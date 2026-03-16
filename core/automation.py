"""Main automation workflow engine for Lineage Classic bot."""
import time
import logging
import threading

from core.image_recognition import ImageRecognition
from core.input_handler import create_input_handler
from core.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class AutomationEngine:
    """Executes the full Lineage Classic automation workflow.

    Workflow steps:
    1)  Character select screen: double-click empty slot
    2)  Character creation screen: click knight icon
    3)  Verify knight image at position, retry if wrong
    4)  Click name input position, type character name
    5)  Click confirm button to create character
    6)  Auto-return to select screen: double-click character slot to enter game
    7)  Press tab, double-click item icon
    8)  Left popup appears: click specific text in popup
    9)  After configurable delay, click point then find & click scarecrow repeatedly
    10) After each scarecrow click, check level-up (image/OCR). Check MP at each level:
        - Level 2, MP 3: continue scarecrow, then go to step 14
        - Level 3, MP 5: continue; else go to step 11
        - Level 4, MP 7: continue; else go to step 11
        - Level 5, MP 9: SUCCESS -> telegram notify & stop; else go to step 11
    11) Ctrl+Q, click exit confirm to return to character select
    12) Select character, click delete, wait for delete popup
    13) After delete popup disappears, go to step 1
    14) MP check at higher levels (handled in step 10 logic)
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

        self.recognizer = ImageRecognition()
        self.input = None
        self.telegram = TelegramNotifier(
            config.get("telegram_bot_token", ""),
            config.get("telegram_chat_id", ""),
        )
        self.iteration_count = 0
        self.current_step = 0

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
            time.sleep(min(0.1, end - time.time()))

    def _wait_and_find(self, image_key, region_key, timeout=10, interval=0.5):
        """Wait for a template image to appear in a region.
        Returns (found, abs_x, abs_y).
        """
        template_path = self.config["images"].get(image_key, "")
        region = self.config["roi"].get(region_key)
        if not template_path:
            self._log(f"Warning: No image set for '{image_key}'", "warning")
            return False, 0, 0

        end_time = time.time() + timeout
        while time.time() < end_time:
            self._check_stop()
            self._wait_pause()
            found, ax, ay, conf = self.recognizer.find_template_in_region(
                template_path, region
            )
            if found:
                return True, ax, ay
            time.sleep(interval)
        return False, 0, 0

    def start(self):
        """Start automation in a new thread."""
        if self.state == self.STATE_RUNNING:
            self._log("Already running")
            return
        self._stop_event.clear()
        self._pause_event.set()
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
        try:
            self._init_input()
            while not self._stop_event.is_set():
                self.iteration_count += 1
                self._log(f"=== Iteration {self.iteration_count} ===")
                result = self._run_single_cycle()
                if result == "success":
                    self.state = self.STATE_SUCCESS
                    self._log("SUCCESS! MP 9 at Level 5 found!")
                    self.telegram.send_message(
                        f"Lineage Bot: SUCCESS! Found MP 9 at Level 5. "
                        f"Iteration: {self.iteration_count}"
                    )
                    break
                elif result == "delete_and_retry":
                    self._log("Character doesn't meet criteria, deleting and retrying...")
                    continue
                else:
                    self._log(f"Cycle ended with result: {result}")
        except StopIteration:
            self._log("Automation stopped by user")
        except Exception as e:
            self._log(f"Error: {e}", "error")
            logger.exception("Automation error")
        finally:
            if self.input:
                self.input.close()
            if self.state != self.STATE_SUCCESS:
                self.state = self.STATE_STOPPED
            self._log("Automation finished")

    def _run_single_cycle(self):
        """Run one complete character creation + testing cycle.
        Returns: 'success', 'delete_and_retry', or 'error'.
        """
        # Step 1: Double-click empty slot
        self.current_step = 1
        self._log("Step 1: Finding empty slot...")
        self._check_stop()
        found, x, y = self._wait_and_find("empty_slot", "empty_slot", timeout=15)
        if not found:
            self._log("Empty slot not found!", "error")
            return "error"
        self.input.double_click(x, y)
        self._sleep(1)

        # Step 2: Click knight icon
        self.current_step = 2
        self._log("Step 2: Clicking knight icon...")
        self._check_stop()
        found, x, y = self._wait_and_find("knight_icon", "knight_icon", timeout=10)
        if not found:
            self._log("Knight icon not found!", "error")
            return "error"
        self.input.click(x, y)
        self._sleep(1)

        # Step 3: Verify knight image, retry click if needed
        self.current_step = 3
        self._log("Step 3: Verifying knight selection...")
        verify_pos = self.config["click_positions"]["knight_verify_click"]
        for attempt in range(5):
            self._check_stop()
            self.input.click(verify_pos["x"], verify_pos["y"])
            self._sleep(0.5)
            template = self.config["images"].get("knight_verify", "")
            region = self.config["roi"]["knight_verify"]
            if template:
                found, _, _, _ = self.recognizer.find_template_in_region(template, region)
                if found:
                    self._log("Knight verified!")
                    break
            else:
                break  # No verification image, just proceed
        self._sleep(0.5)

        # Step 4: Click name input, type character name
        self.current_step = 4
        self._log("Step 4: Entering character name...")
        self._check_stop()
        name_pos = self.config["click_positions"]["name_input_click"]
        self.input.click(name_pos["x"], name_pos["y"])
        self._sleep(0.3)
        char_name = self.config.get("character_name", "Knight001")
        self.input.type_text(char_name)
        self._sleep(0.5)

        # Step 5: Click confirm to create character
        self.current_step = 5
        self._log("Step 5: Confirming character creation...")
        self._check_stop()
        found, x, y = self._wait_and_find("confirm_button", "confirm_button", timeout=5)
        if not found:
            self._log("Confirm button not found!", "error")
            return "error"
        self.input.click(x, y)
        self._sleep(2)

        # Step 6: Double-click character to enter game
        self.current_step = 6
        self._log("Step 6: Entering game...")
        self._check_stop()
        char_pos = self.config["click_positions"]["character_slot_click"]
        self._sleep(1)
        self.input.double_click(char_pos["x"], char_pos["y"])
        wait_time = self.config.get("wait_after_enter_game", 5)
        self._sleep(wait_time)

        # Step 7: Press tab, double-click item
        self.current_step = 7
        self._log("Step 7: Opening inventory, clicking item...")
        self._check_stop()
        self.input.press_key("tab")
        self._sleep(1)
        found, x, y = self._wait_and_find("item_icon", "item_slot", timeout=10)
        if not found:
            self._log("Item icon not found!", "error")
            return "error"
        self.input.double_click(x, y)
        self._sleep(1)

        # Step 8: Click text in popup
        self.current_step = 8
        self._log("Step 8: Clicking popup text...")
        self._check_stop()
        found, x, y = self._wait_and_find("popup_text", "popup_text", timeout=10)
        if not found:
            self._log("Popup text not found!", "error")
            return "error"
        self.input.click(x, y)
        self._sleep(1)

        # Step 9: Wait, click point, then find & click scarecrow
        self.current_step = 9
        self._log("Step 9: Starting scarecrow clicking...")
        self._check_stop()
        scarecrow_delay = self.config.get("wait_before_scarecrow", 3)
        self._sleep(scarecrow_delay)

        # Click initial point after entering
        after_pos = self.config["click_positions"]["after_enter_click"]
        self.input.click(after_pos["x"], after_pos["y"])
        self._sleep(1)

        # Step 10: Scarecrow click loop with level/MP checking
        self.current_step = 10
        result = self._scarecrow_loop()
        return result

    def _capture_progress_snapshot(self, level_region, exp_region):
        """Capture current level and EXP display image for change detection.
        Returns (level_number_or_None, exp_image_bytes).
        """
        level = self.recognizer.ocr_number(level_region)
        exp_img = None
        if exp_region and exp_region.get("w", 0) > 5:
            exp_img = self.recognizer.capture_screen(exp_region).tobytes()
        return level, exp_img

    def _scarecrow_loop(self):
        """Click scarecrow repeatedly and check level/MP.
        Returns 'success' or 'delete_and_retry'.
        """
        current_level = 1
        click_delay = self.config.get("scarecrow_click_delay", 0.5)
        level_check_method = self.config.get("level_check_method", "both")
        level_up_template = self.config["images"].get("level_up_effect", "")
        scarecrow_region = self.config["roi"]["scarecrow_search"]
        level_region = self.config["roi"]["level_display"]
        mp_region = self.config["roi"]["mp_display"]
        exp_region = self.config.get("exp_display")

        # Character center for distance-based sorting
        char_center = self.config.get("character_center")
        origin = char_center if char_center and char_center.get("x", 0) > 0 else None

        # Build scarecrow template list (multi-direction)
        scarecrow_templates = list(self.config.get("scarecrow_templates", []))
        legacy = self.config["images"].get("scarecrow", "")
        if legacy and legacy not in scarecrow_templates:
            scarecrow_templates.insert(0, legacy)

        # HSV color filter settings
        hsv_cfg = self.config.get("scarecrow_hsv", {})
        hsv_range = hsv_cfg if hsv_cfg.get("enabled") else None

        if scarecrow_templates:
            self._log(f"Scarecrow detection: {len(scarecrow_templates)} templates"
                      f"{' + HSV filter' if hsv_range else ''}"
                      f"{' + distance sort' if origin else ''}")
        elif hsv_range:
            self._log("Scarecrow detection: HSV color filter only")
        else:
            self._log("Warning: No scarecrow templates or HSV filter configured!", "warning")

        # Stuck detection settings
        stuck_cfg = self.config.get("stuck_detection", {})
        stuck_enabled = stuck_cfg.get("enabled", True)
        stuck_timeout = stuck_cfg.get("timeout", 10)
        unstuck_clicks = stuck_cfg.get("unstuck_clicks", [])
        unstuck_idx = 0  # Rotate through unstuck click positions

        # Track progress for stuck detection
        last_progress_time = time.time()
        last_level, last_exp_img = self._capture_progress_snapshot(level_region, exp_region)

        # MP requirements per level
        mp_requirements = {2: 3, 3: 5, 4: 7, 5: 9}

        while not self._stop_event.is_set():
            self._check_stop()
            self._wait_pause()

            # --- Stuck detection: check if progress stalled ---
            if stuck_enabled and unstuck_clicks:
                elapsed = time.time() - last_progress_time
                if elapsed >= stuck_timeout:
                    self._log(f"Stuck detected! No progress for {stuck_timeout}s. "
                              "Clicking unstuck position...", "warning")
                    pos = unstuck_clicks[unstuck_idx % len(unstuck_clicks)]
                    self.input.click(pos["x"], pos["y"])
                    unstuck_idx += 1
                    self._sleep(1)
                    last_progress_time = time.time()
                    last_level, last_exp_img = self._capture_progress_snapshot(
                        level_region, exp_region)
                    continue

            # Find and click scarecrow (closest to character first)
            if scarecrow_templates or hsv_range:
                found, sx, sy, conf, idx = self.recognizer.find_scarecrow(
                    scarecrow_region, scarecrow_templates, hsv_range,
                    origin=origin,
                )
                if found:
                    self.input.click(sx, sy)
                    if idx >= 0:
                        self._log(f"Scarecrow clicked (template #{idx+1}, conf={conf:.2f})",
                                  "debug")
                    else:
                        self._log("Scarecrow clicked (HSV fallback)", "debug")
                else:
                    self._log("Scarecrow not found, retrying...", "warning")
                    self._sleep(1)
                    continue
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

            # Check for level up
            leveled_up = False

            if level_check_method in ("image", "both") and level_up_template:
                if self.recognizer.check_level_by_image(level_up_template):
                    leveled_up = True

            if level_check_method in ("ocr", "both"):
                if cur_level is not None and cur_level > current_level:
                    leveled_up = True
                    current_level = cur_level

            if leveled_up:
                # Re-read level via OCR for accuracy
                ocr_level = self.recognizer.ocr_number(level_region)
                if ocr_level is not None:
                    current_level = ocr_level
                else:
                    current_level += 1

                self._log(f"Level up detected! Current level: {current_level}")

                # Check MP
                required_mp = mp_requirements.get(current_level)
                if required_mp is None:
                    # Level not in requirements, keep clicking
                    continue

                actual_mp = self.recognizer.ocr_number(mp_region)
                self._log(f"Level {current_level}: MP = {actual_mp} (need {required_mp})")

                if current_level == 5:
                    if actual_mp == 9:
                        return "success"
                    else:
                        self._log(f"Level 5 but MP={actual_mp}, not 9. Deleting character.")
                        self._exit_and_delete()
                        return "delete_and_retry"

                if actual_mp != required_mp:
                    self._log(
                        f"Level {current_level} MP={actual_mp} != {required_mp}. "
                        "Deleting character."
                    )
                    self._exit_and_delete()
                    return "delete_and_retry"

                self._log(f"Level {current_level} MP={required_mp} OK, continuing...")
                # Continue scarecrow clicking

        return "stopped"

    def _exit_and_delete(self):
        """Steps 11-13: Exit game, delete character."""
        # Step 11: Ctrl+Q to exit
        self.current_step = 11
        self._log("Step 11: Exiting game (Ctrl+Q)...")
        self.input.hotkey("ctrl", "q")
        self._sleep(1)

        # Click exit confirm
        exit_pos = self.config["click_positions"]["exit_confirm_click"]
        found, x, y = self._wait_and_find("exit_button", "exit_button", timeout=5)
        if found:
            self.input.click(x, y)
        else:
            self.input.click(exit_pos["x"], exit_pos["y"])
        self._sleep(3)

        # Step 12: Select character and delete
        self.current_step = 12
        self._log("Step 12: Deleting character...")
        char_pos = self.config["click_positions"]["character_slot_click"]
        self.input.click(char_pos["x"], char_pos["y"])
        self._sleep(0.5)

        delete_pos = self.config["click_positions"]["delete_click"]
        self.input.click(delete_pos["x"], delete_pos["y"])
        self._sleep(1)

        # Step 13: Wait for delete popup to appear and disappear
        self.current_step = 13
        self._log("Step 13: Waiting for delete confirmation...")
        delete_wait = self.config.get("delete_wait_time", 10)

        # Wait for popup to appear
        delete_template = self.config["images"].get("delete_popup", "")
        delete_region = self.config["roi"]["delete_popup"]
        if delete_template:
            # Wait for popup to appear
            popup_appeared = False
            for _ in range(int(delete_wait * 2)):
                self._check_stop()
                found, _, _, _ = self.recognizer.find_template_in_region(
                    delete_template, delete_region
                )
                if found:
                    popup_appeared = True
                    break
                time.sleep(0.5)

            if popup_appeared:
                # Wait for popup to disappear
                for _ in range(int(delete_wait * 4)):
                    self._check_stop()
                    found, _, _, _ = self.recognizer.find_template_in_region(
                        delete_template, delete_region
                    )
                    if not found:
                        self._log("Delete complete!")
                        break
                    time.sleep(0.5)
        else:
            # No delete popup image, just wait
            self._sleep(delete_wait)

        self._sleep(1)
        self._log("Ready for next iteration")
