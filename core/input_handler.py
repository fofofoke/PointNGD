"""Input handler abstraction: Software (pyautogui) and Arduino Leonardo (serial HID)."""
import time
import logging
import subprocess
import platform

logger = logging.getLogger(__name__)


def _copy_to_clipboard(text):
    """Copy text to system clipboard (cross-platform)."""
    system = platform.system()
    if system == "Windows":
        # Use PowerShell to avoid encoding issues with clip.exe
        process = subprocess.Popen(
            ["powershell", "-command", f"Set-Clipboard -Value '{text}'"],
            stdin=subprocess.PIPE,
        )
        process.communicate()
    elif system == "Darwin":
        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        process.communicate(text.encode("utf-8"))
    else:
        process = subprocess.Popen(
            ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE,
        )
        process.communicate(text.encode("utf-8"))


def _sendinput_unicode(text):
    """Type Unicode text using Win32 SendInput with KEYEVENTF_UNICODE.

    This sends each character as a virtual keyboard event at the OS level,
    bypassing the IME pipeline. Works with most programs including games
    that ignore clipboard paste.

    Requires: pywin32 (win32api, win32con) on Windows.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]

            _fields_ = [
                ("type", wintypes.DWORD),
                ("union", _INPUT_UNION),
            ]

        for char in text:
            code = ord(char)

            # Key down
            inputs = (INPUT * 2)()

            inputs[0].type = INPUT_KEYBOARD
            inputs[0].union.ki.wVk = 0
            inputs[0].union.ki.wScan = code
            inputs[0].union.ki.dwFlags = KEYEVENTF_UNICODE
            inputs[0].union.ki.time = 0
            inputs[0].union.ki.dwExtraInfo = None

            # Key up
            inputs[1].type = INPUT_KEYBOARD
            inputs[1].union.ki.wVk = 0
            inputs[1].union.ki.wScan = code
            inputs[1].union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            inputs[1].union.ki.time = 0
            inputs[1].union.ki.dwExtraInfo = None

            user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
            time.sleep(0.03)

        logger.debug(f"SendInput unicode: {text}")
        return True

    except Exception as e:
        logger.error(f"SendInput failed: {e}")
        return False


def _type_non_ascii(text, method="clipboard", paste_func=None):
    """Type non-ASCII text using the specified method.

    Args:
        text: The text to type.
        method: "clipboard" for Ctrl+V paste, "sendinput" for Win32 SendInput.
        paste_func: Callable that performs Ctrl+V (differs per input handler).
    """
    if method == "sendinput":
        if platform.system() == "Windows":
            success = _sendinput_unicode(text)
            if success:
                return
            logger.warning("SendInput failed, falling back to clipboard paste")
        else:
            logger.warning("SendInput is Windows-only, falling back to clipboard paste")

    # Clipboard fallback
    _copy_to_clipboard(text)
    time.sleep(0.1)
    if paste_func:
        paste_func()
    time.sleep(0.1)


class InputHandler:
    """Abstract base for input methods."""

    def __init__(self, korean_method="clipboard"):
        self.korean_method = korean_method

    def click(self, x, y):
        raise NotImplementedError

    def double_click(self, x, y):
        raise NotImplementedError

    def type_text(self, text):
        raise NotImplementedError

    def press_key(self, key):
        raise NotImplementedError

    def hotkey(self, *keys):
        raise NotImplementedError

    def move_to(self, x, y):
        raise NotImplementedError

    def close(self):
        pass


class SoftwareInput(InputHandler):
    """Software-based input using pyautogui."""

    def __init__(self, korean_method="clipboard"):
        super().__init__(korean_method)
        import pyautogui
        self.pyautogui = pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05

    def click(self, x, y):
        self.pyautogui.click(x, y)
        logger.debug(f"Software click at ({x}, {y})")

    def double_click(self, x, y):
        self.pyautogui.doubleClick(x, y)
        logger.debug(f"Software double-click at ({x}, {y})")

    def type_text(self, text):
        """Type text. Uses clipboard/SendInput for non-ASCII (Korean etc)."""
        if all(ord(c) < 128 for c in text):
            self.pyautogui.typewrite(text, interval=0.05)
        else:
            _type_non_ascii(
                text,
                method=self.korean_method,
                paste_func=lambda: self.pyautogui.hotkey("ctrl", "v"),
            )
        logger.debug(f"Software type: {text}")

    def press_key(self, key):
        self.pyautogui.press(key)
        logger.debug(f"Software press: {key}")

    def hotkey(self, *keys):
        self.pyautogui.hotkey(*keys)
        logger.debug(f"Software hotkey: {keys}")

    def move_to(self, x, y):
        self.pyautogui.moveTo(x, y)


class ArduinoInput(InputHandler):
    """Arduino Leonardo-based HID input via serial communication.

    Protocol: Send commands as text lines.
    Commands:
        CLICK x y         - Single click
        DBLCLICK x y      - Double click
        TYPE text          - Type text
        KEY keyname        - Press key
        HOTKEY key1+key2   - Key combination
        MOVE x y           - Move mouse
    """

    def __init__(self, port="COM3", baudrate=9600, korean_method="clipboard"):
        super().__init__(korean_method)
        import serial
        self.serial = serial.Serial(port, baudrate, timeout=2)
        time.sleep(2)  # Wait for Arduino reset
        logger.info(f"Arduino connected on {port}")

    def _send(self, command):
        """Send command to Arduino and wait for ACK."""
        cmd = command.strip() + "\n"
        self.serial.write(cmd.encode("utf-8"))
        self.serial.flush()
        # Wait for acknowledgement
        response = self.serial.readline().decode("utf-8").strip()
        logger.debug(f"Arduino cmd: {command} -> {response}")
        time.sleep(0.05)
        return response

    def click(self, x, y):
        self._send(f"CLICK {x} {y}")

    def double_click(self, x, y):
        self._send(f"DBLCLICK {x} {y}")

    def type_text(self, text):
        """Type text. Uses clipboard/SendInput for non-ASCII (Korean etc)."""
        if all(ord(c) < 128 for c in text):
            self._send(f"TYPE {text}")
        else:
            _type_non_ascii(
                text,
                method=self.korean_method,
                paste_func=lambda: self._send("HOTKEY ctrl+v"),
            )
        logger.debug(f"Arduino type: {text}")

    def press_key(self, key):
        self._send(f"KEY {key}")

    def hotkey(self, *keys):
        combo = "+".join(keys)
        self._send(f"HOTKEY {combo}")

    def move_to(self, x, y):
        self._send(f"MOVE {x} {y}")

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info("Arduino disconnected")


def create_input_handler(method="software", port="COM3", baudrate=9600,
                         korean_method="clipboard"):
    """Factory function to create the appropriate input handler."""
    if method == "arduino":
        return ArduinoInput(port=port, baudrate=baudrate, korean_method=korean_method)
    return SoftwareInput(korean_method=korean_method)
