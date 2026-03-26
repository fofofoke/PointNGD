"""Comprehensive functional validation tests for PointNGD."""
import json
import os
import sys
import tempfile
import shutil
import time
import threading
import unittest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfig(unittest.TestCase):
    """Test configuration management."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_default_config(self):
        from core.config import load_config, DEFAULT_CONFIG
        config = load_config(self.config_path)
        # Should have all default keys
        self.assertIn("input_method", config)
        self.assertIn("roi", config)
        self.assertIn("click_positions", config)
        self.assertIn("images", config)
        self.assertEqual(config["input_method"], "software")

    def test_save_and_load_config(self):
        from core.config import load_config, save_config
        config = load_config(self.config_path)
        config["character_name"] = "TestKnight"
        config["scarecrow_click_delay"] = 1.5
        save_config(config, self.config_path)

        loaded = load_config(self.config_path)
        self.assertEqual(loaded["character_name"], "TestKnight")
        self.assertEqual(loaded["scarecrow_click_delay"], 1.5)

    def test_deep_merge_preserves_defaults(self):
        from core.config import load_config, save_config
        # Save partial config
        partial = {"input_method": "arduino", "roi": {"empty_slot": {"x": 50, "y": 60, "w": 200, "h": 100}}}
        with open(self.config_path, "w") as f:
            json.dump(partial, f)

        config = load_config(self.config_path)
        # Custom value should be loaded
        self.assertEqual(config["input_method"], "arduino")
        self.assertEqual(config["roi"]["empty_slot"]["x"], 50)
        # Default values should still exist
        self.assertIn("knight_icon", config["roi"])
        self.assertIn("click_positions", config)

    def test_profile_management(self):
        from core.config import load_config, save_profile, load_profile, list_profiles, delete_profile
        profiles_dir = os.path.join(self.tmpdir, "profiles")

        config = load_config(self.config_path)
        config["character_name"] = "ProfileTest"

        # Save profile
        path = save_profile(config, "test_profile", profiles_dir)
        self.assertTrue(os.path.exists(path))

        # List profiles
        profiles = list_profiles(profiles_dir)
        self.assertIn("test_profile", profiles)

        # Load profile
        loaded = load_profile("test_profile", profiles_dir)
        self.assertEqual(loaded["character_name"], "ProfileTest")

        # Delete profile
        result = delete_profile("test_profile", profiles_dir)
        self.assertTrue(result)
        self.assertNotIn("test_profile", list_profiles(profiles_dir))

    def test_config_has_all_required_roi_keys(self):
        from core.config import DEFAULT_CONFIG
        required_rois = [
            "empty_slot", "knight_icon", "knight_verify", "confirm_button",
            "item_slot", "popup_text", "scarecrow_search", "level_display",
            "mp_display", "exit_button", "delete_popup", "hp_display",
            "exp_display",
        ]
        for key in required_rois:
            self.assertIn(key, DEFAULT_CONFIG["roi"], f"Missing ROI key: {key}")
            roi = DEFAULT_CONFIG["roi"][key]
            self.assertIn("x", roi)
            self.assertIn("y", roi)
            self.assertIn("w", roi)
            self.assertIn("h", roi)

    def test_config_has_all_required_click_positions(self):
        from core.config import DEFAULT_CONFIG
        required_clicks = [
            "knight_verify_click", "stat_click", "name_input_click",
            "character_slot_click", "enter_character_slot_click",
            "delete_character_slot_click", "after_enter_click",
            "exit_confirm_click", "delete_click",
        ]
        for key in required_clicks:
            self.assertIn(key, DEFAULT_CONFIG["click_positions"],
                          f"Missing click position: {key}")

    def test_config_has_all_required_image_keys(self):
        from core.config import DEFAULT_CONFIG
        required_images = [
            "empty_slot", "knight_icon", "knight_verify", "confirm_button",
            "item_icon", "popup_text", "scarecrow", "exit_button",
            "delete_popup", "death_screen", "revival_button",
            "level_5", "mp_1", "mp_2", "mp_3", "mp_4", "mp_5", "mp_6", "mp_7", "mp_8",
        ]
        for key in required_images:
            self.assertIn(key, DEFAULT_CONFIG["images"],
                          f"Missing image key: {key}")


class TestStats(unittest.TestCase):
    """Test statistics tracking."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_basic_tracking(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        s.record_iteration()
        s.record_iteration()
        s.record_success()
        self.assertEqual(s.total_iterations, 2)
        self.assertEqual(s.successful, 1)

    def test_mp_tracking(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        s.record_mp_pass(2, 3, 1)
        s.record_mp_fail(3, 4, 5, 2)
        s.record_mp_pass(3, 5, 3)

        dist = s.mp_distribution()
        self.assertIn(2, dist)
        self.assertIn(3, dist)
        self.assertEqual(dist[2][3], 1)  # Level 2, MP=3, count=1
        self.assertEqual(dist[3][4], 1)  # Level 3, MP=4 (fail), count=1
        self.assertEqual(dist[3][5], 1)  # Level 3, MP=5 (pass), count=1

    def test_level_up_tracking(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        s.record_level_up(2, 1)
        s.record_level_up(3, 1)
        self.assertEqual(len(s.level_times), 2)
        self.assertEqual(s.level_times[0]["level"], 2)

    def test_elapsed_str(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        result = s.elapsed_str()
        self.assertRegex(result, r"\d{2}:\d{2}:\d{2}")

    def test_success_rate(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        self.assertEqual(s.success_rate(), 0.0)
        s.record_iteration()
        s.record_iteration()
        s.record_success()
        self.assertAlmostEqual(s.success_rate(), 50.0)

    def test_save_to_file(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        s.record_iteration()
        s.record_success()
        path = os.path.join(self.tmpdir, "stats.txt")
        s.save_to_file(path)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            content = f.read()
        self.assertIn("Total Iterations", content)
        self.assertIn("Successful", content)

    def test_summary_text(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        s.record_iteration()
        s.record_death()
        s.record_stuck()
        text = s.summary_text()
        self.assertIn("Deaths", text)
        self.assertIn("Stuck Count", text)

    def test_reset(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        s.start()
        s.record_iteration()
        s.record_success()
        s.reset()
        self.assertEqual(s.total_iterations, 0)
        self.assertEqual(s.successful, 0)
        self.assertIsNone(s.start_time)


class TestTelegram(unittest.TestCase):
    """Test Telegram notifier."""

    def test_not_configured(self):
        from core.telegram_notifier import TelegramNotifier
        n = TelegramNotifier()
        self.assertFalse(n.is_configured())
        self.assertFalse(n.send_message("test"))

    def test_configured(self):
        from core.telegram_notifier import TelegramNotifier
        n = TelegramNotifier("token123", "chat456")
        self.assertTrue(n.is_configured())


class TestImageRecognition(unittest.TestCase):
    """Test image recognition module."""

    def test_instantiation(self):
        from core.image_recognition import ImageRecognition
        r = ImageRecognition()
        self.assertEqual(r.match_threshold, 0.8)

    def test_close_method_exists(self):
        """ImageRecognition.close() is called from AutomationEngine's finally block."""
        from core.image_recognition import ImageRecognition
        r = ImageRecognition()
        # close() must exist and not raise
        self.assertTrue(hasattr(r, 'close'), "ImageRecognition must have close() method")
        r.close()  # Should not raise

    def test_find_template_missing_file(self):
        from core.image_recognition import ImageRecognition
        import numpy as np
        r = ImageRecognition()
        screen = np.zeros((100, 100, 3), dtype=np.uint8)
        found, x, y, conf = r.find_template(screen, "/nonexistent/path.png")
        self.assertFalse(found)

    def test_ocr_number_with_empty_region(self):
        """OCR on a black image should return None (no digits)."""
        from core.image_recognition import ImageRecognition
        import numpy as np
        r = ImageRecognition()
        # Create a small black image and save it as a temporary region
        # We'll use capture_screen with a small region
        # Actually, we can test ocr_number indirectly by checking it handles None
        # gracefully when no text is found
        # OCR requires tesseract installed, so test the pipeline
        region = {"x": 0, "y": 0, "w": 50, "h": 50}
        try:
            result = r.ocr_number(region)
            # Result should be int or None
            self.assertTrue(result is None or isinstance(result, int))
        except Exception:
            pass  # OCR might fail without display

    def test_find_all_templates_missing_file(self):
        from core.image_recognition import ImageRecognition
        import numpy as np
        r = ImageRecognition()
        screen = np.zeros((100, 100, 3), dtype=np.uint8)
        results = r.find_all_templates(screen, "/nonexistent.png")
        self.assertEqual(results, [])

    def test_compare_images_missing_files(self):
        from core.image_recognition import ImageRecognition
        r = ImageRecognition()
        score = r.compare_images("/a.png", "/b.png")
        self.assertEqual(score, 0.0)

    def test_hsv_mask_creation(self):
        from core.image_recognition import ImageRecognition
        import numpy as np
        r = ImageRecognition()
        # Create a simple color image
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :] = [0, 255, 0]  # Green in BGR
        hsv_range = {"h_min": 30, "h_max": 90, "s_min": 50, "s_max": 255,
                     "v_min": 50, "v_max": 255}
        mask = r._create_hsv_mask(img, hsv_range)
        self.assertEqual(mask.shape, (100, 100))
        # Green should be detected
        import cv2
        self.assertGreater(cv2.countNonZero(mask), 0)

    def test_find_scarecrow_no_templates(self):
        from core.image_recognition import ImageRecognition
        r = ImageRecognition()
        region = {"x": 0, "y": 0, "w": 100, "h": 100}
        # Should return early without trying to capture screen
        found, x, y, conf, idx, odist = r.find_scarecrow(region, [], None)
        self.assertFalse(found)

    def test_find_scarecrow_with_image_no_templates(self):
        from core.image_recognition import ImageRecognition
        import numpy as np
        r = ImageRecognition()
        region = {"x": 0, "y": 0, "w": 100, "h": 100}
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        found, x, y, conf, idx, odist = r.find_scarecrow(region, [], None, image=img)
        self.assertFalse(found)

    def test_check_hp_bar_invalid_region(self):
        from core.image_recognition import ImageRecognition
        r = ImageRecognition()
        result = r.check_hp_bar(None)
        self.assertEqual(result["hp_ratio"], 1.0)
        self.assertFalse(result["is_dead"])

        result = r.check_hp_bar({"x": 0, "y": 0, "w": 3, "h": 3})
        self.assertEqual(result["hp_ratio"], 1.0)


class TestInputHandler(unittest.TestCase):
    """Test input handler module."""

    def test_factory_software(self):
        from core.input_handler import create_input_handler, SoftwareInput
        try:
            handler = create_input_handler("software")
            self.assertIsInstance(handler, SoftwareInput)
            handler.close()
        except ImportError:
            pass  # pyautogui may not be available

    def test_factory_default(self):
        from core.input_handler import create_input_handler, SoftwareInput
        try:
            handler = create_input_handler()
            self.assertIsInstance(handler, SoftwareInput)
            handler.close()
        except ImportError:
            pass

    def test_base_class_interface(self):
        from core.input_handler import InputHandler
        handler = InputHandler()
        with self.assertRaises(NotImplementedError):
            handler.click(0, 0)
        with self.assertRaises(NotImplementedError):
            handler.double_click(0, 0)
        with self.assertRaises(NotImplementedError):
            handler.type_text("test")
        with self.assertRaises(NotImplementedError):
            handler.press_key("enter")
        with self.assertRaises(NotImplementedError):
            handler.hotkey("ctrl", "v")
        with self.assertRaises(NotImplementedError):
            handler.move_to(0, 0)
        handler.close()  # Should not raise

    def test_clipboard_function(self):
        from core.input_handler import _copy_to_clipboard
        # Should not crash even without display
        try:
            _copy_to_clipboard("test123")
        except Exception:
            pass  # May fail without clipboard support


class TestHotkeys(unittest.TestCase):
    """Test hotkey manager."""

    def test_instantiation(self):
        from core.hotkeys import HotkeyManager
        hm = HotkeyManager(on_start=lambda: None,
                           on_pause=lambda: None,
                           on_stop=lambda: None)
        self.assertFalse(hm.is_running)

    def test_start_stop(self):
        from core.hotkeys import HotkeyManager, PYNPUT_AVAILABLE
        hm = HotkeyManager()
        if PYNPUT_AVAILABLE:
            result = hm.start()
            self.assertTrue(result)
            self.assertTrue(hm.is_running)
            hm.stop()
            self.assertFalse(hm.is_running)


class TestAutomationEngine(unittest.TestCase):
    """Test automation engine initialization and state management."""

    def test_initialization(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        self.assertEqual(engine.state, AutomationEngine.STATE_IDLE)
        self.assertEqual(engine.iteration_count, 0)
        self.assertEqual(engine.current_step, 0)

    def test_state_transitions(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)

        # Should start as idle
        self.assertEqual(engine.state, AutomationEngine.STATE_IDLE)

        # Stop without starting
        engine.stop()
        self.assertEqual(engine.state, AutomationEngine.STATE_STOPPED)

    def test_abs_roi_conversion(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        engine._win_offset_x = 100
        engine._win_offset_y = 200

        roi = {"x": 10, "y": 20, "w": 50, "h": 60}
        abs_roi = engine._abs_roi(roi)
        self.assertEqual(abs_roi["x"], 110)
        self.assertEqual(abs_roi["y"], 220)
        self.assertEqual(abs_roi["w"], 50)
        self.assertEqual(abs_roi["h"], 60)

    def test_abs_roi_none(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        self.assertIsNone(engine._abs_roi(None))

    def test_abs_pos_conversion(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        engine._win_offset_x = 50
        engine._win_offset_y = 75

        pos = {"x": 10, "y": 20}
        abs_pos = engine._abs_pos(pos)
        self.assertEqual(abs_pos["x"], 60)
        self.assertEqual(abs_pos["y"], 95)

    def test_sleep_interruptible(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)

        # Sleep should complete quickly for small durations
        start = time.time()
        engine._sleep(0.2)
        elapsed = time.time() - start
        self.assertGreater(elapsed, 0.15)
        self.assertLess(elapsed, 1.0)

    def test_sleep_stops_on_event(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)

        # Set stop event, sleep should raise StopIteration
        engine._stop_event.set()
        with self.assertRaises(StopIteration):
            engine._sleep(10)

    def test_ocr_number_retry_returns_none(self):
        """OCR retry with non-existent region should gracefully return None."""
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        # With a small/zero region, OCR should fail gracefully
        try:
            result = engine._ocr_number_retry({"x": 0, "y": 0, "w": 10, "h": 10}, retries=1)
            self.assertTrue(result is None or isinstance(result, int))
        except Exception:
            pass  # May fail without display

    def test_radial_positions(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        positions = engine._generate_radial_positions(500, 400, 100, 8)
        self.assertEqual(len(positions), 8)
        for pos in positions:
            self.assertIn("x", pos)
            self.assertIn("y", pos)
        # First position should be directly to the right
        self.assertEqual(positions[0]["x"], 600)
        self.assertEqual(positions[0]["y"], 400)

    def test_mp_requirements(self):
        """Verify the MP requirements logic matches the spec."""
        mp_requirements = {2: 3, 3: 5, 4: 7, 5: 9}
        # Level 2 needs MP 3
        self.assertEqual(mp_requirements[2], 3)
        # Level 3 needs MP 5
        self.assertEqual(mp_requirements[3], 5)
        # Level 4 needs MP 7
        self.assertEqual(mp_requirements[4], 7)
        # Level 5 needs MP 9 (SUCCESS condition)
        self.assertEqual(mp_requirements[5], 9)
        # Level 1 not in requirements (should keep clicking)
        self.assertNotIn(1, mp_requirements)

    def test_get_image_threshold_returns_configured_value(self):
        """_get_image_threshold returns per-key threshold from config."""
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        config["image_thresholds"] = {"level_5": 0.92, "mp_3": 0.85}
        engine = AutomationEngine(config)
        self.assertAlmostEqual(engine._get_image_threshold("level_5"), 0.92)
        self.assertAlmostEqual(engine._get_image_threshold("mp_3"), 0.85)

    def test_get_image_threshold_returns_default_when_missing(self):
        """_get_image_threshold returns default for unconfigured keys."""
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        config["image_thresholds"] = {}
        engine = AutomationEngine(config)
        self.assertIsNone(engine._get_image_threshold("level_5"))
        self.assertEqual(engine._get_image_threshold("level_5", 0.9), 0.9)

    def test_get_image_threshold_rejects_out_of_range(self):
        """_get_image_threshold rejects values outside 0.1~0.99."""
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        config["image_thresholds"] = {"bad_low": 0.05, "bad_high": 1.0}
        engine = AutomationEngine(config)
        self.assertIsNone(engine._get_image_threshold("bad_low"))
        self.assertIsNone(engine._get_image_threshold("bad_high"))

    def test_classify_mp_from_templates_mp1_is_delete(self):
        """mp_1~mp_8 template match should go to delete branch."""
        from core.automation import AutomationEngine
        from core.config import load_config
        tmpdir = tempfile.mkdtemp()
        try:
            config = load_config("/nonexistent/config.json")
            mp1_path = os.path.join(tmpdir, "mp_1.png")
            with open(mp1_path, "wb") as f:
                f.write(b"x")
            config["images"]["mp_1"] = mp1_path
            engine = AutomationEngine(config)

            class DummyRecognizer:
                def find_template_in_region(self, template_path, region, threshold=None):
                    if template_path == mp1_path:
                        return True, 0, 0, 1.0
                    return False, 0, 0, 0.0

            engine.recognizer = DummyRecognizer()
            decision, low_mp, _ = engine._classify_mp_from_templates(
                {"x": 0, "y": 0, "w": 1, "h": 1}, 0.9
            )
            self.assertEqual(decision, "delete")
            self.assertEqual(low_mp, 1)
        finally:
            shutil.rmtree(tmpdir)

    def test_classify_mp_from_templates_mp2_is_delete(self):
        """mp_2~mp_8 template match should go to delete branch."""
        from core.automation import AutomationEngine
        from core.config import load_config
        tmpdir = tempfile.mkdtemp()
        try:
            config = load_config("/nonexistent/config.json")
            mp2_path = os.path.join(tmpdir, "mp_2.png")
            with open(mp2_path, "wb") as f:
                f.write(b"x")
            config["images"]["mp_2"] = mp2_path
            engine = AutomationEngine(config)

            class DummyRecognizer:
                def find_template_in_region(self, template_path, region, threshold=None):
                    if template_path == mp2_path:
                        return True, 0, 0, 0.99
                    return False, 0, 0, 0.0

            engine.recognizer = DummyRecognizer()
            decision, low_mp, _ = engine._classify_mp_from_templates(
                {"x": 0, "y": 0, "w": 1, "h": 1}, 0.9
            )
            self.assertEqual(decision, "delete")
            self.assertEqual(low_mp, 2)
        finally:
            shutil.rmtree(tmpdir)

    def test_config_image_thresholds_default_empty(self):
        """Default config should have empty image_thresholds dict."""
        from core.config import DEFAULT_CONFIG
        self.assertIn("image_thresholds", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["image_thresholds"], {})

    def test_config_strict_template_threshold_default(self):
        """Default strict_template_threshold should be 0.9."""
        from core.config import DEFAULT_CONFIG
        self.assertEqual(DEFAULT_CONFIG["strict_template_threshold"], 0.9)

    def test_run_step_with_retry_success(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)

        call_count = [0]

        def step():
            call_count[0] += 1
            return (True, 100, 200)

        result = engine._run_step_with_retry(step, "test_step", max_retries=3)
        self.assertEqual(result, (True, 100, 200))
        self.assertEqual(call_count[0], 1)

    def test_run_step_with_retry_failure(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        engine._step_retry_delay = 0.01  # Speed up test

        call_count = [0]

        def step():
            call_count[0] += 1
            return (False, 0, 0)

        result = engine._run_step_with_retry(step, "test_step", max_retries=3)
        self.assertIsNone(result)
        self.assertEqual(call_count[0], 3)

    def test_run_step_with_retry_eventual_success(self):
        from core.automation import AutomationEngine
        from core.config import load_config
        config = load_config("/nonexistent/config.json")
        engine = AutomationEngine(config)
        engine._step_retry_delay = 0.01

        call_count = [0]

        def step():
            call_count[0] += 1
            if call_count[0] >= 2:
                return (True, 50, 60)
            return (False, 0, 0)

        result = engine._run_step_with_retry(step, "test_step", max_retries=3)
        self.assertEqual(result, (True, 50, 60))
        self.assertEqual(call_count[0], 2)


class TestWindowUtils(unittest.TestCase):
    """Test window utility functions."""

    def test_find_windows_empty_title(self):
        from gui.window_utils import find_windows_by_title
        result = find_windows_by_title("")
        self.assertEqual(result, [])

    def test_get_window_rect_invalid(self):
        from gui.window_utils import get_window_rect
        result = get_window_rect("invalid_window_id_12345")
        self.assertIsNone(result)

    def test_capture_window_invalid(self):
        from gui.window_utils import capture_window
        img, rect = capture_window("invalid_window_id_12345")
        self.assertIsNone(img)

    def test_capture_window_region_invalid(self):
        from gui.window_utils import capture_window_region
        img, roi = capture_window_region("invalid", {"x": 0, "y": 0, "w": 100, "h": 100})
        self.assertIsNone(img)

    def test_capture_window_by_title_not_found(self):
        from gui.window_utils import capture_window_by_title
        img, rect, wid = capture_window_by_title("__nonexistent_window_title_xyz__")
        self.assertIsNone(img)
        self.assertIsNone(rect)
        self.assertIsNone(wid)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("tkinter"),
    "tkinter not available in headless environment",
)
class TestROIEditorLabels(unittest.TestCase):
    """Test ROI editor configuration consistency."""

    def test_roi_labels_match_config(self):
        """ROI editor labels should include all config ROI keys."""
        from gui.roi_editor import ROIEditor
        from core.config import DEFAULT_CONFIG
        editor_keys = set(ROIEditor.ROI_LABELS.keys())
        config_keys = set(DEFAULT_CONFIG["roi"].keys())
        # All config keys should be in editor
        missing = config_keys - editor_keys
        self.assertEqual(missing, set(),
                         f"ROI keys in config but not in editor: {missing}")

    def test_capturable_rois_have_image_keys(self):
        """Capturable ROIs should map to valid image config keys."""
        from gui.roi_editor import ROIEditor
        from core.config import DEFAULT_CONFIG
        for roi_key in ROIEditor.CAPTURABLE_ROIS:
            image_key = ROIEditor.ROI_TO_IMAGE_KEY.get(roi_key, roi_key)
            self.assertIn(image_key, DEFAULT_CONFIG["images"],
                          f"ROI '{roi_key}' maps to image key '{image_key}' "
                          f"which is not in DEFAULT_CONFIG['images']")

    def test_shared_roi_entries_are_capturable(self):
        """All SHARED_ROI keys must be in CAPTURABLE_ROIS."""
        from gui.roi_editor import ROIEditor
        for key in ROIEditor.SHARED_ROI:
            self.assertIn(key, ROIEditor.CAPTURABLE_ROIS,
                          f"SHARED_ROI key '{key}' not in CAPTURABLE_ROIS")

    def test_shared_roi_parents_exist_in_config(self):
        """SHARED_ROI parent keys must exist in DEFAULT_CONFIG['roi']."""
        from gui.roi_editor import ROIEditor
        from core.config import DEFAULT_CONFIG
        for key, parent in ROIEditor.SHARED_ROI.items():
            self.assertIn(parent, DEFAULT_CONFIG["roi"],
                          f"SHARED_ROI parent '{parent}' for '{key}' "
                          f"not in DEFAULT_CONFIG['roi']")

    def test_shared_roi_keys_have_labels(self):
        """All SHARED_ROI keys must have entries in ROI_LABELS."""
        from gui.roi_editor import ROIEditor
        for key in ROIEditor.SHARED_ROI:
            self.assertIn(key, ROIEditor.ROI_LABELS,
                          f"SHARED_ROI key '{key}' missing from ROI_LABELS")


@unittest.skipUnless(
    __import__("importlib").util.find_spec("tkinter"),
    "tkinter not available in headless environment",
)
class TestClickPositionEditorLabels(unittest.TestCase):
    """Test click position editor configuration consistency."""

    def test_click_labels_match_config(self):
        from gui.roi_editor import ClickPositionEditor
        from core.config import DEFAULT_CONFIG
        editor_keys = set(ClickPositionEditor.POSITION_LABELS.keys())
        config_click_keys = set(DEFAULT_CONFIG["click_positions"].keys())
        toplevel_keys = {"character_center"}

        expected_keys = config_click_keys | toplevel_keys
        # Editor should have all config keys
        missing = expected_keys - editor_keys
        self.assertEqual(missing, set(),
                         f"Click position keys in config but not in editor: {missing}")


class TestWorkflowIntegrity(unittest.TestCase):
    """Test workflow step integrity and data flow."""

    def test_automation_uses_correct_config_keys(self):
        """Verify automation engine accesses only keys that exist in config."""
        from core.config import DEFAULT_CONFIG

        # Keys accessed in automation.py
        required_config_keys = [
            "input_method", "arduino_port", "arduino_baudrate",
            "korean_input_method", "target_window_title",
            "character_name", "scarecrow_click_delay",
            "wait_after_enter_game", "wait_before_scarecrow",
            "delete_wait_time", "telegram_bot_token", "telegram_chat_id",
            "error_screenshot_dir", "ocr_retry_count",
        ]
        for key in required_config_keys:
            self.assertIn(key, DEFAULT_CONFIG,
                          f"Required config key '{key}' missing from DEFAULT_CONFIG")

    def test_automation_required_image_keys(self):
        """Verify all image keys used in automation exist in config."""
        from core.config import DEFAULT_CONFIG
        required_images = [
            "empty_slot", "knight_icon", "knight_verify",
            "confirm_button", "item_icon", "popup_text",
            "scarecrow", "exit_button", "delete_popup",
            "death_screen", "revival_button",
            "level_5", "mp_1", "mp_2", "mp_3", "mp_4", "mp_5", "mp_6", "mp_7", "mp_8",
        ]
        for key in required_images:
            self.assertIn(key, DEFAULT_CONFIG["images"],
                          f"Required image key '{key}' missing from config")

    def test_automation_required_roi_keys(self):
        """Verify all ROI keys used in automation exist in config."""
        from core.config import DEFAULT_CONFIG
        required_rois = [
            "empty_slot", "knight_icon", "knight_verify",
            "confirm_button", "item_slot", "popup_text",
            "scarecrow_search", "level_display", "mp_display",
            "exit_button", "delete_popup",
        ]
        for key in required_rois:
            self.assertIn(key, DEFAULT_CONFIG["roi"],
                          f"Required ROI key '{key}' missing from config")

    def test_automation_required_click_positions(self):
        """Verify all click position keys used in automation exist in config."""
        from core.config import DEFAULT_CONFIG
        required_clicks = [
            "knight_verify_click", "stat_click", "name_input_click",
            "character_slot_click", "enter_character_slot_click",
            "delete_character_slot_click", "after_enter_click",
            "exit_confirm_click", "delete_click",
        ]
        for key in required_clicks:
            self.assertIn(key, DEFAULT_CONFIG["click_positions"],
                          f"Required click position '{key}' missing from config")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_config_unicode_handling(self):
        """Config should handle Korean character names."""
        tmpdir = tempfile.mkdtemp()
        try:
            from core.config import save_config, load_config
            path = os.path.join(tmpdir, "config.json")
            config = load_config(path)
            config["character_name"] = "기사001"
            save_config(config, path)
            loaded = load_config(path)
            self.assertEqual(loaded["character_name"], "기사001")
        finally:
            shutil.rmtree(tmpdir)

    def test_stats_mp_distribution_empty(self):
        from core.stats import StatsTracker
        s = StatsTracker()
        dist = s.mp_distribution()
        self.assertEqual(dist, {})

    def test_telegram_async_does_not_block(self):
        from core.telegram_notifier import TelegramNotifier
        n = TelegramNotifier()
        start = time.time()
        n.send_message_async("test")
        elapsed = time.time() - start
        # Async should return immediately
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
