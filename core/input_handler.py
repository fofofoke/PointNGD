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
        # Use PowerShell with UTF-8 encoding to handle Korean and other non-ASCII text
        process = subprocess.Popen(
            ["powershell", "-command",
             "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
             "$input | Set-Clipboard"],
            stdin=subprocess.PIPE,
        )
        process.communicate(text.encode("utf-8"))
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

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

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


def _get_linux_screen_size():
    """Detect screen resolution on Linux. Returns (width, height)."""
    # Try xdpyinfo first (most reliable for total screen area)
    try:
        out = subprocess.check_output(
            ["xdpyinfo"], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if "dimensions:" in line:
                # e.g. "  dimensions:    3840x2160 pixels ..."
                dim = line.split()[1]
                w, h = dim.split("x")
                logger.info("Screen size from xdpyinfo: %sx%s", w, h)
                return int(w), int(h)
    except Exception:
        pass
    # Try xrandr (look for current mode)
    try:
        out = subprocess.check_output(
            ["xrandr", "--current"], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if " connected " in line and "+" in line:
                # e.g. "DP-1 connected 3840x2160+0+0 ..."
                for part in line.split():
                    if "x" in part and "+" in part:
                        res = part.split("+")[0]
                        w, h = res.split("x")
                        logger.info("Screen size from xrandr: %sx%s", w, h)
                        return int(w), int(h)
    except Exception:
        pass
    # Try pyautogui
    try:
        import pyautogui
        w, h = pyautogui.size()
        logger.info("Screen size from pyautogui: %dx%d", w, h)
        return w, h
    except Exception:
        pass
    # Try python-mss
    try:
        import mss
        with mss.mss() as sct:
            # monitors[0] is the virtual screen (all monitors combined)
            mon = sct.monitors[0]
            logger.info("Screen size from mss: %dx%d", mon["width"], mon["height"])
            return mon["width"], mon["height"]
    except Exception:
        pass
    logger.warning("Could not detect screen size, defaulting to 1920x1080")
    return 1920, 1080


class ArduinoInput(InputHandler):
    """Arduino Leonardo-based HID input via serial communication.

    Uses AbsoluteMouse (HID-Project library) for pixel-accurate positioning.
    Sends screen resolution on connect so Arduino can map coordinates correctly.

    Protocol: Send commands as text lines.
    Commands:
        CLICK x y         - Single click
        DBLCLICK x y      - Double click
        TYPE text          - Type text
        KEY keyname        - Press key
        HOTKEY key1+key2   - Key combination
        MOVE x y           - Move mouse
        SCREEN ox oy w h   - Set virtual desktop dimensions
    """

    def __init__(self, port="COM3", baudrate=9600, korean_method="clipboard"):
        super().__init__(korean_method)
        import serial
        self.serial = serial.Serial(port, baudrate, timeout=2)
        time.sleep(2)  # Wait for Arduino reset
        logger.info(f"Arduino connected on {port}")
        # Send screen resolution so Arduino can map absolute coordinates
        self._send_screen_info()

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

    def _send_screen_info(self):
        """Send virtual desktop dimensions to Arduino for absolute mouse mapping."""
        try:
            if platform.system() == "Windows":
                import ctypes
                user32 = ctypes.windll.user32
                # Virtual desktop = combined area of all monitors
                origin_x = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
                origin_y = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
                width = user32.GetSystemMetrics(78)      # SM_CXVIRTUALSCREEN
                height = user32.GetSystemMetrics(79)     # SM_CYVIRTUALSCREEN
            else:
                origin_x, origin_y = 0, 0
                width, height = _get_linux_screen_size()

            self._send(f"SCREEN {origin_x} {origin_y} {width} {height}")
            logger.info(
                f"Screen info sent to Arduino: origin=({origin_x},{origin_y}) "
                f"size={width}x{height}"
            )
        except Exception as e:
            logger.warning(f"Failed to send screen info: {e}, using defaults")

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
