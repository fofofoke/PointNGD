"""Main GUI window for LC AB."""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
import threading
import logging
import os

from core.config import (load_config, save_config, list_profiles,
                          save_profile, load_profile, delete_profile)
from core.telegram_notifier import TelegramNotifier
from core.hotkeys import HotkeyManager
from core import updater


class MainWindow:
    """Main application window."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LC AB")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)

        self.config = load_config()
        self.engine = None
        self.hotkey_manager = None

        self._setup_logging()
        self._setup_file_logging()
        self._build_ui()
        self._load_settings_to_ui()
        self._init_hotkeys()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    def _setup_file_logging(self):
        """Set up logging to file."""
        log_cfg = self.config.get("log_file", {})
        if not log_cfg.get("enabled", True):
            return
        log_path = log_cfg.get("path", "bot.log")
        self._file_handler = logging.FileHandler(log_path, encoding="utf-8")
        self._file_handler.setLevel(logging.DEBUG)
        self._file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(self._file_handler)

    def _init_hotkeys(self):
        """Initialize global hotkeys."""
        if not self.config.get("hotkeys", {}).get("enabled", True):
            return
        self.hotkey_manager = HotkeyManager(
            on_start=lambda: self.root.after(0, self._hotkey_start_resume),
            on_pause=lambda: self.root.after(0, self._pause_automation),
            on_stop=lambda: self.root.after(0, self._stop_automation),
        )
        if self.hotkey_manager.start():
            logging.getLogger(__name__).info("Global hotkeys active: F9/F10/F11")

    def _hotkey_start_resume(self):
        """Handle F9: start if idle, resume if paused."""
        if self.engine and self.engine.state == "paused":
            self._resume_automation()
        elif not self.engine or self.engine.state in ("idle", "stopped", "success"):
            self._start_automation()

    def _build_ui(self):
        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Settings", command=self._save_settings)
        file_menu.add_command(label="Load Settings", command=self._load_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        profile_menu = tk.Menu(menubar, tearoff=0)
        profile_menu.add_command(label="Save as Profile...", command=self._save_as_profile)
        profile_menu.add_command(label="Load Profile...", command=self._load_profile)
        profile_menu.add_command(label="Delete Profile...", command=self._delete_profile)
        menubar.add_cascade(label="Profiles", menu=profile_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="ROI & Image Editor", command=self._open_roi_editor)
        tools_menu.add_command(label="Click Position Editor", command=self._open_click_editor)
        tools_menu.add_separator()
        tools_menu.add_command(label="Scarecrow Detection Editor", command=self._open_scarecrow_editor)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Check for Updates", command=self._check_for_updates)
        menubar.add_cascade(label="Help", menu=help_menu)

        # Notebook (tabs)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: General Settings
        settings_frame = ttk.Frame(notebook)
        notebook.add(settings_frame, text="Settings")
        self._build_settings_tab(settings_frame)

        # Tab 2: Control & Log
        control_frame = ttk.Frame(notebook)
        notebook.add(control_frame, text="Control")
        self._build_control_tab(control_frame)

        # Tab 3: Status
        status_frame = ttk.Frame(notebook)
        notebook.add(status_frame, text="Status")
        self._build_status_tab(status_frame)

        # Tab 4: Statistics
        stats_frame = ttk.Frame(notebook)
        notebook.add(stats_frame, text="Statistics")
        self._build_stats_tab(stats_frame)

        # Bottom status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_settings_tab(self, parent):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Input Method
        input_frame = ttk.LabelFrame(scroll_frame, text="Input Method")
        input_frame.pack(fill=tk.X, padx=10, pady=5)

        self.input_method_var = tk.StringVar(value="software")
        ttk.Radiobutton(
            input_frame, text="Software (pyautogui)", variable=self.input_method_var,
            value="software", command=self._toggle_arduino,
        ).pack(anchor=tk.W, padx=10, pady=2)
        ttk.Radiobutton(
            input_frame, text="Arduino Leonardo (HID)", variable=self.input_method_var,
            value="arduino", command=self._toggle_arduino,
        ).pack(anchor=tk.W, padx=10, pady=2)

        self.arduino_frame = ttk.Frame(input_frame)
        self.arduino_frame.pack(fill=tk.X, padx=20, pady=5)

        ttk.Label(self.arduino_frame, text="COM Port:").pack(side=tk.LEFT)
        self.arduino_port_var = tk.StringVar(value="COM3")
        ttk.Entry(self.arduino_frame, textvariable=self.arduino_port_var, width=10).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(self.arduino_frame, text="Baud:").pack(side=tk.LEFT, padx=(10, 0))
        self.arduino_baud_var = tk.StringVar(value="9600")
        ttk.Entry(self.arduino_frame, textvariable=self.arduino_baud_var, width=8).pack(
            side=tk.LEFT, padx=5
        )

        # Korean Input Method
        korean_frame = ttk.LabelFrame(scroll_frame, text="Korean Input Method")
        korean_frame.pack(fill=tk.X, padx=10, pady=5)

        self.korean_method_var = tk.StringVar(value="clipboard")
        ttk.Radiobutton(
            korean_frame, text="Clipboard Paste (Ctrl+V)",
            variable=self.korean_method_var, value="clipboard",
        ).pack(anchor=tk.W, padx=10, pady=2)
        ttk.Label(
            korean_frame,
            text="    Simple and fast. May not work if the game blocks Ctrl+V.",
            foreground="gray",
        ).pack(anchor=tk.W, padx=10)
        ttk.Radiobutton(
            korean_frame, text="Win32 SendInput (Recommended for games)",
            variable=self.korean_method_var, value="sendinput",
        ).pack(anchor=tk.W, padx=10, pady=2)
        ttk.Label(
            korean_frame,
            text="    OS-level keystroke simulation. Works with most games.\n"
            "    Windows only. Falls back to clipboard on other OS.",
            foreground="gray",
        ).pack(anchor=tk.W, padx=10)

        # Target Window
        win_frame = ttk.LabelFrame(scroll_frame, text="Target Window")
        win_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(win_frame,
                  text="Partial window title to bind to. All ROI/click positions "
                  "become relative to this window.").pack(
            anchor=tk.W, padx=10, pady=2)

        win_entry_row = ttk.Frame(win_frame)
        win_entry_row.pack(fill=tk.X, padx=10, pady=2)

        self.target_window_var = tk.StringVar(value="")
        ttk.Entry(win_entry_row, textvariable=self.target_window_var, width=30).pack(
            side=tk.LEFT, padx=(0, 5))
        ttk.Button(win_entry_row, text="Find Window",
                   command=self._find_target_window).pack(side=tk.LEFT, padx=2)
        ttk.Button(win_entry_row, text="Test Capture",
                   command=self._test_window_capture).pack(side=tk.LEFT, padx=2)

        self.window_status_var = tk.StringVar(value="")
        ttk.Label(win_frame, textvariable=self.window_status_var,
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        # Character Settings
        char_frame = ttk.LabelFrame(scroll_frame, text="Character Settings")
        char_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(char_frame, text="Character Name:").pack(anchor=tk.W, padx=10, pady=2)
        self.char_name_var = tk.StringVar(value="Knight001")
        ttk.Entry(char_frame, textvariable=self.char_name_var, width=30).pack(
            anchor=tk.W, padx=10, pady=2
        )

        # Timing Settings
        timing_frame = ttk.LabelFrame(scroll_frame, text="Timing (seconds)")
        timing_frame.pack(fill=tk.X, padx=10, pady=5)

        timings = [
            ("Scarecrow Click Delay:", "scarecrow_delay_var", "0.5"),
            ("Wait After Enter Game:", "enter_wait_var", "5"),
            ("Wait Before Scarecrow:", "scarecrow_wait_var", "3"),
            ("Delete Wait Time:", "delete_wait_var", "10"),
        ]
        for label, var_name, default in timings:
            row = ttk.Frame(timing_frame)
            row.pack(fill=tk.X, padx=10, pady=2)
            ttk.Label(row, text=label, width=25).pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            ttk.Entry(row, textvariable=var, width=8).pack(side=tk.LEFT, padx=5)

        # Stuck Detection
        stuck_frame = ttk.LabelFrame(scroll_frame, text="Stuck Detection (Path Blocked)")
        stuck_frame.pack(fill=tk.X, padx=10, pady=5)

        self.stuck_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(stuck_frame, text="Enable stuck detection",
                        variable=self.stuck_enabled_var).pack(anchor=tk.W, padx=10, pady=2)

        stuck_timeout_row = ttk.Frame(stuck_frame)
        stuck_timeout_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(stuck_timeout_row, text="Timeout (seconds):", width=25).pack(side=tk.LEFT)
        self.stuck_timeout_var = tk.StringVar(value="10")
        ttk.Entry(stuck_timeout_row, textvariable=self.stuck_timeout_var, width=8).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(stuck_frame,
                  text="Unstuck click positions (one per line, format: x,y):",
                  ).pack(anchor=tk.W, padx=10, pady=2)
        self.unstuck_text = tk.Text(stuck_frame, height=3, width=30, font=("Consolas", 10))
        self.unstuck_text.pack(fill=tk.X, padx=10, pady=2)
        self.radial_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(stuck_frame, text="Use radial movement (8 directions from character center)",
                        variable=self.radial_enabled_var).pack(anchor=tk.W, padx=10, pady=2)

        radial_dist_row = ttk.Frame(stuck_frame)
        radial_dist_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(radial_dist_row, text="Radial distance (px):", width=25).pack(side=tk.LEFT)
        self.radial_distance_var = tk.StringVar(value="100")
        ttk.Entry(radial_dist_row, textvariable=self.radial_distance_var, width=8).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(stuck_frame,
                  text="If no EXP/level change for timeout seconds, clicks these\n"
                  "positions in order to move the character, then retries scarecrow.\n"
                  "Radial mode auto-generates 8 direction positions around character center.",
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        # Death Recovery
        death_frame = ttk.LabelFrame(scroll_frame, text="Death Recovery (HP=0)")
        death_frame.pack(fill=tk.X, padx=10, pady=5)

        self.death_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(death_frame, text="Enable death detection & auto-recovery",
                        variable=self.death_enabled_var).pack(anchor=tk.W, padx=10, pady=2)

        death_interval_row = ttk.Frame(death_frame)
        death_interval_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(death_interval_row, text="HP check interval (sec):", width=25).pack(side=tk.LEFT)
        self.death_interval_var = tk.StringVar(value="2")
        ttk.Entry(death_interval_row, textvariable=self.death_interval_var, width=8).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(death_frame,
                  text="When HP=0 detected: click revival image → Tab → use item → resume.\n"
                  "Set 'Death Screen Image' and 'HP Display' ROI in their editors.",
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        # Target Lock
        target_frame = ttk.LabelFrame(scroll_frame, text="Target Lock")
        target_frame.pack(fill=tk.X, padx=10, pady=5)

        self.target_lock_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(target_frame, text="Keep attacking same scarecrow until it disappears",
                        variable=self.target_lock_var).pack(anchor=tk.W, padx=10, pady=2)

        target_tol_row = ttk.Frame(target_frame)
        target_tol_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(target_tol_row, text="Position tolerance (px):", width=25).pack(side=tk.LEFT)
        self.target_tolerance_var = tk.StringVar(value="30")
        ttk.Entry(target_tol_row, textvariable=self.target_tolerance_var, width=8).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(target_frame,
                  text="Prefers last-clicked scarecrow if still visible within tolerance.\n"
                  "Switches to nearest target only when current one disappears.",
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        # HP Bar Detection Method
        hp_frame = ttk.LabelFrame(scroll_frame, text="HP Bar Detection")
        hp_frame.pack(fill=tk.X, padx=10, pady=5)

        self.hp_bar_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(hp_frame, text="Enable HP bar color detection",
                        variable=self.hp_bar_enabled_var).pack(anchor=tk.W, padx=10, pady=2)

        self.hp_method_var = tk.StringVar(value="color")
        ttk.Radiobutton(hp_frame, text="Color detection (fast, recommended)",
                        variable=self.hp_method_var, value="color").pack(
            anchor=tk.W, padx=20, pady=1)
        ttk.Radiobutton(hp_frame, text="OCR number reading",
                        variable=self.hp_method_var, value="ocr").pack(
            anchor=tk.W, padx=20, pady=1)

        ttk.Label(hp_frame,
                  text="Color mode detects HP bar red pixels. More reliable than OCR.\n"
                  "Set the HP Display ROI in ROI Editor for the HP bar area.",
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        # Error Recovery
        retry_frame = ttk.LabelFrame(scroll_frame, text="Error Recovery")
        retry_frame.pack(fill=tk.X, padx=10, pady=5)

        retry_row = ttk.Frame(retry_frame)
        retry_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(retry_row, text="Step max retries:", width=25).pack(side=tk.LEFT)
        self.step_retry_var = tk.StringVar(value="3")
        ttk.Entry(retry_row, textvariable=self.step_retry_var, width=8).pack(
            side=tk.LEFT, padx=5)

        step_timeout_row = ttk.Frame(retry_frame)
        step_timeout_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(step_timeout_row, text="Step timeout (seconds):", width=25).pack(side=tk.LEFT)
        self.step_timeout_var = tk.StringVar(value="10")
        ttk.Entry(step_timeout_row, textvariable=self.step_timeout_var, width=8).pack(
            side=tk.LEFT, padx=5)

        recovery_wait_row = ttk.Frame(retry_frame)
        recovery_wait_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(recovery_wait_row, text="Recovery wait (seconds):", width=25).pack(side=tk.LEFT)
        self.recovery_wait_var = tk.StringVar(value="3")
        ttk.Entry(recovery_wait_row, textvariable=self.recovery_wait_var, width=8).pack(
            side=tk.LEFT, padx=5)

        ocr_row = ttk.Frame(retry_frame)
        ocr_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(ocr_row, text="OCR retry count:", width=25).pack(side=tk.LEFT)
        self.ocr_retry_var = tk.StringVar(value="3")
        ttk.Entry(ocr_row, textvariable=self.ocr_retry_var, width=8).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(retry_frame,
                  text="Retries failed steps before giving up. OCR retries improve\n"
                  "MP/level reading accuracy. Error screenshots auto-saved.",
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        threshold_row = ttk.Frame(retry_frame)
        threshold_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(threshold_row, text="Strict template threshold:", width=25).pack(side=tk.LEFT)
        self.strict_threshold_var = tk.StringVar(value="0.9")
        ttk.Entry(threshold_row, textvariable=self.strict_threshold_var, width=8).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(
            threshold_row, text="Image Thresholds...",
            command=self._open_image_threshold_editor,
        ).pack(side=tk.LEFT, padx=8)

        # Hotkeys
        hotkey_frame = ttk.LabelFrame(scroll_frame, text="Global Hotkeys")
        hotkey_frame.pack(fill=tk.X, padx=10, pady=5)

        self.hotkeys_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(hotkey_frame, text="Enable global hotkeys",
                        variable=self.hotkeys_enabled_var).pack(anchor=tk.W, padx=10, pady=2)
        ttk.Label(hotkey_frame,
                  text="F9 = Start / Resume    F10 = Pause    F11 = Stop\n"
                  "Works even when game window is focused.",
                  foreground="gray").pack(anchor=tk.W, padx=10, pady=2)

        # Log File
        logfile_frame = ttk.LabelFrame(scroll_frame, text="Log File")
        logfile_frame.pack(fill=tk.X, padx=10, pady=5)

        self.logfile_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(logfile_frame, text="Save logs to file",
                        variable=self.logfile_enabled_var).pack(anchor=tk.W, padx=10, pady=2)

        logpath_row = ttk.Frame(logfile_frame)
        logpath_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(logpath_row, text="Log file path:", width=25).pack(side=tk.LEFT)
        self.logfile_path_var = tk.StringVar(value="bot.log")
        ttk.Entry(logpath_row, textvariable=self.logfile_path_var, width=25).pack(
            side=tk.LEFT, padx=5)

        # Telegram Settings
        tg_frame = ttk.LabelFrame(scroll_frame, text="Telegram Notification")
        tg_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(tg_frame, text="Bot Token:").pack(anchor=tk.W, padx=10, pady=2)
        self.tg_token_var = tk.StringVar()
        ttk.Entry(tg_frame, textvariable=self.tg_token_var, width=50).pack(
            anchor=tk.W, padx=10, pady=2
        )

        ttk.Label(tg_frame, text="Chat ID:").pack(anchor=tk.W, padx=10, pady=2)
        self.tg_chat_var = tk.StringVar()
        ttk.Entry(tg_frame, textvariable=self.tg_chat_var, width=30).pack(
            anchor=tk.W, padx=10, pady=2
        )

        ttk.Button(tg_frame, text="Test Connection", command=self._test_telegram).pack(
            anchor=tk.W, padx=10, pady=5
        )

        tg_alert_row = ttk.Frame(tg_frame)
        tg_alert_row.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.error_alert_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            tg_alert_row,
            text="Alert on consecutive errors",
            variable=self.error_alert_enabled_var,
        ).pack(side=tk.LEFT)
        ttk.Label(tg_alert_row, text="Count:", width=7).pack(side=tk.LEFT, padx=(15, 2))
        self.error_alert_count_var = tk.StringVar(value="3")
        ttk.Entry(tg_alert_row, textvariable=self.error_alert_count_var, width=6).pack(side=tk.LEFT)

        # Quick access buttons
        quick_frame = ttk.LabelFrame(scroll_frame, text="Quick Setup")
        quick_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(quick_frame, text="Open ROI & Image Editor", command=self._open_roi_editor).pack(
            fill=tk.X, padx=10, pady=2
        )
        ttk.Button(
            quick_frame, text="Open Click Position Editor", command=self._open_click_editor
        ).pack(fill=tk.X, padx=10, pady=2)
        ttk.Button(quick_frame, text="Scarecrow Detection Editor",
                   command=self._open_scarecrow_editor).pack(fill=tk.X, padx=10, pady=2)

    def _build_control_tab(self, parent):
        # Control buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        self.start_btn = ttk.Button(btn_frame, text="START", command=self._start_automation)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = ttk.Button(
            btn_frame, text="PAUSE", command=self._pause_automation, state=tk.DISABLED
        )
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.resume_btn = ttk.Button(
            btn_frame, text="RESUME", command=self._resume_automation, state=tk.DISABLED
        )
        self.resume_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(
            btn_frame, text="STOP", command=self._stop_automation, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # Log area
        log_frame = ttk.LabelFrame(parent, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=20, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Button(log_frame, text="Clear Log", command=self._clear_log).pack(anchor=tk.E, padx=5, pady=2)

    def _build_status_tab(self, parent):
        info_frame = ttk.Frame(parent)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.status_labels = {}
        items = [
            ("State:", "state", "Idle"),
            ("Current Step:", "step", "-"),
            ("Iteration:", "iteration", "0"),
            ("Input Method:", "input", "-"),
        ]
        for i, (label, key, default) in enumerate(items):
            ttk.Label(info_frame, text=label, font=("", 11, "bold")).grid(
                row=i, column=0, sticky=tk.W, padx=10, pady=5
            )
            var = tk.StringVar(value=default)
            ttk.Label(info_frame, textvariable=var, font=("", 11)).grid(
                row=i, column=1, sticky=tk.W, padx=10, pady=5
            )
            self.status_labels[key] = var

        # Workflow description
        workflow_frame = ttk.LabelFrame(parent, text="Workflow Steps")
        workflow_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        steps = [
            "1. Double-click empty slot (character select)",
            "2. Click knight icon (class selection)",
            "3. Verify knight image, retry if wrong",
            "4. Click stat position 4 times",
            "5. Enter character name",
            "6. Click confirm to create character",
            "7. Double-click character to enter game",
            "8. Press Tab, double-click item",
            "9. Click text in popup",
            "10. Wait, then find & click scarecrow",
            "11. Check level/MP after scarecrow clicks",
            "12. Exit game (Ctrl+Q) if MP doesn't match",
            "13. Select & delete character",
            "14. Wait for delete, then restart",
            "14. Level 5 MP=9 -> SUCCESS + Telegram notify",
        ]
        for step in steps:
            ttk.Label(workflow_frame, text=step, font=("", 9)).pack(anchor=tk.W, padx=10, pady=1)

    def _build_stats_tab(self, parent):
        """Build statistics display tab."""
        # Stats info
        info_frame = ttk.LabelFrame(parent, text="Current Session")
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        self.stats_vars = {}
        stat_items = [
            ("Elapsed Time:", "elapsed", "00:00:00"),
            ("Total Iterations:", "total", "0"),
            ("Successful:", "success", "0"),
            ("Failed (MP):", "failed", "0"),
            ("Errors:", "errors", "0"),
            ("Deaths:", "deaths", "0"),
            ("Stuck Count:", "stuck", "0"),
            ("Success Rate:", "rate", "0.0%"),
        ]
        for i, (label, key, default) in enumerate(stat_items):
            ttk.Label(info_frame, text=label, font=("", 10, "bold")).grid(
                row=i, column=0, sticky=tk.W, padx=10, pady=2)
            var = tk.StringVar(value=default)
            ttk.Label(info_frame, textvariable=var, font=("", 10)).grid(
                row=i, column=1, sticky=tk.W, padx=10, pady=2)
            self.stats_vars[key] = var

        # MP distribution
        mp_frame = ttk.LabelFrame(parent, text="MP Distribution by Level")
        mp_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.stats_text = scrolledtext.ScrolledText(
            mp_frame, height=10, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(btn_frame, text="Refresh Stats",
                   command=self._refresh_stats).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Save Stats to File",
                   command=self._save_stats_to_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Export Stats Report",
                   command=self._export_stats).pack(side=tk.LEFT, padx=5)

    def _refresh_stats(self):
        """Update statistics display from engine."""
        if not self.engine or not hasattr(self.engine, 'stats'):
            return
        s = self.engine.stats
        self.stats_vars["elapsed"].set(s.elapsed_str())
        self.stats_vars["total"].set(str(s.total_iterations))
        self.stats_vars["success"].set(str(s.successful))
        self.stats_vars["failed"].set(str(s.failed_mp))
        self.stats_vars["errors"].set(str(s.errors))
        self.stats_vars["deaths"].set(str(s.deaths))
        self.stats_vars["stuck"].set(str(s.stuck_count))
        self.stats_vars["rate"].set(f"{s.success_rate():.1f}%")

        # Update MP distribution text
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        dist = s.mp_distribution()
        if dist:
            for lv in sorted(dist.keys()):
                mp_counts = dist[lv]
                parts = [f"MP={mp}: {count}회" for mp, count in sorted(mp_counts.items())]
                self.stats_text.insert(tk.END, f"Level {lv}: {', '.join(parts)}\n")
        else:
            self.stats_text.insert(tk.END, "No MP data yet.\n")

        # Recent level-ups
        if s.level_times:
            self.stats_text.insert(tk.END, "\n--- Recent Level-Ups ---\n")
            for entry in s.level_times[-10:]:
                t = int(entry["elapsed"])
                h, t = divmod(t, 3600)
                m, sec = divmod(t, 60)
                self.stats_text.insert(
                    tk.END,
                    f"  Iter #{entry['iteration']:>4d}  Lv{entry['level']}  "
                    f"at {h:02d}:{m:02d}:{sec:02d}\n"
                )
        self.stats_text.config(state=tk.DISABLED)

    def _save_stats_to_file(self):
        """Save current stats to text file."""
        if not self.engine or not hasattr(self.engine, 'stats'):
            messagebox.showinfo("Info", "No stats available. Start automation first.")
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt")],
            initialfile="stats.txt",
        )
        if filepath:
            self.engine.stats.save_to_file(filepath)
            messagebox.showinfo("Saved", f"Stats saved to {filepath}")

    def _export_stats(self):
        """Export stats report to a text file."""
        if not self.engine or not hasattr(self.engine, 'stats'):
            messagebox.showinfo("Info", "No stats available. Start automation first.")
            return
        report = self.engine.stats.summary_text()
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt")],
            initialfile=f"stats_report.txt",
        )
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)
            messagebox.showinfo("Exported", f"Stats report exported to {filepath}")

    def _save_as_profile(self):
        """Save current settings as a named profile."""
        self._apply_ui_to_config()
        name = simpledialog.askstring("Save Profile", "Enter profile name:")
        if name:
            name = name.strip()
            if not name:
                return
            path = save_profile(self.config, name)
            messagebox.showinfo("Saved", f"Profile '{name}' saved!")
            self.status_var.set(f"Profile '{name}' saved")

    def _load_profile(self):
        """Load a named profile."""
        profiles = list_profiles()
        if not profiles:
            messagebox.showinfo("Info", "No profiles saved yet.")
            return

        # Simple selection dialog
        win = tk.Toplevel(self.root)
        win.title("Load Profile")
        win.geometry("300x400")
        ttk.Label(win, text="Select a profile:", font=("", 11)).pack(pady=10)
        listbox = tk.Listbox(win, font=("", 10))
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        for p in profiles:
            listbox.insert(tk.END, p)

        def on_load():
            sel = listbox.curselection()
            if not sel:
                return
            name = profiles[sel[0]]
            self.config = load_profile(name)
            self._load_settings_to_ui()
            save_config(self.config)
            self.status_var.set(f"Profile '{name}' loaded")
            win.destroy()

        ttk.Button(win, text="Load", command=on_load).pack(pady=10)

    def _delete_profile(self):
        """Delete a named profile."""
        profiles = list_profiles()
        if not profiles:
            messagebox.showinfo("Info", "No profiles saved yet.")
            return

        win = tk.Toplevel(self.root)
        win.title("Delete Profile")
        win.geometry("300x400")
        ttk.Label(win, text="Select a profile to delete:", font=("", 11)).pack(pady=10)
        listbox = tk.Listbox(win, font=("", 10))
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        for p in profiles:
            listbox.insert(tk.END, p)

        def on_delete():
            sel = listbox.curselection()
            if not sel:
                return
            name = profiles[sel[0]]
            if messagebox.askyesno("Confirm", f"Delete profile '{name}'?"):
                delete_profile(name)
                listbox.delete(sel[0])
                self.status_var.set(f"Profile '{name}' deleted")

        ttk.Button(win, text="Delete", command=on_delete).pack(pady=10)

    def _exclude_own_windows(self, windows):
        """Filter out the bot's own windows from the search results."""
        own_title = self.root.title()
        exclude_prefixes = (own_title, "Window Capture Preview", "Select Target Window")
        return [(wid, wtitle) for wid, wtitle in windows
                if not wtitle.startswith(exclude_prefixes)]

    def _find_target_window(self):
        """Search for windows matching the title and display results."""
        from gui.window_utils import find_windows_by_title, get_window_rect
        title = self.target_window_var.get().strip()
        if not title:
            messagebox.showwarning("Warning", "Enter a window title substring first.")
            return
        windows = self._exclude_own_windows(find_windows_by_title(title))
        if not windows:
            self.window_status_var.set("No matching windows found.")
            return

        if len(windows) == 1:
            wid, wtitle = windows[0]
            rect = get_window_rect(wid)
            if rect:
                self.window_status_var.set(
                    f"Found: \"{wtitle}\" at ({rect['x']},{rect['y']}) "
                    f"{rect['w']}x{rect['h']}")
            else:
                self.window_status_var.set(f"Found: \"{wtitle}\" (could not get rect)")
        else:
            # Multiple matches - show selection dialog
            win = tk.Toplevel(self.root)
            win.title("Select Target Window")
            win.geometry("500x300")
            ttk.Label(win, text=f"Found {len(windows)} matching windows:",
                      font=("", 11)).pack(pady=10)
            listbox = tk.Listbox(win, font=("", 10))
            listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            for wid, wtitle in windows:
                listbox.insert(tk.END, wtitle)

            def on_select():
                sel = listbox.curselection()
                if not sel:
                    return
                wid, wtitle = windows[sel[0]]
                self.target_window_var.set(title)
                rect = get_window_rect(wid)
                if rect:
                    self.window_status_var.set(
                        f"Selected: \"{wtitle}\" at ({rect['x']},{rect['y']}) "
                        f"{rect['w']}x{rect['h']}")
                win.destroy()

            ttk.Button(win, text="Select", command=on_select).pack(pady=10)

    def _test_window_capture(self):
        """Capture the target window and show a preview."""
        from gui.window_utils import find_windows_by_title, capture_window
        title = self.target_window_var.get().strip()
        if not title:
            messagebox.showwarning("Warning", "Enter a window title first.")
            return
        windows = self._exclude_own_windows(find_windows_by_title(title))
        if not windows:
            messagebox.showerror("Error", f"No window matching \"{title}\" found.")
            return

        wid = windows[0][0]
        img, rect = capture_window(wid)
        if img is None:
            messagebox.showerror("Error", "Failed to capture window.")
            return

        # Show preview (reuse existing window if open)
        if hasattr(self, '_capture_preview') and self._capture_preview.winfo_exists():
            preview = self._capture_preview
            for w in preview.winfo_children():
                w.destroy()
        else:
            preview = tk.Toplevel(self.root)
            self._capture_preview = preview
        preview.title(f"Window Capture Preview ({rect['w']}x{rect['h']})")
        from PIL import Image as PILImage, ImageTk
        max_w, max_h = 800, 600
        scale = min(max_w / img.width, max_h / img.height, 1.0)
        disp = img.resize((int(img.width * scale), int(img.height * scale)), PILImage.LANCZOS)
        photo = ImageTk.PhotoImage(disp)
        canvas = tk.Canvas(preview, width=disp.width, height=disp.height)
        canvas.pack()
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        preview._photo = photo  # prevent GC

        self.window_status_var.set(
            f"Captured: \"{windows[0][1]}\" ({rect['w']}x{rect['h']})")

    def _toggle_arduino(self):
        pass  # Arduino frame is always visible

    @staticmethod
    def _safe_int(value, default):
        """Parse int from string, returning default on failure."""
        try:
            return int(value) if value else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_float(value, default):
        """Parse float from string, returning default on failure."""
        try:
            return float(value) if value else default
        except (ValueError, TypeError):
            return default

    def _apply_ui_to_config(self):
        """Apply UI values to config dict."""
        self.config["input_method"] = self.input_method_var.get()
        self.config["arduino_port"] = self.arduino_port_var.get()
        try:
            self.config["arduino_baudrate"] = int(self.arduino_baud_var.get())
        except ValueError:
            self.config["arduino_baudrate"] = 9600
        self.config["character_name"] = self.char_name_var.get()
        self.config["korean_input_method"] = self.korean_method_var.get()
        self.config["target_window_title"] = self.target_window_var.get().strip()

        # Stuck detection
        unstuck_clicks = []
        for line in self.unstuck_text.get("1.0", "end").strip().splitlines():
            line = line.strip()
            if "," in line:
                parts = line.split(",")
                try:
                    unstuck_clicks.append({"x": int(parts[0].strip()), "y": int(parts[1].strip())})
                except (ValueError, IndexError):
                    pass
        self.config["stuck_detection"] = {
            "enabled": self.stuck_enabled_var.get(),
            "timeout": self._safe_float(self.stuck_timeout_var.get(), 10),
            "unstuck_clicks": unstuck_clicks,
            "use_radial_movement": self.radial_enabled_var.get(),
            "radial_distance": self._safe_int(self.radial_distance_var.get(), 100),
        }

        self.config["death_recovery"] = {
            "enabled": self.death_enabled_var.get(),
            "hp_check_interval": self._safe_float(self.death_interval_var.get(), 2),
        }

        self.config["target_lock"] = {
            "enabled": self.target_lock_var.get(),
            "position_tolerance": self._safe_int(self.target_tolerance_var.get(), 30),
        }

        self.config["hp_bar_detection"] = {
            "enabled": self.hp_bar_enabled_var.get(),
            "method": self.hp_method_var.get(),
        }

        self.config["step_retry"] = {
            "max_retries": self._safe_int(self.step_retry_var.get(), 3),
            "retry_delay": 2,
            "step_timeout": self._safe_float(self.step_timeout_var.get(), 10),
            "recovery_wait": self._safe_float(self.recovery_wait_var.get(), 3),
        }
        self.config["ocr_retry_count"] = self._safe_int(self.ocr_retry_var.get(), 3)
        self.config["strict_template_threshold"] = self._safe_float(
            self.strict_threshold_var.get(), 0.9
        )

        self.config["hotkeys"] = {"enabled": self.hotkeys_enabled_var.get()}
        self.config["log_file"] = {
            "enabled": self.logfile_enabled_var.get(),
            "path": self.logfile_path_var.get() or "bot.log",
        }

        self.config["telegram_bot_token"] = self.tg_token_var.get()
        self.config["telegram_chat_id"] = self.tg_chat_var.get()
        self.config["error_alert"] = {
            "enabled": self.error_alert_enabled_var.get(),
            "consecutive_errors": self._safe_int(self.error_alert_count_var.get(), 3),
        }
        try:
            self.config["scarecrow_click_delay"] = float(self.scarecrow_delay_var.get())
        except ValueError:
            pass
        try:
            self.config["wait_after_enter_game"] = float(self.enter_wait_var.get())
        except ValueError:
            pass
        try:
            self.config["wait_before_scarecrow"] = float(self.scarecrow_wait_var.get())
        except ValueError:
            pass
        try:
            self.config["delete_wait_time"] = float(self.delete_wait_var.get())
        except ValueError:
            pass

    def _load_settings_to_ui(self):
        """Load config values into UI."""
        self.input_method_var.set(self.config.get("input_method", "software"))
        self.arduino_port_var.set(self.config.get("arduino_port", "COM3"))
        self.arduino_baud_var.set(str(self.config.get("arduino_baudrate", 9600)))
        self.char_name_var.set(self.config.get("character_name", "Knight001"))
        self.korean_method_var.set(self.config.get("korean_input_method", "clipboard"))
        self.target_window_var.set(self.config.get("target_window_title", ""))

        # Stuck detection
        stuck = self.config.get("stuck_detection", {})
        self.stuck_enabled_var.set(stuck.get("enabled", True))
        self.stuck_timeout_var.set(str(stuck.get("timeout", 10)))
        self.unstuck_text.delete("1.0", "end")
        for pos in stuck.get("unstuck_clicks", []):
            self.unstuck_text.insert("end", f"{pos['x']},{pos['y']}\n")

        # Radial movement
        self.radial_enabled_var.set(stuck.get("use_radial_movement", False))
        self.radial_distance_var.set(str(stuck.get("radial_distance", 100)))

        # Death recovery
        death = self.config.get("death_recovery", {})
        self.death_enabled_var.set(death.get("enabled", True))
        self.death_interval_var.set(str(death.get("hp_check_interval", 2)))

        # Target lock
        target = self.config.get("target_lock", {})
        self.target_lock_var.set(target.get("enabled", True))
        self.target_tolerance_var.set(str(target.get("position_tolerance", 30)))

        # HP bar detection
        hp_bar = self.config.get("hp_bar_detection", {})
        self.hp_bar_enabled_var.set(hp_bar.get("enabled", True))
        self.hp_method_var.set(hp_bar.get("method", "color"))

        # Error recovery
        step_retry = self.config.get("step_retry", {})
        self.step_retry_var.set(str(step_retry.get("max_retries", 3)))
        self.step_timeout_var.set(str(step_retry.get("step_timeout", 10)))
        self.recovery_wait_var.set(str(step_retry.get("recovery_wait", 3)))
        self.ocr_retry_var.set(str(self.config.get("ocr_retry_count", 3)))
        self.strict_threshold_var.set(str(self.config.get("strict_template_threshold", 0.9)))

        # Hotkeys
        self.hotkeys_enabled_var.set(self.config.get("hotkeys", {}).get("enabled", True))

        # Log file
        log_cfg = self.config.get("log_file", {})
        self.logfile_enabled_var.set(log_cfg.get("enabled", True))
        self.logfile_path_var.set(log_cfg.get("path", "bot.log"))

        self.tg_token_var.set(self.config.get("telegram_bot_token", ""))
        self.tg_chat_var.set(self.config.get("telegram_chat_id", ""))
        error_alert = self.config.get("error_alert", {})
        self.error_alert_enabled_var.set(error_alert.get("enabled", True))
        self.error_alert_count_var.set(str(error_alert.get("consecutive_errors", 3)))
        self.scarecrow_delay_var.set(str(self.config.get("scarecrow_click_delay", 0.5)))
        self.enter_wait_var.set(str(self.config.get("wait_after_enter_game", 5)))
        self.scarecrow_wait_var.set(str(self.config.get("wait_before_scarecrow", 3)))
        self.delete_wait_var.set(str(self.config.get("delete_wait_time", 10)))

    def _save_settings(self):
        self._apply_ui_to_config()
        save_config(self.config)
        self.status_var.set("Settings saved!")

    def _load_settings(self):
        self.config = load_config()
        self._load_settings_to_ui()
        self.status_var.set("Settings loaded!")

    def _open_roi_editor(self):
        from gui.roi_editor import ROIEditor
        def on_save(cfg):
            self.config.update(cfg)
            save_config(self.config)

        ROIEditor(self.root, self.config, images_dir="images", on_save=on_save)

    def _open_click_editor(self):
        from gui.roi_editor import ClickPositionEditor
        def on_save(cfg):
            self.config.update(cfg)
            save_config(self.config)

        ClickPositionEditor(self.root, self.config, on_save=on_save)

    def _open_scarecrow_editor(self):
        from gui.scarecrow_editor import ScarecrowEditor
        def on_save(cfg):
            self.config.update(cfg)
            save_config(self.config)

        ScarecrowEditor(self.root, self.config, images_dir="images", on_save=on_save)

    def _open_image_threshold_editor(self):
        """Open editor for per-image template match thresholds."""
        win = tk.Toplevel(self.root)
        win.title("Image Match Thresholds")
        win.geometry("420x600")
        win.transient(self.root)
        win.grab_set()

        ttk.Label(
            win,
            text="Set threshold per image key (0.10 ~ 0.99). Empty = default.",
            foreground="gray",
            wraplength=390,
        ).pack(anchor=tk.W, padx=10, pady=(10, 5))

        canvas = tk.Canvas(win)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=5)

        image_keys = sorted(self.config.get("images", {}).keys())
        threshold_cfg = self.config.setdefault("image_thresholds", {})
        vars_map = {}
        for key in image_keys:
            row = ttk.Frame(body)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=key, width=20).pack(side=tk.LEFT, padx=(0, 6))
            cur = threshold_cfg.get(key)
            var = tk.StringVar(value="" if cur is None else str(cur))
            vars_map[key] = var
            ttk.Entry(row, textvariable=var, width=10).pack(side=tk.LEFT)

        def on_save():
            new_cfg = {}
            errors = []
            for key, var in vars_map.items():
                raw = var.get().strip()
                if not raw:
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    errors.append(f"{key}: not a number")
                    continue
                if not (0.10 <= val <= 0.99):
                    errors.append(f"{key}: must be 0.10~0.99")
                    continue
                new_cfg[key] = round(val, 3)

            if errors:
                messagebox.showerror(
                    "Invalid threshold",
                    "Please fix these fields:\n- " + "\n- ".join(errors[:12]),
                    parent=win,
                )
                return

            self.config["image_thresholds"] = new_cfg
            save_config(self.config)
            self.status_var.set(f"Saved image thresholds ({len(new_cfg)} keys)")
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btns, text="Save", command=on_save).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=8)

    def _test_telegram(self):
        token = self.tg_token_var.get()
        chat_id = self.tg_chat_var.get()
        if not token or not chat_id:
            messagebox.showwarning("Warning", "Enter Bot Token and Chat ID first")
            return
        notifier = TelegramNotifier(token, chat_id)
        success = notifier.test_connection()
        if success:
            messagebox.showinfo("Success", "Telegram test message sent!")
        else:
            messagebox.showerror("Error", "Failed to send test message")

    def _log_callback(self, msg):
        """Thread-safe log callback."""
        self.root.after(0, self._append_log, msg)

    def _append_log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

        # Update status labels
        if self.engine:
            self.status_labels["state"].set(self.engine.state)
            self.status_labels["step"].set(str(self.engine.current_step))
            self.status_labels["iteration"].set(str(self.engine.iteration_count))
            self.status_labels["input"].set(self.config.get("input_method", "software"))

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _start_automation(self):
        from core.automation import AutomationEngine
        self._apply_ui_to_config()
        save_config(self.config)

        if self.engine:
            self.engine.stop()
        self.engine = AutomationEngine(self.config, log_callback=self._log_callback)
        self.engine.start()

        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Running...")

        # Start status update timer
        self._update_status()

    def _pause_automation(self):
        if self.engine:
            self.engine.pause()
            self.pause_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.NORMAL)
            self.status_var.set("Paused")

    def _resume_automation(self):
        if self.engine:
            self.engine.resume()
            self.resume_btn.config(state=tk.DISABLED)
            self.pause_btn.config(state=tk.NORMAL)
            self.status_var.set("Running...")

    def _stop_automation(self):
        if self.engine:
            self.engine.stop()
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.resume_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Stopped")

    def _update_status(self):
        """Periodically update status labels and stats."""
        if self.engine:
            self.status_labels["state"].set(self.engine.state)
            self.status_labels["step"].set(str(self.engine.current_step))
            self.status_labels["iteration"].set(str(self.engine.iteration_count))

            # Update stats display
            self._refresh_stats()

            if self.engine.state in ("running", "paused"):
                self.root.after(500, self._update_status)
            elif self.engine.state == "success":
                self._refresh_stats()
                self._stop_automation()
                self.status_var.set("SUCCESS! MP 9 found at Level 5!")
            elif self.engine.state == "stopped":
                self._refresh_stats()
                self._stop_automation()
            else:
                # Unknown/transient state - keep polling
                self.root.after(500, self._update_status)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def _check_for_updates(self):
        """Check GitHub for updates and offer to apply them."""
        self.status_var.set("Checking for updates...")
        self.root.update_idletasks()

        def _do_check():
            result = updater.check_for_updates()
            self.root.after(0, lambda: self._on_update_check_done(result))

        threading.Thread(target=_do_check, daemon=True).start()

    def _on_update_check_done(self, result):
        self.status_var.set("Ready")

        if result["error"]:
            messagebox.showerror(
                "Update Check Failed",
                f"Could not check for updates:\n{result['error']}"
            )
            return

        if not result["has_update"]:
            messagebox.showinfo(
                "No Updates",
                f"You are on the latest version.\n(commit: {result['local_commit']})"
            )
            return

        log = result["update_log"] or "(details unavailable)"
        answer = messagebox.askyesno(
            "Update Available",
            f"A new update is available!\n\n"
            f"Current: {result['local_commit']}\n"
            f"Latest:  {result['remote_commit']}\n\n"
            f"Changes:\n{log}\n\n"
            f"Do you want to update now?"
        )
        if answer:
            self._apply_update()

    def _apply_update(self):
        """Pull updates from GitHub."""
        self.status_var.set("Updating...")
        self.root.update_idletasks()

        def _do_update():
            result = updater.apply_update()
            self.root.after(0, lambda: self._on_update_done(result))

        threading.Thread(target=_do_update, daemon=True).start()

    def _on_update_done(self, result):
        self.status_var.set("Ready")

        if result["success"]:
            messagebox.showinfo(
                "Update Complete",
                "Update applied successfully!\n\n"
                "Please restart the application to use the new version."
            )
        else:
            messagebox.showerror(
                "Update Failed",
                f"Update failed:\n{result['message']}"
            )

    def _on_close(self):
        if self.engine and self.engine.state in ("running", "paused"):
            if not messagebox.askyesno("Confirm", "Automation is running. Stop and exit?"):
                return
            self.engine.stop()
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        if hasattr(self, '_file_handler') and self._file_handler:
            logging.getLogger().removeHandler(self._file_handler)
            self._file_handler.close()
        self._apply_ui_to_config()
        save_config(self.config)
        self.root.destroy()

    def run(self):
        self.root.mainloop()
