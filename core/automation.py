"""Main automation workflow engine for LC AB."""
import math
import os
import sys
import time
import logging
import threading
from datetime import datetime

from core.image_recognition import ImageRecognition
from core.input_handler import create_input_handler
from core.telegram_notifier import TelegramNotifier
from core.stats import StatsTracker
from gui.window_utils import find_windows_by_title, get_window_rect

logger = logging.getLogger(__name__)


def _set_foreground_window(hwnd):
    """Bring the target window to the foreground.

    Windows: Tries SetForegroundWindow, falls back to simulating an Alt
    key press (which satisfies the OS foreground-lock policy) and retrying.

    Linux: Uses xdotool windowactivate to focus the window.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # First attempt
            if user32.SetForegroundWindow(int(hwnd)):
                return
            # OS may block SetForegroundWindow unless the calling thread
            # owns the foreground lock.  A brief Alt press/release is the
            # standard workaround.
            user32.keybd_event(0x12, 0, 0, 0)       # Alt down
            user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
            user32.SetForegroundWindow(int(hwnd))
        except Exception:
            pass
    elif sys.platform == "linux":
        import subprocess
        try:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", str(hwnd)],
                check=True, timeout=3,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def _get_cursor_pos_win32():
    """Get cursor position via Win32 GetCursorPos (physical pixels).

    Returns (x, y) or None on failure.  Unlike pyautogui.position(),
    this always returns physical pixel coordinates matching SetCursorPos.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import ctypes.wintypes
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


