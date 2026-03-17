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
        "name_input": {"x": 0, "y": 0, "w": 100, "h": 100},
        "confirm_button": {"x": 0, "y": 0, "w": 100, "h": 100},
        "character_slot": {"x": 0, "y": 0, "w": 100, "h": 100},
        "tab_area": {"x": 0, "y": 0, "w": 100, "h": 100},
        "item_slot": {"x": 0, "y": 0, "w": 100, "h": 100},
        "popup_text": {"x": 0, "y": 0, "w": 100, "h": 100},
        "scarecrow_search": {"x": 0, "y": 0, "w": 400, "h": 400},
        "level_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "mp_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "exit_button": {"x": 0, "y": 0, "w": 100, "h": 100},
        "delete_button": {"x": 0, "y": 0, "w": 100, "h": 100},
        "delete_popup": {"x": 0, "y": 0, "w": 200, "h": 100},
        "click_after_enter": {"x": 0, "y": 0, "w": 10, "h": 10},
        "hp_display": {"x": 0, "y": 0, "w": 80, "h": 30},
        "exp_display": {"x": 0, "y": 0, "w": 100, "h": 20},
    },
    "click_positions": {
        "knight_verify_click": {"x": 0, "y": 0},
        "name_input_click": {"x": 0, "y": 0},
        "character_slot_click": {"x": 0, "y": 0},
        "tab_click": {"x": 0, "y": 0},
        "after_enter_click": {"x": 0, "y": 0},
        "exit_confirm_click": {"x": 0, "y": 0},
        "delete_click": {"x": 0, "y": 0},
    },
    "images": {
        "empty_slot": "",
        "knight_icon": "",
        "knight_verify": "",
        "confirm_button": "",
        "item_icon": "",
        "popup_text": "",
        "scarecrow": "",
        "exit_button": "",
        "delete_popup": "",
        "death_screen": "",
        "revival_button": "",
    },
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
    },
    "ocr_retry_count": 3,
    "error_screenshot_dir": "error_screenshots",
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
