"""Input handler abstraction: Software (pyautogui) and Arduino Leonardo (serial HID)."""
import sys
import time
import logging
import subprocess
import platform

logger = logging.getLogger(__name__)


def _ensure_win32_dpi_awareness():
    """Best-effort: force a DPI-aware context for consistent Win32 coordinates.

    On Windows with scaling (e.g. 150%), mixing DPI-aware and DPI-unaware calls
    can yield mismatched coordinate spaces (logical vs physical pixels). HID
    absolute mapping relies on physical coordinates, so we opt into the highest
    awareness context available.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # Prefer per-monitor v2 (Windows 10+)
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        # Fallback for older versions
        shcore = getattr(ctypes.windll, "shcore", None)
        if shcore and hasattr(shcore, "SetProcessDpiAwareness"):
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            shcore.SetProcessDpiAwareness(2)
            return
        if hasattr(user32, "SetProcessDPIAware"):
            user32.SetProcessDPIAware()
    except Exception:
        # Non-fatal: keep running with whatever context is available.
        pass


def _set_cursor_pos(x, y, *, window_id=None):
    """Move cursor to (x, y) using native OS API (physical pixels).

    On high-DPI displays pyautogui normalises coordinates via
    GetSystemMetrics / MOUSEEVENTF_ABSOLUTE which can be off by the
    DPI scale factor.  Calling SetCursorPos directly bypasses that
    normalisation and always operates in *physical* pixel space
    (assuming the process is already DPI-aware, which main.py ensures).

    On Linux we fall back to xdotool, then pyautogui.

    Args:
        x, y: Target coordinates (absolute screen coords, or
              window-relative if *window_id* is given on Linux).
        window_id: Optional X11 window id.  When provided on Linux,
                   ``xdotool mousemove --window`` is used so the
                   coordinates are interpreted relative to the window
                   rather than the screen.  This avoids mismatches
                   between ``xdotool getwindowgeometry`` and the actual
                   display coordinate space (e.g. DPI scaling, Xwayland).
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            return True
        except Exception:
            pass
    elif sys.platform == "linux":
        try:
            cmd = ["xdotool", "mousemove"]
            if window_id is not None:
                cmd += ["--window", str(window_id)]
            cmd += ["--", str(int(x)), str(int(y))]
            subprocess.run(
                cmd,
                check=True, timeout=2,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass
    return False


def _win32_click(button=1, *, repeat=1):
    """Send mouse click via Win32 SendInput at the current cursor position.

    Unlike pyautogui.click(), this does NOT re-read or re-position the
    cursor, so it won't undo SetCursorPos on high-DPI displays.

    Args:
        button: 1=left, 2=middle, 3=right.
        repeat: Number of clicks (2 for double-click).

    Returns True on success, False on failure.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import ctypes.wintypes

        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010

        flags = {
            1: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            2: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
            3: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        }
        down_flag, up_flag = flags.get(button, flags[1])

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("mi", MOUSEINPUT),
            ]

        INPUT_MOUSE = 0

        for _ in range(repeat):
            # Mouse down
            inp_down = INPUT()
            inp_down.type = INPUT_MOUSE
            inp_down.mi.dwFlags = down_flag
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
            # Mouse up
            inp_up = INPUT()
            inp_up.type = INPUT_MOUSE
            inp_up.mi.dwFlags = up_flag
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
            if repeat > 1:
                time.sleep(0.05)

        return True
    except Exception:
        return False


def _xdotool_click(button=1, *, repeat=1):
    """Click using xdotool at the current cursor position.

    More reliable than pyautogui on Linux/X11 because it generates
    proper XTest events that game windows recognise.

    Args:
        button: Mouse button (1=left, 2=middle, 3=right).
        repeat: Number of clicks (2 for double-click).

    Returns True on success, False on failure.
    """
    try:
        cmd = ["xdotool", "click", "--repeat", str(repeat),
               "--delay", "50", str(button)]
        subprocess.run(cmd, check=True, timeout=2,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _xdotool_getmouselocation():
    """Get current cursor position via xdotool.

    Returns (x, y) or None on failure.
    """
    try:
        output = subprocess.check_output(
            ["xdotool", "getmouselocation"],
            text=True, timeout=2, stderr=subprocess.DEVNULL,
        )
        # Output format: x:123 y:456 screen:0 window:789
        parts = {}
        for token in output.strip().split():
            if ":" in token:
                k, v = token.split(":", 1)
                parts[k] = int(v)
        if "x" in parts and "y" in parts:
            return parts["x"], parts["y"]
    except Exception:
        pass
    return None


def _native_click(button=1, *, repeat=1):
    """Send a mouse click using the native OS API (Win32 / xdotool).

    Avoids pyautogui's internal coordinate re-positioning which can
    undo SetCursorPos on high-DPI Windows displays.
    """
    if sys.platform == "win32":
        return _win32_click(button, repeat=repeat)
    elif sys.platform == "linux":
        return _xdotool_click(button, repeat=repeat)
    return False


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

    # When True, the handler positions the cursor itself (e.g. Arduino HID
    # AbsoluteMouse).  AutomationEngine will skip _ensure_cursor_pos and
    # pass coordinates directly to click()/double_click().
    handles_positioning = False

    def __init__(self, korean_method="clipboard"):
        self.korean_method = korean_method

    def click(self, x, y):
        raise NotImplementedError

    def click_in_place(self, count=1):
        """Click at the current cursor position without moving it.

        This is used by AutomationEngine after _ensure_cursor_pos has
        already verified the cursor is at the correct position, so that
        no re-move (which could undo DPI compensation) occurs.

        Args:
            count: Number of clicks (1=single, 2=double).
        """
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
    """Software-based input using pyautogui.

    On high-DPI displays (e.g. 150 % scaling) pyautogui's internal
    coordinate normalisation can send the cursor to the wrong physical
    pixel.  To work around this we position the cursor via the native
    OS API (``SetCursorPos`` on Windows, ``xdotool`` on Linux) and then
    ask pyautogui to click *at the current position* (no coordinates).
    """

    def __init__(self, korean_method="clipboard"):
        super().__init__(korean_method)
        try:
            import pyautogui
        except Exception as e:
            raise ImportError(f"pyautogui unavailable: {e}") from e
        self.pyautogui = pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05

    # -- internal helpers ------------------------------------------------

    def _move(self, x, y):
        """Move cursor to *physical* (x, y) using native API first."""
        if not _set_cursor_pos(x, y):
            # Fallback: let pyautogui try (may be off on high-DPI)
            self.pyautogui.moveTo(x, y)

    # -- public API ------------------------------------------------------

    def click(self, x, y):
        self._move(x, y)
        if not _native_click(1):
            self.pyautogui.click()  # fallback
        logger.debug(f"Software click at ({x}, {y})")

    def click_in_place(self, count=1):
        """Click at the current cursor position without moving it."""
        if not _native_click(1, repeat=count):
            if count >= 2:
                self.pyautogui.doubleClick()
            else:
                self.pyautogui.click()
        logger.debug(f"Software click-in-place (count={count})")

    def double_click(self, x, y):
        self._move(x, y)
        if not _native_click(1, repeat=2):
            self.pyautogui.doubleClick()  # fallback
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
        self._move(x, y)


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

    The CLICK/DBLCLICK commands handle positioning + clicking atomically
    via USB HID, so handles_positioning is True — AutomationEngine will
    pass coordinates directly instead of using SetCursorPos + click_in_place.

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

    handles_positioning = True

    def __init__(self, port="COM3", baudrate=9600, korean_method="clipboard"):
        super().__init__(korean_method)
        import serial
        _ensure_win32_dpi_awareness()
        self.serial = serial.Serial(port, baudrate, timeout=2)
        self.firmware_version = None
        time.sleep(2)  # Wait for Arduino reset
        self._drain_serial()  # Discard READY message from Arduino boot
        self._probe_firmware_version()
        logger.info(f"Arduino connected on {port}")
        # Send screen resolution so Arduino can map absolute coordinates
        self._send_screen_info()
        self._calibrate_hid()
        self._sanity_check_hid_mapping()

    def _probe_firmware_version(self):
        """Query firmware version if supported.

        Newer firmware responds to `VERSION` with `VER:x.y.z`.
        Older firmware may reply `ERR:UNKNOWN` or nothing.
        """
        old_timeout = self.serial.timeout
        self.serial.timeout = 0.4
        try:
            self.serial.write(b"VERSION\n")
            self.serial.flush()
            line = self.serial.readline().decode("utf-8").strip()
            if line.startswith("VER:"):
                self.firmware_version = line.split(":", 1)[1].strip()
                logger.info("Arduino firmware version: %s", self.firmware_version)
            else:
                logger.warning(
                    "Arduino firmware version probe unavailable (response=%r). "
                    "If HID clicks are offset, re-upload latest "
                    "arduino/lineage_hid/lineage_hid.ino.",
                    line,
                )
        except Exception as e:
            logger.warning("Arduino firmware version probe failed: %s", e)
        finally:
            self.serial.timeout = old_timeout

    def _sanity_check_hid_mapping(self):
        """Best-effort startup check for HID absolute mapping accuracy."""
        if platform.system() != "Windows":
            return True
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            origin_x = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            origin_y = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
            width = user32.GetSystemMetrics(78)      # SM_CXVIRTUALSCREEN
            height = user32.GetSystemMetrics(79)     # SM_CYVIRTUALSCREEN
            tx = origin_x + width // 2
            ty = origin_y + height // 2

            pt = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            saved_x, saved_y = pt.x, pt.y

            self._send(f"MOVE {tx} {ty}")
            time.sleep(0.1)
            user32.GetCursorPos(ctypes.byref(pt))
            ax, ay = pt.x, pt.y
            user32.SetCursorPos(saved_x, saved_y)

            err_x = abs(ax - tx)
            err_y = abs(ay - ty)
            if err_x > 120 or err_y > 120:
                self.hid_mapping_ok = False
                logger.warning(
                    "Startup HID sanity check failed: intended (%d,%d) "
                    "actual (%d,%d) err=(%d,%d). "
                    "Arduino absolute mapping may still be inaccurate.",
                    tx, ty, ax, ay, err_x, err_y,
                )
            else:
                self.hid_mapping_ok = True
                logger.info(
                    "Startup HID sanity check OK: err=(%d,%d)",
                    err_x, err_y,
                )
            return self.hid_mapping_ok
        except Exception as e:
            self.hid_mapping_ok = False
            logger.warning("Startup HID sanity check failed: %s", e)
            return False

    def _drain_serial(self):
        """Discard any pending data in serial buffer (e.g. READY message).

        After Arduino reset, the firmware sends 'READY\\n'.  If this is
        not consumed before the first real command, readline() in _send
        will return 'READY' instead of the actual command response,
        causing a permanent 1-response offset.
        """
        old_timeout = self.serial.timeout
        self.serial.timeout = 0.1
        try:
            while True:
                line = self.serial.readline().decode("utf-8").strip()
                if not line:
                    break
                logger.debug(f"Arduino drain: {line}")
        finally:
            self.serial.timeout = old_timeout

    def _send(self, command):
        """Send command to Arduino and wait for ACK."""
        cmd = command.strip() + "\n"
        self.serial.write(cmd.encode("utf-8"))
        self.serial.flush()
        # Wait for acknowledgement
        response = self.serial.readline().decode("utf-8").strip()
        if not response:
            logger.warning(f"Arduino NO RESPONSE for: {command}")
        else:
            logger.info(f"Arduino cmd: {command} -> {response}")
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

    def _calibrate_hid(self):
        """Auto-calibrate HID absolute mouse coordinate mapping.

        Windows may map HID absolute coordinates (0-32767) to a
        different coordinate space than what GetSystemMetrics reports,
        especially on high-DPI or multi-monitor setups.

        This method moves the cursor to two known positions via Arduino
        MOVE, reads back actual cursor positions via GetCursorPos, and
        re-sends corrected SCREEN dimensions so future clicks land at
        the intended pixel.
        """
        if platform.system() != "Windows":
            return

        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32

            # Current SCREEN values sent to Arduino
            origin_x = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            origin_y = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
            width = user32.GetSystemMetrics(78)       # SM_CXVIRTUALSCREEN
            height = user32.GetSystemMetrics(79)      # SM_CYVIRTUALSCREEN

            if width <= 0 or height <= 0:
                return

            # Two test points at 1/3 and 2/3 of the virtual desktop
            t1x = origin_x + width // 3
            t1y = origin_y + height // 3
            t2x = origin_x + 2 * width // 3
            t2y = origin_y + 2 * height // 3

            # Save current cursor position to restore later
            pt = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            saved_x, saved_y = pt.x, pt.y

            # Move to first test point and measure
            self._send(f"MOVE {t1x} {t1y}")
            time.sleep(0.1)
            user32.GetCursorPos(ctypes.byref(pt))
            a1x, a1y = pt.x, pt.y

            # Move to second test point and measure
            self._send(f"MOVE {t2x} {t2y}")
            time.sleep(0.1)
            user32.GetCursorPos(ctypes.byref(pt))
            a2x, a2y = pt.x, pt.y

            # Restore cursor position
            user32.SetCursorPos(saved_x, saved_y)

            dx_target = t2x - t1x   # == width // 3
            dy_target = t2y - t1y   # == height // 3
            dx_actual = a2x - a1x
            dy_actual = a2y - a1y

            if dx_target == 0 or dy_target == 0:
                logger.warning("HID calibration: zero range, skipping")
                return

            scale_x = dx_actual / dx_target
            scale_y = dy_actual / dy_target

            # If the mapping is already accurate, no correction needed
            if abs(scale_x - 1.0) < 0.02 and abs(scale_y - 1.0) < 0.02:
                logger.info(
                    "HID calibration: no correction needed "
                    f"(scale_x={scale_x:.3f} scale_y={scale_y:.3f})"
                )
                return

            # Compute the real coordinate space Windows uses for HID mapping
            # actual = (target - originX) * realWidth / width + realOriginX
            real_width = round(width * scale_x)
            real_height = round(height * scale_y)
            real_origin_x = round(a1x - (t1x - origin_x) * scale_x)
            real_origin_y = round(a1y - (t1y - origin_y) * scale_y)

            # Re-send corrected SCREEN dimensions
            self._send(
                f"SCREEN {real_origin_x} {real_origin_y} "
                f"{real_width} {real_height}"
            )
            # Validate that correction really improves landing error.
            verify_tx = origin_x + width // 2
            verify_ty = origin_y + height // 2
            self._send(f"MOVE {verify_tx} {verify_ty}")
            time.sleep(0.1)
            user32.GetCursorPos(ctypes.byref(pt))
            vx, vy = pt.x, pt.y
            err_x = abs(vx - verify_tx)
            err_y = abs(vy - verify_ty)

            # If calibration is clearly wrong (e.g. cursor clipping/game lock),
            # restore the original mapping to avoid making clicks worse.
            if err_x > 120 or err_y > 120:
                self._send(f"SCREEN {origin_x} {origin_y} {width} {height}")
                logger.warning(
                    "HID calibration rejected (verify error too large: "
                    f"dx={err_x}, dy={err_y}). Restored original SCREEN."
                )
            else:
                logger.info(
                    f"HID calibrated: original=({origin_x},{origin_y} "
                    f"{width}x{height}) -> corrected=({real_origin_x},"
                    f"{real_origin_y} {real_width}x{real_height}) "
                    f"scale=({scale_x:.3f},{scale_y:.3f}) "
                    f"verify_err=({err_x},{err_y})"
                )

        except Exception as e:
            logger.warning(f"HID calibration failed: {e}")

    def click(self, x, y):
        self._send(f"CLICK {x} {y}")
        logger.info(f"Arduino click at ({x}, {y})")

    def click_in_place(self, count=1):
        """Click at current cursor position (Arduino falls back to native click)."""
        if not _native_click(1, repeat=count):
            logger.warning("Arduino click_in_place: native click failed")

    def double_click(self, x, y):
        """Double-click via Arduino HID.

        Uses two separate CLICK commands with a short delay instead of
        DBLCLICK, because some games don't recognise the AbsoluteMouse
        double-click event properly.
        """
        self._send(f"CLICK {x} {y}")
        time.sleep(0.08)
        self._send(f"CLICK {x} {y}")
        logger.info(f"Arduino double-click (2xCLICK) at ({x}, {y})")

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