class AutomationEngine:
    """Executes the full Lineage Classic automation workflow.

    Workflow steps:
    1)  Character select screen: double-click empty slot
    2)  Character creation screen: click knight icon
    3)  Verify knight image at position, retry if wrong
    4)  Click stat position 4 times
    5)  Click name input position, type character name
    6)  Click confirm button to create character
    7)  Auto-return to select screen: double-click character slot to enter game
    8)  Press tab, double-click item icon
    9)  Left popup appears: click specific text in popup
    10) After configurable delay, click point then find & click scarecrow repeatedly
    11) After each scarecrow click, check level-up (image/OCR). Check MP at each level:
        - Level 2, MP 3: continue scarecrow, then go to step 15
        - Level 3, MP 5: continue; else go to step 12
        - Level 4, MP 7: continue; else go to step 12
        - Level 5, MP 9: SUCCESS -> telegram notify & stop; else go to step 12
    12) Ctrl+Q, click exit confirm to return to character select
    13) Select character, click delete, wait for delete popup
    14) After delete popup disappears, go to step 1
    15) MP check at higher levels (handled in step 11 logic)
    """

    # Workflow states
    STATE_IDLE = "idle"
    STATE_RUNNING = "running"
    STATE_PAUSED = "paused"
    STATE_STOPPED = "stopped"
    STATE_SUCCESS = "success"

    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_callback = log_callback
        self.state = self.STATE_IDLE
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default

        self._state_lock = threading.Lock()
        self.recognizer = ImageRecognition()
        self.input = None
        self.telegram = TelegramNotifier(
            config.get("telegram_bot_token", ""),
            config.get("telegram_chat_id", ""),
        )
        self.iteration_count = 0
        self.current_step = 0
        self.stats = StatsTracker()

        # Target window offset (for window-relative coordinates)
        self._win_offset_x = 0
        self._win_offset_y = 0
        self._hid_recalibration_attempted = False
        self._hid_fallback_to_host_click = False
        self._target_window_id = None
        # DPI ratio for scaling ROI/click coordinates (runtime / capture)
        self._roi_dpi_ratio = 1.0

        # Error screenshot directory
        self._error_ss_dir = config.get("error_screenshot_dir", "error_screenshots")
        os.makedirs(self._error_ss_dir, exist_ok=True)

        # OCR retry count
        self._ocr_retries = config.get("ocr_retry_count", 3)

        # Step retry settings
        step_retry = config.get("step_retry", {})
        self._step_max_retries = step_retry.get("max_retries", 3)
        self._step_retry_delay = step_retry.get("retry_delay", 2)

    def _log(self, msg, level="info"):
        logger.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self.log_callback:
            self.log_callback(msg)

    def _check_stop(self):
        """Check if stop was requested. Raises StopIteration if so."""
        if self._stop_event.is_set():
            raise StopIteration("Automation stopped by user")

    def _wait_pause(self):
        """Block while paused."""
        while not self._pause_event.is_set():
            if self._stop_event.is_set():
                raise StopIteration("Automation stopped by user")
            time.sleep(0.1)

    def _sleep(self, seconds):
        """Interruptible sleep."""
        end = time.time() + seconds
        while time.time() < end:
            self._check_stop()
            self._wait_pause()
            remaining = end - time.time()
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining))

    def _configure_dpi_scaling(self):
        """Detect DPI mismatch between capture-time and runtime.

        If the user changed their display scaling since templates were
        captured, this configures the image recogniser to auto-resize
        templates so they still match.
        """
        from gui.window_utils import get_dpi_scale

        capture_scales = self.config.get("capture_dpi_scale", {})
        if not capture_scales:
            return  # No saved DPI info — templates were captured before this feature

        # Use the ROI scale or the first template scale as representative
        capture_scale = capture_scales.get("roi")
        if capture_scale is None:
            for v in capture_scales.values():
                if isinstance(v, (int, float)) and v > 0:
                    capture_scale = v
                    break
        if not capture_scale:
            return

        runtime_scale = get_dpi_scale(self._target_window_id)
        self.recognizer.set_template_dpi_ratio(capture_scale, runtime_scale)
        self._roi_dpi_ratio = runtime_scale / capture_scale

        if abs(runtime_scale - capture_scale) > 0.01:
            self._log(
                f"DPI changed: captured at {capture_scale:.0%}, "
                f"current {runtime_scale:.0%}. "
                f"Templates will be auto-resized. "
                f"For best accuracy, recapture in ROI Editor.",
                "warning",
            )

    def _refresh_window(self):
        """Refresh target window position. Returns True if OK."""
        title = self.config.get("target_window_title", "")
        if not title:
            self._win_offset_x = 0
            self._win_offset_y = 0
            logger.debug("No target window title set, using offset (0, 0)")
            return True
        windows = find_windows_by_title(title)
        if not windows:
            self._log(f"Target window '{title}' not found!", "warning")
            return False
        self._target_window_id = windows[0][0]
        rect = get_window_rect(self._target_window_id)
        if not rect:
            self._log("Failed to get target window rect!", "warning")
            return False
        self._win_offset_x = rect["x"]
        self._win_offset_y = rect["y"]
        logger.debug(
            "Window refresh: hwnd=%s title='%s' rect=(%d,%d %dx%d)",
            self._target_window_id, windows[0][1],
            rect["x"], rect["y"], rect["w"], rect["h"],
        )
        return True

    def _abs_roi(self, roi):
        """Convert window-relative ROI dict to absolute screen ROI.

        When the DPI scale has changed since capture, coordinates are
        rescaled so they point to the same logical area on screen.
        """
        if not roi:
            return roi
        r = self._roi_dpi_ratio
        return {
            "x": round(roi["x"] * r) + self._win_offset_x,
            "y": round(roi["y"] * r) + self._win_offset_y,
            "w": round(roi["w"] * r),
            "h": round(roi["h"] * r),
        }

    def _abs_pos(self, pos):
        """Convert window-relative position dict to absolute screen position."""
        if not pos:
            return pos
        r = self._roi_dpi_ratio
        return {
            "x": round(pos["x"] * r) + self._win_offset_x,
            "y": round(pos["y"] * r) + self._win_offset_y,
        }

    # ------------------------------------------------------------------
    # Centralised click helpers – every click in the bot flows through
    # these two methods so that:
    #   1. The window position is refreshed right before the click.
    #   2. The game window is brought to the foreground.
    #   3. The final coordinates are validated and logged.
    # ------------------------------------------------------------------

    def _click(self, x, y, *, skip_focus=False):
        """Click at absolute screen coordinates (x, y).

        For handlers that position the cursor themselves (e.g. Arduino HID),
        coordinates are passed directly to click().  For software handlers,
        the cursor is first moved and verified via _ensure_cursor_pos, then
        clicked in place so the verified position is not disturbed.
        """
        self._focus_and_validate(x, y, skip_focus)
        if self.input.handles_positioning and not self._hid_fallback_to_host_click:
            self.input.click(x, y)
            self._verify_hid_cursor(x, y)
        else:
            self._ensure_cursor_pos(x, y)
            self.input.click_in_place()
        logger.debug("Automation click at (%d, %d)", x, y)

    def _double_click(self, x, y, *, skip_focus=False):
        """Double-click at absolute screen coordinates (x, y)."""
        self._focus_and_validate(x, y, skip_focus)
        if self.input.handles_positioning and not self._hid_fallback_to_host_click:
            self.input.double_click(x, y)
            self._verify_hid_cursor(x, y)
        else:
            self._ensure_cursor_pos(x, y)
            self.input.click_in_place(count=2)
        logger.debug("Automation double-click at (%d, %d)", x, y)

    def _verify_hid_cursor(self, intended_x, intended_y):
        """Log actual cursor position after HID click for diagnostics.

        HID AbsoluteMouse can land at the wrong position when:
        - DPI scaling causes coordinate space mismatch
        - Multi-monitor HID mapping doesn't match virtual desktop size
        """
        time.sleep(0.03)
        actual = self._get_actual_cursor_pos()
        if actual:
            ax, ay = actual
            dx, dy = ax - intended_x, ay - intended_y
            if abs(dx) > 10 or abs(dy) > 10:
                self._log(
                    f"HID CURSOR MISMATCH: intended ({intended_x},{intended_y}) "
                    f"actual ({ax},{ay}) delta=({dx:+d},{dy:+d}). "
                    f"Arduino coordinates are landing wrong!",
                    "warning",
                )
                if (not self._hid_recalibration_attempted and
                        (abs(dx) > 100 or abs(dy) > 100)):
                    calibrate = getattr(self.input, "_calibrate_hid", None)
                    if callable(calibrate):
                        self._hid_recalibration_attempted = True
                        self._log(
                            "Large HID mismatch detected. Attempting one-time "
                            "Arduino HID recalibration.",
                            "warning",
                        )
                        try:
                            calibrate()
                        except Exception as e:
                            logger.warning("One-time HID recalibration failed: %s", e)
                elif (self._hid_recalibration_attempted and
                      (abs(dx) > 100 or abs(dy) > 100) and
                      not self._hid_fallback_to_host_click):
                    self._hid_fallback_to_host_click = True
                    self._log(
                        "HID mismatch persists after recalibration. "
                        "Switching to host cursor move + native click fallback.",
                        "warning",
                    )
            else:
                logger.debug(
                    "HID cursor OK: intended (%d,%d) actual (%d,%d)",
                    intended_x, intended_y, ax, ay,
                )

    def _get_actual_cursor_pos(self):
        """Return (x, y) of the current cursor using native OS API."""
        if sys.platform == "win32":
            pos = _get_cursor_pos_win32()
            if pos:
                return pos
        elif sys.platform == "linux":
            from core.input_handler import _xdotool_getmouselocation
            pos = _xdotool_getmouselocation()
            if pos:
                return pos
        import pyautogui
        return pyautogui.position()

    def _ensure_cursor_pos(self, x, y):
        """Move cursor to (x, y) and verify it arrived before clicking.

        On high-DPI displays SetCursorPos can land the cursor at the
        wrong physical pixel when DPI virtualisation is active.  This
        method moves the cursor, reads back the actual position, and if
        there is a mismatch it calculates a *compensated* coordinate so
        the cursor actually ends up where intended.

        The compensation formula is:
            corrected = intended - (actual - intended) = 2*intended - actual
        This mirrors the offset so the next SetCursorPos lands correctly.

        Up to 3 attempts are made (initial + 2 corrections).

        On Linux, if a target window is known, we use window-relative
        movement (``xdotool mousemove --window``) which is immune to
        coordinate-space mismatches between ``xdotool getwindowgeometry``
        and the actual display (DPI scaling, Xwayland offsets, etc.).
        """
        from core.input_handler import _set_cursor_pos

        # -- Linux window-relative path ------------------------------------
        if sys.platform == "linux" and self._target_window_id:
            win_rel_x = int(x - self._win_offset_x)
            win_rel_y = int(y - self._win_offset_y)
            _set_cursor_pos(
                win_rel_x, win_rel_y,
                window_id=self._target_window_id,
            )
            time.sleep(0.02)
            logger.debug(
                "Window-relative move: abs(%d,%d) -> win_rel(%d,%d) "
                "[window=%s offset=(%d,%d)]",
                x, y, win_rel_x, win_rel_y,
                self._target_window_id,
                self._win_offset_x, self._win_offset_y,
            )
            return

        # -- Absolute path (Windows / no target window) --------------------
        max_attempts = 3
        target_x, target_y = int(x), int(y)

        for attempt in range(max_attempts):
            try:
                _set_cursor_pos(target_x, target_y)
                time.sleep(0.02)  # brief settle time

                actual_x, actual_y = self._get_actual_cursor_pos()
                dx = actual_x - x
                dy = actual_y - y

                if abs(dx) <= 5 and abs(dy) <= 5:
                    if attempt > 0:
                        self._log(
                            f"Cursor position corrected (attempt {attempt + 1}): "
                            f"intended ({x},{y}) actual ({actual_x},{actual_y})"
                        )
                    logger.debug(
                        "Cursor position OK (attempt %d): intended (%d,%d) "
                        "actual (%d,%d)",
                        attempt + 1, x, y, actual_x, actual_y,
                    )
                    return

                if attempt < max_attempts - 1:
                    # Compute compensated target: mirror the error
                    target_x = int(2 * x - actual_x)
                    target_y = int(2 * y - actual_y)
                    self._log(
                        f"CURSOR MISMATCH (attempt {attempt + 1}): "
                        f"intended ({x},{y}) actual ({actual_x},{actual_y}) "
                        f"delta=({dx:+d},{dy:+d}). "
                        f"Compensating → SetCursorPos({target_x},{target_y})",
                        "warning",
                    )
                    time.sleep(0.03)
                else:
                    self._log(
                        f"CURSOR STILL MISMATCHED after {max_attempts} attempts: "
                        f"intended ({x},{y}) actual ({actual_x},{actual_y}) "
                        f"delta=({dx:+d},{dy:+d}). DPI scaling issue persists.",
                        "warning",
                    )
            except Exception as e:
                logger.debug("Could not verify cursor position (attempt %d): %s",
                             attempt + 1, e)
                return

    def _focus_and_validate(self, x, y, skip_focus):
        """Shared logic for _click/_double_click."""
        if not skip_focus and self._target_window_id:
            _set_foreground_window(self._target_window_id)
            # Brief delay so the OS finishes the focus switch before we
            # send mouse events — without this the first click can be
            # swallowed by the window-activation itself.
            time.sleep(0.15)
        # Warn if coordinates fall outside the known game window area
        if self._target_window_id:
            rect = get_window_rect(self._target_window_id)
            if rect:
                in_x = rect["x"] <= x <= rect["x"] + rect["w"]
                in_y = rect["y"] <= y <= rect["y"] + rect["h"]
                if not (in_x and in_y):
                    self._log(
                        f"WARNING: Click ({x}, {y}) is OUTSIDE game window "
                        f"({rect['x']},{rect['y']} {rect['w']}x{rect['h']})! "
                        f"win_offset=({self._win_offset_x},{self._win_offset_y})",
                        "warning",
                    )
                else:
                    logger.debug(
                        "Click (%d, %d) inside window (%d,%d %dx%d) OK",
                        x, y, rect["x"], rect["y"], rect["w"], rect["h"],
                    )

    def _wait_and_find(self, image_key, region_key, timeout=10, interval=0.5):
        """Wait for a template image to appear in a region.
        Returns (found, abs_x, abs_y, confidence).
        """
        template_path = self.config["images"].get(image_key, "")
        raw_roi = self.config["roi"].get(region_key)
        region = self._abs_roi(raw_roi)
        if not template_path:
            self._log(f"Warning: No image set for '{image_key}'", "warning")
            return False, 0, 0, 0.0

        logger.info(
            "wait_and_find: key='%s' template='%s' "
            "roi_config=%s win_offset=(%d,%d) abs_region=%s",
            image_key, os.path.basename(template_path),
            raw_roi, self._win_offset_x, self._win_offset_y, region,
        )

        end_time = time.time() + timeout
        while time.time() < end_time:
            self._check_stop()
            self._wait_pause()
            self._refresh_window()
            region = self._abs_roi(self.config["roi"].get(region_key))
            threshold = self._get_image_threshold(image_key)
            found, ax, ay, conf = self.recognizer.find_template_in_region(
                template_path, region, threshold=threshold
            )
            if found:
                return True, ax, ay, conf
            time.sleep(interval)
        return False, 0, 0, 0.0

    def _get_image_threshold(self, image_key, default=None):
        """Return per-image match threshold from config (0.1~0.99)."""
        thresholds = self.config.get("image_thresholds", {})
        raw = thresholds.get(image_key)
        if raw is None:
            return default
        try:
            val = float(raw)
            if 0.1 <= val <= 0.99:
                return val
        except (TypeError, ValueError):
            pass
        return default

    def _ocr_number_retry(self, region, retries=None):
        """OCR a number with retries for reliability.
        Returns int or None.
        """
        retries = retries if retries is not None else self._ocr_retries
        for attempt in range(retries):
            result = self.recognizer.ocr_number(region)
            if result is not None:
                return result
            if attempt < retries - 1:
                time.sleep(0.3)
        return None

    def _save_error_screenshot(self, step_name):
        """Save a screenshot when an error occurs for debugging."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"error_{step_name}_{timestamp}.png"
            filepath = os.path.join(self._error_ss_dir, filename)
            self.recognizer.save_region_as_template(None, filepath)
            self._log(f"Error screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            self._log(f"Failed to save error screenshot: {e}", "error")
            return None

    def _run_step_with_retry(self, step_func, step_name, max_retries=None):
        """Run a step function with retry logic.
        step_func should return (success, *results).
        Returns the step_func result on success, or None on all retries exhausted.
        """
        max_retries = max_retries if max_retries is not None else self._step_max_retries
        for attempt in range(max_retries):
            self._check_stop()
            self._wait_pause()
            result = step_func()
            if result[0]:  # success
                return result
            if attempt < max_retries - 1:
                self._log(f"Step '{step_name}' failed (attempt {attempt + 1}/{max_retries}), "
                          f"retrying in {self._step_retry_delay}s...", "warning")
                self._sleep(self._step_retry_delay)
            else:
                self._log(f"Step '{step_name}' failed after {max_retries} attempts", "error")
                self._save_error_screenshot(step_name)
        return None

    def start(self):
        """Start automation in a new thread."""
        with self._state_lock:
            if self.state == self.STATE_RUNNING:
                self._log("Already running")
                return
            self._stop_event.clear()
            self._pause_event.set()
            self.iteration_count = 0
            self.current_step = 0
            self.state = self.STATE_RUNNING
        thread = threading.Thread(target=self._run_loop, daemon=True)
        thread.start()

    def pause(self):
        if self.state == self.STATE_RUNNING:
            self._pause_event.clear()
            self.state = self.STATE_PAUSED
            self._log("Paused")

    def resume(self):
        if self.state == self.STATE_PAUSED:
            self._pause_event.set()
            self.state = self.STATE_RUNNING
            self._log("Resumed")

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused
        self.state = self.STATE_STOPPED
        self._log("Stop requested")

    def _init_input(self):
        """Initialize the input handler based on config."""
        method = self.config.get("input_method", "software")
        port = self.config.get("arduino_port", "COM3")
        baudrate = self.config.get("arduino_baudrate", 9600)
        korean_method = self.config.get("korean_input_method", "clipboard")
        self.input = create_input_handler(method, port, baudrate, korean_method)
        self._log(f"Input method: {method}")

    def _run_loop(self):
        """Main automation loop."""
        self.stats.reset()
        self.stats.start()
        try:
            self._init_input()
            if not self._refresh_window():
                self._log("Cannot find target window. Check 'Target Window' setting.", "error")
                return
            # Configure template DPI scaling for runtime
            self._configure_dpi_scaling()
            # Log full coordinate diagnostic on startup
            rect = get_window_rect(self._target_window_id) if self._target_window_id else None
            self._log(
                f"Automation started: window_id={self._target_window_id} "
                f"rect={rect} offset=({self._win_offset_x},{self._win_offset_y})"
            )
            while not self._stop_event.is_set():
                self.iteration_count += 1
                self.stats.record_iteration()
                self._log(f"=== Iteration {self.iteration_count} "
                          f"[{self.stats.elapsed_str()}] ===")
                result = self._run_single_cycle()
                if result == "success":
                    self.state = self.STATE_SUCCESS
                    self.stats.record_success()
                    self._log("SUCCESS! MP 9 at Level 5 found!")
                    self._log(f"Stats: {self.stats.total_iterations} iterations, "
                              f"{self.stats.elapsed_str()} elapsed")
                    self.telegram.send_message_async(
                        f"LC AB: SUCCESS! Found MP 9 at Level 5. "
                        f"Iteration: {self.iteration_count}, "
                        f"Time: {self.stats.elapsed_str()}"
                    )
                    break
                elif result == "delete_and_retry":
                    self._log("Character doesn't meet criteria, deleting and retrying...")
                    continue
                elif result == "error":
                    self.stats.record_error()
                    self._log("Cycle ended with error, retrying...")
                    self._sleep(2)
                    continue
                else:
                    self._log(f"Cycle ended with result: {result}")
        except StopIteration:
            self._log("Automation stopped by user")
        except Exception as e:
            self._log(f"Error: {e}", "error")
            self._save_error_screenshot("unexpected")
            logger.exception("Automation error")
        finally:
            if self.input:
                self.input.close()
            if self.recognizer:
                self.recognizer.close()
            # Save stats on finish
            try:
                self.stats.save_to_file("stats.txt")
                self.stats.append_to_file("stats_log.txt")
                self._log("Statistics saved to stats.txt and stats_log.txt")
            except Exception as e:
                self._log(f"Failed to save stats: {e}", "error")
            if self.state != self.STATE_SUCCESS:
                self.state = self.STATE_STOPPED
            self._log("Automation finished")

    def _run_single_cycle(self):
        """Run one complete character creation + testing cycle.
        Returns: 'success', 'delete_and_retry', or 'error'.
        """
        # Step 1: Double-click empty slot and verify character creation screen
        self.current_step = 1
        self._log("Step 1: Finding empty slot...")
        result = self._run_step_with_retry(
            lambda: self._step_find_and_click(
                "empty_slot", "empty_slot", double=True, timeout=15,
                verify_image_key="knight_icon", verify_region_key="knight_icon",
                verify_timeout=3,
            ),
            "find_empty_slot")
        if result is None:
            return "error"

        # Step 2: Click knight icon
        self.current_step = 2
        self._log("Step 2: Clicking knight icon...")
        result = self._run_step_with_retry(
            lambda: self._step_find_and_click("knight_icon", "knight_icon", timeout=10),
            "find_knight_icon")
        if result is None:
            return "error"
        self._sleep(1)

        # Step 3: Verify knight image, retry click if needed
        self.current_step = 3
        self._log("Step 3: Verifying knight selection...")
        for attempt in range(5):
            self._check_stop()
            self._refresh_window()
            verify_pos = self._abs_pos(self.config["click_positions"]["knight_verify_click"])
            self._click(verify_pos["x"], verify_pos["y"])
            self._sleep(0.5)
            template = self.config["images"].get("knight_verify", "")
            region = self._abs_roi(self.config["roi"]["knight_verify"])
            if template:
                found, _, _, _ = self.recognizer.find_template_in_region(
                    template, region,
                    threshold=self._get_image_threshold("knight_verify"),
                )
                if found:
                    self._log("Knight verified!")
                    break
            else:
                break  # No verification image, just proceed
        self._sleep(0.5)

        # Step 4: Click stat position 4 times
        self.current_step = 4
        self._log("Step 4: Clicking stat position 4 times...")
        self._check_stop()
        self._refresh_window()
        stat_pos = self._abs_pos(self.config["click_positions"]["stat_click"])
        for i in range(4):
            self._click(stat_pos["x"], stat_pos["y"])
            self._sleep(0.3)
        self._sleep(0.5)

        # Step 5: Click name input, type character name
        self.current_step = 5
        self._log("Step 5: Entering character name...")
        self._check_stop()
        self._refresh_window()
        name_pos = self._abs_pos(self.config["click_positions"]["name_input_click"])
        self._click(name_pos["x"], name_pos["y"])
        self._sleep(0.3)
        char_name = self.config.get("character_name", "Knight001")
        self.input.type_text(char_name)
        self._sleep(0.5)

        # Step 6: Click confirm to create character
        self.current_step = 6
        self._log("Step 6: Confirming character creation...")
        result = self._run_step_with_retry(
            lambda: self._step_find_and_click("confirm_button", "confirm_button", timeout=5),
            "find_confirm_button")
        if result is None:
            return "error"
        self._sleep(2)

        # Step 7: Double-click character to enter game
        self.current_step = 7
        self._log("Step 7: Entering game...")
        self._check_stop()
        self._refresh_window()
        char_pos = self._abs_pos(self.config["click_positions"]["character_slot_click"])
        self._sleep(1)
        self._double_click(char_pos["x"], char_pos["y"])
        wait_time = self.config.get("wait_after_enter_game", 5)
        self._sleep(wait_time)

        # Step 8: Press tab, double-click item
        self.current_step = 8
        self._log("Step 8: Opening inventory, clicking item...")
        self._check_stop()
        self.input.press_key("tab")
        self._sleep(1)
        result = self._run_step_with_retry(
            lambda: self._step_find_and_click("item_icon", "item_slot", double=True, timeout=10),
            "find_item_icon")
        if result is None:
            return "error"
        self._sleep(1)

        # Step 9: Click text in popup
        self.current_step = 9
        self._log("Step 9: Clicking popup text...")
        result = self._run_step_with_retry(
            lambda: self._step_find_and_click("popup_text", "popup_text", timeout=10),
            "find_popup_text")
        if result is None:
            return "error"
        self._sleep(1)

        # Step 10: Wait, click point, then find & click scarecrow
        self.current_step = 10
        self._log("Step 10: Starting scarecrow clicking...")
        self._check_stop()
        scarecrow_delay = self.config.get("wait_before_scarecrow", 3)
        self._sleep(scarecrow_delay)

        # Click initial point after entering
        self._refresh_window()
        after_pos = self._abs_pos(self.config["click_positions"]["after_enter_click"])
        self._click(after_pos["x"], after_pos["y"])
        self._sleep(1)

        # Step 11: Scarecrow click loop with level/MP checking
        self.current_step = 11
        result = self._scarecrow_loop()
        return result

    def _step_find_and_click(self, image_key, region_key, double=False, timeout=10,
                             verify_image_key=None, verify_region_key=None,
                             verify_timeout=3):
        """Helper for step retry: find template and click.
        If verify_image_key is given, checks that the verify template appears
        after clicking.  Returns (True, x, y) or (False, 0, 0).
        """
        found, x, y, conf = self._wait_and_find(image_key, region_key, timeout=timeout)
        if found:
            action = "double-click" if double else "click"
            raw_roi = self.config["roi"].get(region_key)
            abs_region = self._abs_roi(raw_roi)
            self._log(
                f"Found '{image_key}' -> {action} at ({x}, {y}) "
                f"conf={conf:.3f} "
                f"[win_offset=({self._win_offset_x}, {self._win_offset_y}) "
                f"dpi_ratio={self._roi_dpi_ratio:.3f} "
                f"raw_roi={raw_roi} abs_roi={abs_region}]"
            )
            if double:
                self._double_click(x, y)
            else:
                self._click(x, y)
            # Post-click verification
            if verify_image_key and verify_region_key:
                self._sleep(1)
                v_found, _, _, _ = self._wait_and_find(
                    verify_image_key, verify_region_key, timeout=verify_timeout
                )
                if not v_found:
                    self._log(
                        f"Post-click verification failed: '{verify_image_key}' "
                        f"not found after clicking '{image_key}'",
                        "warning",
                    )
                    return (False, 0, 0)
                self._log(f"Post-click verification OK: '{verify_image_key}' found")
            return (True, x, y)
        return (False, 0, 0)

    def _capture_progress_snapshot(self, level_region, exp_region):
        """Capture current level and EXP display image for change detection.
        Returns (level_number_or_None, exp_image_bytes).
        """
        level = self.recognizer.ocr_number(level_region)
        exp_img = None
        if exp_region and exp_region.get("w", 0) > 5:
            exp_img = self.recognizer.capture_screen(exp_region).tobytes()
        return level, exp_img

    def _check_death(self, death_template, revival_template, hp_region, use_color=True):
        """Check if character has died (HP=0) and attempt recovery.
        Returns True if death was detected and recovery attempted.
        """
        death_detected = False

        # Method 1: Check for death screen image
        if death_template:
            screen = self._capture_target_screen()
            found, _, _, _ = self.recognizer.find_template(
                screen, death_template,
                threshold=self._get_image_threshold("death_screen"),
            )
            if found:
                death_detected = True

        # Method 2: HP bar color detection (fast and reliable)
        if not death_detected and use_color and hp_region and hp_region.get("w", 0) > 5:
            hp_info = self.recognizer.check_hp_bar(hp_region)
            if hp_info["is_dead"]:
                death_detected = True
                self._log(f"HP bar empty (ratio={hp_info['hp_ratio']:.3f})", "warning")

        # Method 3: Check HP display via OCR (HP = 0) as fallback
        if not death_detected and not use_color and hp_region and hp_region.get("w", 0) > 5:
            hp_val = self.recognizer.ocr_number(hp_region)
            if hp_val is not None and hp_val == 0:
                death_detected = True

        if not death_detected:
            return False

        self._log("DEATH DETECTED! HP=0. Starting recovery...", "warning")

        # Step 1: Click revival button / death screen image
        # Always refresh window to get fresh coordinates before clicking.
        self._refresh_window()
        if revival_template:
            found, rx, ry = self._wait_and_find_by_path(revival_template, timeout=10)
            if found:
                self._click(rx, ry)
                self._log("Clicked revival button")
            else:
                self._log("Revival button not found, clicking death screen...", "warning")
                if death_template:
                    self._refresh_window()
                    rect = get_window_rect(self._target_window_id) if self._target_window_id else None
                    screen = self._capture_target_screen()
                    found, dx, dy, _ = self.recognizer.find_template(
                        screen, death_template,
                        threshold=self._get_image_threshold("death_screen"),
                    )
                    if found and rect:
                        self._click(dx + rect["x"], dy + rect["y"])
        elif death_template:
            self._refresh_window()
            rect = get_window_rect(self._target_window_id) if self._target_window_id else None
            screen = self._capture_target_screen()
            found, dx, dy, _ = self.recognizer.find_template(
                screen, death_template,
                threshold=self._get_image_threshold("death_screen"),
            )
            if found and rect:
                self._click(dx + rect["x"], dy + rect["y"])
                self._log("Clicked death screen image")

        self._sleep(2)

        # Step 2: Press tab to open inventory
        self.input.press_key("tab")
        self._sleep(1)

        # Step 3: Double-click item (same as step 7)
        found, ix, iy, _ = self._wait_and_find("item_icon", "item_slot", timeout=10)
        if found:
            self._double_click(ix, iy)
            self._sleep(1)
            self._log("Used recovery item after death")
        else:
            self._log("Item not found during death recovery!", "warning")

        # Step 4: Click popup text (same as step 8)
        found, px, py, _ = self._wait_and_find("popup_text", "popup_text", timeout=10)
        if found:
            self._click(px, py)
            self._sleep(1)

        self._log("Death recovery complete. Resuming scarecrow clicking...")
        return True

    def _capture_target_screen(self, region=None):
        """Capture screen within target window (or full screen if no target).

        If region is given, captures that absolute-coordinate region.
        Otherwise captures the full target window area.
        Returns numpy BGR image.
        """
        if region:
            return self.recognizer.capture_screen(region)
        # Capture the whole target window area
        if self._target_window_id:
            rect = get_window_rect(self._target_window_id)
            if rect:
                return self.recognizer.capture_screen(rect)
        return self.recognizer.capture_screen()

    def _wait_and_find_by_path(self, template_path, timeout=10, interval=0.5):
        """Wait for a template image (by path) to appear on target window/screen.
        Returns (found, x, y).
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            self._check_stop()
            self._wait_pause()
            self._refresh_window()
            screen = self._capture_target_screen()
            found, x, y, _ = self.recognizer.find_template(screen, template_path)
            if found:
                # x, y are relative to the captured image; add window offset
                return True, x + self._win_offset_x, y + self._win_offset_y
            time.sleep(interval)
        return False, 0, 0

    def _generate_radial_positions(self, center_x, center_y, distance, count=8):
        """Generate positions in 8 directions around a center point."""
        positions = []
        for i in range(count):
            angle = (2 * math.pi * i) / count
            x = int(center_x + distance * math.cos(angle))
            y = int(center_y + distance * math.sin(angle))
            positions.append({"x": x, "y": y})
        return positions

    def _scarecrow_loop(self):
        """Click scarecrow repeatedly and check level/MP.
        Returns 'success' or 'delete_and_retry'.
        """
        current_level = 1
        level5_detect_streak = 0
        pending_final_decision = None  # "success" | "delete"
        pending_decision_streak = 0
        click_delay = self.config.get("scarecrow_click_delay", 0.5)
        strict_threshold = float(self.config.get("strict_template_threshold", 0.9))
        strict_threshold = min(0.99, max(0.5, strict_threshold))

        # Death recovery settings
        death_cfg = self.config.get("death_recovery", {})
        death_enabled = death_cfg.get("enabled", True)
        hp_check_interval = death_cfg.get("hp_check_interval", 2)
        death_template = self.config["images"].get("death_screen", "")
        revival_template = self.config["images"].get("revival_button", "")
        hp_bar_cfg = self.config.get("hp_bar_detection", {})
        hp_use_color = hp_bar_cfg.get("enabled", True) and hp_bar_cfg.get("method", "color") == "color"
        last_death_check = time.time()

        # Target lock settings
        target_cfg = self.config.get("target_lock", {})
        target_lock_enabled = target_cfg.get("enabled", True)
        target_tolerance = target_cfg.get("position_tolerance", 30)
        last_target_pos = None  # (x, y) of last clicked scarecrow

        # Character center for distance-based sorting (window-relative)
        char_center = self.config.get("character_center")

        # Build scarecrow template list (multi-direction)
        scarecrow_templates = list(self.config.get("scarecrow_templates", []))
        legacy = self.config["images"].get("scarecrow", "")
        if legacy and legacy not in scarecrow_templates:
            scarecrow_templates.insert(0, legacy)

        # HSV color filter settings
        hsv_cfg = self.config.get("scarecrow_hsv", {})
        hsv_range = hsv_cfg if hsv_cfg.get("enabled") else None

        origin = self._abs_pos(char_center) if char_center and char_center.get("x", 0) > 0 else None
        features = []
        if scarecrow_templates:
            features.append(f"{len(scarecrow_templates)} templates")
        if hsv_range:
            features.append("HSV filter")
        if origin:
            features.append("distance sort")
        if target_lock_enabled:
            features.append("target lock")
        if death_enabled:
            features.append("death recovery")
        if features:
            self._log(f"Scarecrow detection: {' + '.join(features)}")
        else:
            self._log("Error: No scarecrow templates or HSV filter configured! "
                       "Cannot proceed with scarecrow loop.", "error")
            self._save_error_screenshot("no_scarecrow_config")
            return "error"

        # Stuck detection settings
        stuck_cfg = self.config.get("stuck_detection", {})
        stuck_enabled = stuck_cfg.get("enabled", True)
        stuck_timeout = stuck_cfg.get("timeout", 10)
        unstuck_clicks = stuck_cfg.get("unstuck_clicks", [])
        use_radial = stuck_cfg.get("use_radial_movement", False)
        radial_distance = stuck_cfg.get("radial_distance", 100)
        unstuck_idx = 0  # Rotate through unstuck click positions

        # Generate radial positions if enabled and character center is set
        if use_radial and origin:
            radial_positions = self._generate_radial_positions(
                origin["x"], origin["y"], radial_distance)
            self._log(f"Radial unstuck: 8 directions, distance={radial_distance}px")
        else:
            radial_positions = None

        # Track progress for stuck detection
        last_progress_time = time.time()
        self._refresh_window()
        level_region = self._abs_roi(self.config["roi"]["level_display"])
        exp_region_cfg = self.config["roi"].get("exp_display") or self.config.get("exp_display")
        exp_region = self._abs_roi(exp_region_cfg) if exp_region_cfg else None
        last_level, last_exp_img = self._capture_progress_snapshot(level_region, exp_region)

        while not self._stop_event.is_set():
            self._check_stop()
            self._wait_pause()

            # Refresh window position each loop iteration
            self._refresh_window()
            scarecrow_region = self._abs_roi(self.config["roi"]["scarecrow_search"])
            level_region = self._abs_roi(self.config["roi"]["level_display"])
            mp_region = self._abs_roi(self.config["roi"]["mp_display"])
            exp_region = self._abs_roi(exp_region_cfg) if exp_region_cfg else None
            hp_region_cfg = self.config["roi"].get("hp_display")
            hp_region = self._abs_roi(hp_region_cfg) if hp_region_cfg else None
            origin = self._abs_pos(char_center) if char_center and char_center.get("x", 0) > 0 else None

            # --- Death check ---
            if death_enabled and (death_template or (hp_region and hp_region.get("w", 0) > 5)):
                now = time.time()
                if now - last_death_check >= hp_check_interval:
                    last_death_check = now
                    if self._check_death(death_template, revival_template, hp_region,
                                         use_color=hp_use_color):
                        self.stats.record_death()
                        last_progress_time = time.time()
                        last_target_pos = None
                        continue

            # --- Stuck detection: check if progress stalled ---
            if stuck_enabled:
                elapsed = time.time() - last_progress_time
                if elapsed >= stuck_timeout:
                    # Determine unstuck positions (convert to absolute)
                    if radial_positions:
                        positions_to_use = radial_positions
                    elif unstuck_clicks:
                        positions_to_use = [self._abs_pos(p) for p in unstuck_clicks]
                    else:
                        positions_to_use = None

                    if positions_to_use:
                        self.stats.record_stuck()
                        self._log(f"Stuck detected! No progress for {stuck_timeout}s. "
                                  f"Clicking unstuck position #{unstuck_idx + 1}...", "warning")
                        pos = positions_to_use[unstuck_idx % len(positions_to_use)]
                        self._click(pos["x"], pos["y"])
                        unstuck_idx += 1
                        self._sleep(1)
                        last_progress_time = time.time()
                        last_target_pos = None  # Reset target lock after unstuck
                        last_level, last_exp_img = self._capture_progress_snapshot(
                            level_region, exp_region)
                        continue

            # --- Find and click scarecrow ---
            scarecrow_clicked = False

            # Target lock: try clicking last known target first
            if target_lock_enabled and last_target_pos and (scarecrow_templates or hsv_range):
                found, sx, sy, conf, idx = self.recognizer.find_scarecrow(
                    scarecrow_region, scarecrow_templates, hsv_range,
                    origin={"x": last_target_pos[0], "y": last_target_pos[1]},
                )
                if found:
                    dist = abs(sx - last_target_pos[0]) + abs(sy - last_target_pos[1])
                    if dist <= target_tolerance:
                        self._click(sx, sy)
                        last_target_pos = (sx, sy)
                    else:
                        self._click(sx, sy)
                        last_target_pos = (sx, sy)
                        self._log("Target moved, switched to nearest scarecrow", "debug")
                    scarecrow_clicked = True
                else:
                    last_target_pos = None
                    self._log("Target lost, searching for new scarecrow...", "debug")

            # No target lock hit — search for closest scarecrow
            if not scarecrow_clicked and (scarecrow_templates or hsv_range):
                found, sx, sy, conf, idx = self.recognizer.find_scarecrow(
                    scarecrow_region, scarecrow_templates, hsv_range,
                    origin=origin,
                )
                if found:
                    self._click(sx, sy)
                    last_target_pos = (sx, sy) if target_lock_enabled else None
                    scarecrow_clicked = True
                    if idx >= 0:
                        self._log(f"Scarecrow clicked (template #{idx+1}, conf={conf:.2f})",
                                  "debug")
                    else:
                        self._log("Scarecrow clicked (HSV fallback)", "debug")
                else:
                    self._log("Scarecrow not found, retrying...", "warning")
                    self._sleep(1)
                    continue

            if scarecrow_clicked:
                self._sleep(click_delay)

            # --- Check for progress (level or EXP change) ---
            cur_level, cur_exp_img = self._capture_progress_snapshot(
                level_region, exp_region)
            progress_detected = False

            if cur_level is not None and last_level is not None:
                if cur_level > last_level:
                    progress_detected = True
            if cur_exp_img is not None and last_exp_img is not None:
                if cur_exp_img != last_exp_img:
                    progress_detected = True

            if progress_detected:
                last_progress_time = time.time()
                last_level = cur_level
                last_exp_img = cur_exp_img

            # OCR level tracking
            if cur_level is not None and cur_level > current_level:
                current_level = cur_level
                self._log(f"Level up detected! Current level: {current_level}")
                self.stats.record_level_up(current_level, self.iteration_count)

            # Fallback: if OCR is unstable, detect level 5 by template in level ROI.
            if current_level < 5:
                level5_template = self.config["images"].get("level_5", "")
                if level5_template and os.path.exists(level5_template):
                    level5_threshold = self._get_image_threshold("level_5", strict_threshold)
                    found_l5, _, _, conf_l5 = self.recognizer.find_template_in_region(
                        level5_template, level_region, threshold=level5_threshold
                    )
                    if found_l5:
                        level5_detect_streak += 1
                        self._log(
                            f"Level 5 template matched "
                            f"(conf={conf_l5:.3f}, streak={level5_detect_streak}/2)",
                            "debug",
                        )
                        if level5_detect_streak >= 2:
                            current_level = 5
                            self._log("Level 5 reached (template confirmation x2).")
                    else:
                        level5_detect_streak = 0
                else:
                    level5_detect_streak = 0

            # MP is tested only when level 5 is confirmed.
            if current_level < 5:
                pending_final_decision = None
                pending_decision_streak = 0
                continue

            required_mp = 9
            actual_mp = self._ocr_number_retry(mp_region)
            final_decision = None
            low_mp_value = None

            if actual_mp is None:
                self._log(f"Level {current_level}: MP OCR failed! "
                          "Retrying after short delay...", "warning")
                self._sleep(0.5)
                actual_mp = self._ocr_number_retry(mp_region)

            if actual_mp is not None:
                self._log(f"Level {current_level}: MP OCR={actual_mp} (need {required_mp})")
                if actual_mp >= required_mp:
                    final_decision = "success"
                else:
                    final_decision = "delete"
                    low_mp_value = actual_mp
            else:
                # OCR failed twice: match mp_2~mp_8 templates with strict threshold.
                matched_low = None
                best_conf = 0.0
                for mp_val in range(2, 9):
                    key = f"mp_{mp_val}"
                    path = self.config["images"].get(key, "")
                    if not path or not os.path.exists(path):
                        continue
                    mp_threshold = self._get_image_threshold(key, strict_threshold)
                    found_mp, _, _, conf_mp = self.recognizer.find_template_in_region(
                        path, mp_region, threshold=mp_threshold
                    )
                    best_conf = max(best_conf, conf_mp)
                    if found_mp:
                        matched_low = mp_val
                        break

                if matched_low is not None:
                    final_decision = "delete"
                    low_mp_value = matched_low
                    used_thresh = self._get_image_threshold(
                        f"mp_{matched_low}", strict_threshold
                    )
                    self._log(
                        f"MP template matched: mp_{matched_low} "
                        f"(threshold={used_thresh:.2f}).",
                        "warning",
                    )
                else:
                    final_decision = "success"
                    self._log(
                        f"MP OCR failed twice and no mp_2~mp_8 matched "
                        f"(best_conf={best_conf:.3f}). Treating as MP>=9.",
                        "warning",
                    )

            # Confirm identical decision for 2 consecutive frames.
            if final_decision == pending_final_decision:
                pending_decision_streak += 1
            else:
                pending_final_decision = final_decision
                pending_decision_streak = 1

            if pending_decision_streak < 2:
                self._log(
                    f"Decision pending: {final_decision} "
                    f"({pending_decision_streak}/2). Rechecking...",
                    "debug",
                )
                self._sleep(0.3)
                continue

            if final_decision == "success":
                pass_mp = actual_mp if actual_mp is not None else 9
                self.stats.record_mp_pass(current_level, pass_mp, self.iteration_count)
                return "success"

            fail_mp = low_mp_value if low_mp_value is not None else (actual_mp or 0)
            self._log(
                f"Level {current_level} MP={fail_mp} < {required_mp}. Deleting character."
            )
            self.stats.record_mp_fail(current_level, fail_mp, required_mp,
                                      self.iteration_count)
            self._exit_and_delete()
            return "delete_and_retry"

        return "stopped"

    def _exit_and_delete(self):
        """Steps 12-14: Exit game, delete character."""
        # Step 12: Ctrl+Q to exit
        self.current_step = 12
        self._log("Step 12: Exiting game (Ctrl+Q)...")
        self.input.hotkey("ctrl", "q")
        self._sleep(1)

        # Click exit confirm
        self._refresh_window()
        exit_pos = self._abs_pos(self.config["click_positions"]["exit_confirm_click"])
        found, x, y, _ = self._wait_and_find("exit_button", "exit_button", timeout=5)
        if found:
            self._click(x, y)
        else:
            self._click(exit_pos["x"], exit_pos["y"])
        self._sleep(3)

        # Step 13: Select character and delete
        self.current_step = 13
        self._log("Step 13: Deleting character...")
        self._refresh_window()
        char_pos = self._abs_pos(self.config["click_positions"]["character_slot_click"])
        self._click(char_pos["x"], char_pos["y"])
        self._sleep(0.5)

        self._refresh_window()
        delete_pos = self._abs_pos(self.config["click_positions"]["delete_click"])
        self._click(delete_pos["x"], delete_pos["y"])
        self._sleep(1)

        # Step 14: Wait for delete popup to appear and disappear
        self.current_step = 14
        self._log("Step 14: Waiting for delete confirmation...")
        delete_wait = self.config.get("delete_wait_time", 10)

        # Wait for popup to appear
        delete_template = self.config["images"].get("delete_popup", "")
        delete_region = self._abs_roi(self.config["roi"]["delete_popup"])
        delete_threshold = self._get_image_threshold("delete_popup")
        if delete_template:
            # Wait for popup to appear
            popup_appeared = False
            for _ in range(int(delete_wait * 2)):
                self._check_stop()
                self._wait_pause()
                found, _, _, _ = self.recognizer.find_template_in_region(
                    delete_template, delete_region, threshold=delete_threshold
                )
                if found:
                    popup_appeared = True
                    break
                self._sleep(0.5)

            if popup_appeared:
                # Wait for popup to disappear
                for _ in range(int(delete_wait * 4)):
                    self._check_stop()
                    self._wait_pause()
                    found, _, _, _ = self.recognizer.find_template_in_region(
                        delete_template, delete_region, threshold=delete_threshold
                    )
                    if not found:
                        self._log("Delete complete!")
                        break
                    self._sleep(0.5)
        else:
            # No delete popup image, just wait
            self._sleep(delete_wait)

        self._sleep(1)
        self._log("Ready for next iteration")
