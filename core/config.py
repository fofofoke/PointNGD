"""Configuration manager for saving/loading all settings."""
import json
import os

DEFAULT_CONFIG = {
    "input_method": "software",  # "software" or "arduino"
    "arduino_port": "COM3",
    "arduino_baudrate": 9600,
    "target_window_title": "",  # partial window title to bind to
    "character_name": "Knight001",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "korean_input_method": "clipboard",  # "clipboard" or "sendinput"
    "scarecrow_click_delay": 0.5,
    "wait_after_enter_game": 5,
    "wait_before_scarecrow": 3,
    "delete_wait_time": 10,
    "roi": {
        "empty_slot": {"x": 0, "y": 0, "w": 100, "h": 100},
        "knight_icon": {"x": 0, "y": 0, "w": 100, "h": 100},
        "knight_verify": {"x": 0, "y": 0, "w": 100, "h": 100},
        "confirm_button": {"x": 0, "y": 0, "w": 100, "h": 100},
        "post_confirm_verify": {"x": 0, "y": 0, "w": 100, "h": 100},
        "item_slot": {"x": 0, "y": 0, "w": 100, "h": 100},
        "popup_text": {"x": 0, "y": 0, "w": 100, "h": 100},
        "scarecrow_search": {"x": 0, "y": 0, "w": 400, "h": 400},
        "level_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "mp_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "exit_button": {"x": 0, "y": 0, "w": 100, "h": 100},
        "delete_popup": {"x": 0, "y": 0, "w": 200, "h": 100},
        "hp_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "hp_check_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "hp_6": {"x": 0, "y": 0, "w": 40, "h": 30},
        "exp_display": {"x": 0, "y": 0, "w": 100, "h": 20},
        "game_entered": {"x": 0, "y": 0, "w": 200, "h": 200},
    },
    "click_positions": {
        "knight_verify_click": {"x": 0, "y": 0},
        "stat_click": {"x": 0, "y": 0},
        "name_input_click": {"x": 0, "y": 0},
        # Legacy shared slot key (kept for backward compatibility)
        "character_slot_click": {"x": 0, "y": 0},
        # Separate slot click points for workflow steps
        "enter_character_slot_click": {"x": 0, "y": 0},   # Step 7
        "delete_character_slot_click": {"x": 0, "y": 0},  # Step 13
        "after_enter_click": {"x": 0, "y": 0},
        "exit_confirm_click": {"x": 0, "y": 0},
        "delete_click": {"x": 0, "y": 0},
    },
    "images": {
        "empty_slot": "",
        "knight_icon": "",
        "knight_verify": "",
        "confirm_button": "",
        "post_confirm_verify": "",
        "item_icon": "",
        "popup_text": "",
        "scarecrow": "",
        "level_display": "",
        "mp_display": "",
        "level_5": "",
        "mp_1": "",
        "mp_2": "",
        "mp_3": "",
        "mp_4": "",
        "mp_5": "",
        "mp_6": "",
        "mp_7": "",
        "mp_8": "",
        "exit_button": "",
        "delete_popup": "",
        "death_screen": "",
        "revival_button": "",
        "game_entered": "",
        "hp_6": "",
    },
    "strict_template_threshold": 0.9,
    "image_thresholds": {},
    "stuck_detection": {
        "enabled": True,
        "timeout": 10,
        "unstuck_clicks": [{"x": 0, "y": 0}],
        "use_radial_movement": False,
        "radial_distance": 100,
    },
    "death_recovery": {
        "enabled": True,
        "hp_check_interval": 2,
    },
    "target_lock": {
        "enabled": True,
        "position_tolerance": 30,
    },
    "character_center": {"x": 0, "y": 0},
    "scarecrow_templates": [],
    "scarecrow_hsv": {
        "enabled": False,
        "h_min": 10, "s_min": 50, "v_min": 50,
        "h_max": 30, "s_max": 255, "v_max": 255,
    },
    "hp_bar_detection": {
        "enabled": True,
        "method": "color",  # "color" or "ocr"
    },
    "hp_stop_condition": {
        "priority": "image_first",  # "image_first" or "ocr_first"
        "hp_threshold": 70,         # stop if HP OCR >= this value
        "hp_digits": 2,             # expected digit count
        "hp_min": 55,               # valid HP range minimum
        "hp_max": 79,               # valid HP range maximum
    },
    "hotkeys": {
        "enabled": True,
    },
    "log_file": {
        "enabled": True,
        "path": "bot.log",
    },
    "step_retry": {
        "max_retries": 3,
        "retry_delay": 2,
        "step_timeout": 10,
        "recovery_wait": 3,
    },
    "error_alert": {
        "enabled": True,
        "consecutive_errors": 3,
    },
    "ocr_retry_count": 3,
    "error_screenshot_dir": "resources/screenshots",
    "template_dir": "resources/templates",
    "model_dir": "resources/models",
}

CONFIG_FILE = "config.json"


def load_config(path=None):
    """Load configuration from file, merging with defaults."""
    filepath = path or CONFIG_FILE
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            saved = json.load(f)
        _deep_merge(config, saved)
    return config


def save_config(config, path=None):
    """Save configuration to file."""
    filepath = path or CONFIG_FILE
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def list_profiles(profiles_dir="profiles"):
    """List available profile names."""
    if not os.path.isdir(profiles_dir):
        return []
    profiles = []
    for f in sorted(os.listdir(profiles_dir)):
        if f.endswith(".json"):
            profiles.append(f[:-5])
    return profiles


def save_profile(config, name, profiles_dir="profiles"):
    """Save config as a named profile."""
    os.makedirs(profiles_dir, exist_ok=True)
    path = os.path.join(profiles_dir, f"{name}.json")
    save_config(config, path)
    return path


def load_profile(name, profiles_dir="profiles"):
    """Load a named profile."""
    path = os.path.join(profiles_dir, f"{name}.json")
    return load_config(path)


def delete_profile(name, profiles_dir="profiles"):
    """Delete a named profile."""
    path = os.path.join(profiles_dir, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def _deep_merge(base, override):
    """Recursively merge override into base dict."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
