"""Main GUI window for Lineage Classic automation bot."""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import logging
import os

from core.config import load_config, save_config
from core.automation import AutomationEngine
from core.telegram_notifier import TelegramNotifier
from gui.roi_editor import ROIEditor, ClickPositionEditor
from gui.image_manager import ImageManager


class MainWindow:
    """Main application window."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Lineage Classic Automation Bot")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)

        self.config = load_config()
        self.engine = None

        self._setup_logging()
        self._build_ui()
        self._load_settings_to_ui()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

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

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="ROI Editor", command=self._open_roi_editor)
        tools_menu.add_command(label="Click Position Editor", command=self._open_click_editor)
        tools_menu.add_command(label="Image Manager", command=self._open_image_manager)
        menubar.add_cascade(label="Tools", menu=tools_menu)

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

        # Level Check Method
        level_frame = ttk.LabelFrame(scroll_frame, text="Level Check Method")
        level_frame.pack(fill=tk.X, padx=10, pady=5)

        self.level_method_var = tk.StringVar(value="both")
        for text, val in [
            ("OCR Only", "ocr"),
            ("Image Detection Only", "image"),
            ("Both (Recommended)", "both"),
        ]:
            ttk.Radiobutton(level_frame, text=text, variable=self.level_method_var, value=val).pack(
                anchor=tk.W, padx=10, pady=2
            )

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

        # Quick access buttons
        quick_frame = ttk.LabelFrame(scroll_frame, text="Quick Setup")
        quick_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(quick_frame, text="Open ROI Editor", command=self._open_roi_editor).pack(
            fill=tk.X, padx=10, pady=2
        )
        ttk.Button(
            quick_frame, text="Open Click Position Editor", command=self._open_click_editor
        ).pack(fill=tk.X, padx=10, pady=2)
        ttk.Button(quick_frame, text="Open Image Manager", command=self._open_image_manager).pack(
            fill=tk.X, padx=10, pady=2
        )

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
            "4. Enter character name",
            "5. Click confirm to create character",
            "6. Double-click character to enter game",
            "7. Press Tab, double-click item",
            "8. Click text in popup",
            "9. Wait, then find & click scarecrow",
            "10. Check level/MP after scarecrow clicks",
            "11. Exit game (Ctrl+Q) if MP doesn't match",
            "12. Select & delete character",
            "13. Wait for delete, then restart",
            "14. Level 5 MP=9 -> SUCCESS + Telegram notify",
        ]
        for step in steps:
            ttk.Label(workflow_frame, text=step, font=("", 9)).pack(anchor=tk.W, padx=10, pady=1)

    def _toggle_arduino(self):
        pass  # Arduino frame is always visible

    def _apply_ui_to_config(self):
        """Apply UI values to config dict."""
        self.config["input_method"] = self.input_method_var.get()
        self.config["arduino_port"] = self.arduino_port_var.get()
        try:
            self.config["arduino_baudrate"] = int(self.arduino_baud_var.get())
        except ValueError:
            self.config["arduino_baudrate"] = 9600
        self.config["character_name"] = self.char_name_var.get()
        self.config["telegram_bot_token"] = self.tg_token_var.get()
        self.config["telegram_chat_id"] = self.tg_chat_var.get()
        self.config["level_check_method"] = self.level_method_var.get()
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
        self.tg_token_var.set(self.config.get("telegram_bot_token", ""))
        self.tg_chat_var.set(self.config.get("telegram_chat_id", ""))
        self.level_method_var.set(self.config.get("level_check_method", "both"))
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
        def on_save(cfg):
            self.config.update(cfg)
            save_config(self.config)

        ROIEditor(self.root, self.config, on_save=on_save)

    def _open_click_editor(self):
        def on_save(cfg):
            self.config.update(cfg)
            save_config(self.config)

        ClickPositionEditor(self.root, self.config, on_save=on_save)

    def _open_image_manager(self):
        def on_save(cfg):
            self.config.update(cfg)
            save_config(self.config)

        ImageManager(self.root, self.config, on_save=on_save)

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
        self._apply_ui_to_config()
        save_config(self.config)

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
        """Periodically update status labels."""
        if self.engine:
            self.status_labels["state"].set(self.engine.state)
            self.status_labels["step"].set(str(self.engine.current_step))
            self.status_labels["iteration"].set(str(self.engine.iteration_count))

            if self.engine.state in (
                AutomationEngine.STATE_RUNNING,
                AutomationEngine.STATE_PAUSED,
            ):
                self.root.after(500, self._update_status)
            elif self.engine.state == AutomationEngine.STATE_SUCCESS:
                self.status_var.set("SUCCESS! MP 9 found at Level 5!")
                self._stop_automation()
            elif self.engine.state == AutomationEngine.STATE_STOPPED:
                self._stop_automation()

    def _on_close(self):
        if self.engine and self.engine.state == AutomationEngine.STATE_RUNNING:
            if not messagebox.askyesno("Confirm", "Automation is running. Stop and exit?"):
                return
            self.engine.stop()
        self._apply_ui_to_config()
        save_config(self.config)
        self.root.destroy()

    def run(self):
        self.root.mainloop()
