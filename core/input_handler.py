"""Input handler abstraction: Software (pyautogui) and Arduino Leonardo (serial HID)."""
import time
import logging

logger = logging.getLogger(__name__)


class InputHandler:
    """Abstract base for input methods."""

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

    def __init__(self):
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
        self.pyautogui.typewrite(text, interval=0.05)
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

    def __init__(self, port="COM3", baudrate=9600):
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
        self._send(f"TYPE {text}")

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


def create_input_handler(method="software", port="COM3", baudrate=9600):
    """Factory function to create the appropriate input handler."""
    if method == "arduino":
        return ArduinoInput(port=port, baudrate=baudrate)
    return SoftwareInput()
