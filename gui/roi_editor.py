"""ROI (Region of Interest) editor with visual selection on screen capture."""
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw
import mss
import os
import time

from gui.window_utils import find_windows_by_title, get_window_rect, capture_window, list_all_windows


class ROIEditor(tk.Toplevel):
    """Visual ROI editor: capture screen and drag-select regions."""

    ROI_LABELS = {
        "empty_slot": "Empty Slot (Character Select)",
        "knight_icon": "Knight Icon (Class Selection)",
        "knight_verify": "Knight Verify Area",
        "name_input": "Name Input Field",
        "confirm_button": "Confirm Button",
        "character_slot": "Character Slot (Select Screen)",
        "tab_area": "Tab Area",
        "item_slot": "Item Slot (Inventory)",
        "popup_text": "Popup Text Area",
        "scarecrow_search": "Scarecrow Search Area",
        "level_display": "Level Display Area",
        "mp_display": "MP Display Area",
        "exit_button": "Exit Button Area",
        "delete_button": "Delete Button Area",
        "delete_popup": "Delete Popup Area",
        "click_after_enter": "Click After Enter Game",
        "exp_display": "EXP Display Area (Stuck Detection)",
        "hp_display": "HP Display Area (Death Detection)",
    }

    # ROI keys that correspond to an image template in config["images"]
    CAPTURABLE_ROIS = {
        "empty_slot", "knight_icon", "knight_verify", "confirm_button",
        "item_slot", "popup_text", "scarecrow_search", "level_display",
        "mp_display", "exit_button", "delete_button", "delete_popup",
    }

    def __init__(self, parent, config, images_dir="images", on_save=None):
        super().__init__(parent)
        self.title("ROI Editor")
        self.config = config
        self.images_dir = images_dir
        self.on_save = on_save
        self.current_roi_key = None
        self.screenshot = None
        self.photo = None
        self.drag_start = None
        self.drag_rect = None
        self.scale_factor = 1.0
        # Window-relative mode
        self._window_id = None
        self._window_rect = None  # {"x","y","w","h"} of target window on screen

        os.makedirs(images_dir, exist_ok=True)
        self.geometry("1200x800")
        self._resolve_target_window()
        self._build_ui()

    def _resolve_target_window(self):
        """Find the target window from config."""
        title = self.config.get("target_window_title", "")
        if not title:
            return
        windows = find_windows_by_title(title)
        if windows:
            self._window_id = windows[0][0]
            self._window_rect = get_window_rect(self._window_id)

    def _build_ui(self):
        # Left panel: ROI list
        left_frame = ttk.Frame(self, width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        left_frame.pack_propagate(False)

        ttk.Label(left_frame, text="ROI Regions", font=("", 12, "bold")).pack(pady=5)

        # Window info
        win_title = self.config.get("target_window_title", "")
        if win_title:
            status = "Found" if self._window_id else "NOT FOUND"
            ttk.Label(left_frame, text=f"Target: {win_title} [{status}]",
                      foreground="green" if self._window_id else "red",
                      wraplength=280).pack(pady=2)
        else:
            ttk.Label(left_frame, text="No target window (full screen mode)",
                      foreground="gray").pack(pady=2)

        # ROI listbox
        self.roi_listbox = tk.Listbox(left_frame, font=("", 10))
        self.roi_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        self.roi_listbox.bind("<<ListboxSelect>>", self._on_roi_select)

        for key, label in self.ROI_LABELS.items():
            roi = self.config["roi"].get(key, {})
            status = "SET" if roi.get("w", 0) > 10 else "---"
            self.roi_listbox.insert(tk.END, f"[{status}] {label}")

        # Current ROI info
        info_frame = ttk.LabelFrame(left_frame, text="Selected ROI")
        info_frame.pack(fill=tk.X, pady=5)

        self.roi_info_var = tk.StringVar(value="Select a ROI from the list")
        ttk.Label(info_frame, textvariable=self.roi_info_var, wraplength=280).pack(padx=5, pady=5)

        # Manual entry
        manual_frame = ttk.LabelFrame(left_frame, text="Manual Entry (window-relative)")
        manual_frame.pack(fill=tk.X, pady=5)

        coord_frame = ttk.Frame(manual_frame)
        coord_frame.pack(padx=5, pady=5)
        self.manual_vars = {}
        for i, label in enumerate(["X:", "Y:", "W:", "H:"]):
            ttk.Label(coord_frame, text=label).grid(row=i // 2, column=(i % 2) * 2, padx=2)
            var = tk.StringVar(value="0")
            ttk.Entry(coord_frame, textvariable=var, width=8).grid(
                row=i // 2, column=(i % 2) * 2 + 1, padx=2
            )
            self.manual_vars[label[0].lower()] = var

        ttk.Button(manual_frame, text="Apply Manual", command=self._apply_manual).pack(pady=5)

        # Capture as image section
        capture_frame = ttk.LabelFrame(left_frame, text="Capture ROI as Image")
        capture_frame.pack(fill=tk.X, pady=5)

        ttk.Button(
            capture_frame, text="Capture from Screenshot",
            command=self._capture_roi_from_screenshot,
        ).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(
            capture_frame, text="Capture Live Screen",
            command=self._capture_roi_live,
        ).pack(fill=tk.X, padx=5, pady=2)

        self.capture_preview_label = ttk.Label(capture_frame, text="")
        self.capture_preview_label.pack(padx=5, pady=2)

        # Buttons
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Capture Screen", command=self._capture_screen).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Capture Window...",
                   command=self._capture_selected_window).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Save All ROIs", command=self._save_all).pack(
            fill=tk.X, pady=2
        )

        # Right panel: Screen capture display
        right_frame = ttk.Frame(self)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(right_frame, bg="gray20", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        # Status bar
        self.status_var = tk.StringVar(value="Click 'Capture Screen' to start")
        ttk.Label(self, textvariable=self.status_var).pack(side=tk.BOTTOM, fill=tk.X)

    def _capture_screen(self):
        """Capture the target window (or full screen if no target)."""
        self.withdraw()
        self.update()
        time.sleep(0.5)

        if self._window_id:
            # Refresh window rect in case it moved
            self._window_rect = get_window_rect(self._window_id)
            if not self._window_rect:
                self.deiconify()
                messagebox.showerror("Error", "Target window not found. Is it still open?")
                return
            img, rect = capture_window(self._window_id)
            if img is None:
                self.deiconify()
                messagebox.showerror("Error", "Failed to capture target window.")
                return
            self.screenshot = img
            self.screen_width = rect["w"]
            self.screen_height = rect["h"]
        else:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)
                self.screenshot = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                self.screen_width = monitor["width"]
                self.screen_height = monitor["height"]

        self.deiconify()
        self._display_screenshot()
        mode = "window" if self._window_id else "full screen"
        self.status_var.set(f"Captured ({mode}). Select a ROI, then drag on the image.")

    def _capture_selected_window(self):
        """Show a window list dialog and capture the selected window."""
        dialog = WindowSelectDialog(self)
        self.wait_window(dialog)

        if dialog.selected_window_id is None:
            return

        wid = dialog.selected_window_id

        self.withdraw()
        self.update()
        time.sleep(0.5)

        rect = get_window_rect(wid)
        if not rect:
            self.deiconify()
            messagebox.showerror("Error", "Failed to get window geometry. Is it still open?")
            return

        img, rect = capture_window(wid)
        if img is None:
            self.deiconify()
            messagebox.showerror("Error", "Failed to capture the selected window.")
            return

        # Update window tracking so ROI coordinates are relative to this window
        self._window_id = wid
        self._window_rect = rect
        self.screenshot = img
        self.screen_width = rect["w"]
        self.screen_height = rect["h"]

        self.deiconify()
        self._display_screenshot()
        self.status_var.set(
            f"Captured window ({rect['w']}x{rect['h']}). "
            f"Select a ROI, then drag on the image."
        )

    def _display_screenshot(self):
        if self.screenshot is None:
            return
        canvas_w = self.canvas.winfo_width() or 800
        canvas_h = self.canvas.winfo_height() or 600
        img_w, img_h = self.screenshot.size

        self.scale_factor = min(canvas_w / img_w, canvas_h / img_h)
        new_w = int(img_w * self.scale_factor)
        new_h = int(img_h * self.scale_factor)

        display_img = self.screenshot.resize((new_w, new_h), Image.LANCZOS)

        # Draw existing ROIs
        draw = ImageDraw.Draw(display_img)
        roi_keys = list(self.ROI_LABELS.keys())
        colors = [
            "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF",
            "#FFA500", "#800080", "#008080", "#FFD700", "#DC143C", "#00CED1",
            "#FF6347", "#7B68EE", "#32CD32", "#FF69B4",
        ]
        for i, key in enumerate(roi_keys):
            roi = self.config["roi"].get(key, {})
            if roi.get("w", 0) > 10:
                sx = int(roi["x"] * self.scale_factor)
                sy = int(roi["y"] * self.scale_factor)
                ex = int((roi["x"] + roi["w"]) * self.scale_factor)
                ey = int((roi["y"] + roi["h"]) * self.scale_factor)
                color = colors[i % len(colors)]
                draw.rectangle([sx, sy, ex, ey], outline=color, width=2)
                draw.text((sx + 2, sy + 2), key[:8], fill=color)

        self.photo = ImageTk.PhotoImage(display_img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

    def _on_roi_select(self, event):
        selection = self.roi_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        self.current_roi_key = list(self.ROI_LABELS.keys())[idx]
        roi = self.config["roi"].get(self.current_roi_key, {})
        self.roi_info_var.set(
            f"{self.ROI_LABELS[self.current_roi_key]}\n"
            f"X={roi.get('x', 0)}, Y={roi.get('y', 0)}, "
            f"W={roi.get('w', 0)}, H={roi.get('h', 0)}"
        )
        self.manual_vars["x"].set(str(roi.get("x", 0)))
        self.manual_vars["y"].set(str(roi.get("y", 0)))
        self.manual_vars["w"].set(str(roi.get("w", 0)))
        self.manual_vars["h"].set(str(roi.get("h", 0)))

    def _on_drag_start(self, event):
        if self.current_roi_key is None:
            self.status_var.set("Please select a ROI from the list first!")
            return
        self.drag_start = (event.x, event.y)
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)

    def _on_drag_motion(self, event):
        if self.drag_start is None:
            return
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)
        self.drag_rect = self.canvas.create_rectangle(
            self.drag_start[0], self.drag_start[1], event.x, event.y,
            outline="lime", width=2, dash=(4, 4),
        )

    def _on_drag_end(self, event):
        if self.drag_start is None or self.current_roi_key is None:
            return

        x1 = min(self.drag_start[0], event.x)
        y1 = min(self.drag_start[1], event.y)
        x2 = max(self.drag_start[0], event.x)
        y2 = max(self.drag_start[1], event.y)

        # Convert back to window-relative coordinates
        real_x = int(x1 / self.scale_factor)
        real_y = int(y1 / self.scale_factor)
        real_w = int((x2 - x1) / self.scale_factor)
        real_h = int((y2 - y1) / self.scale_factor)

        if real_w < 5 or real_h < 5:
            self.drag_start = None
            return

        self.config["roi"][self.current_roi_key] = {
            "x": real_x, "y": real_y, "w": real_w, "h": real_h
        }

        coord_type = "window-relative" if self._window_id else "screen"
        self.roi_info_var.set(
            f"{self.ROI_LABELS[self.current_roi_key]}\n"
            f"X={real_x}, Y={real_y}, W={real_w}, H={real_h} ({coord_type})"
        )
        self.manual_vars["x"].set(str(real_x))
        self.manual_vars["y"].set(str(real_y))
        self.manual_vars["w"].set(str(real_w))
        self.manual_vars["h"].set(str(real_h))

        # Update listbox
        idx = list(self.ROI_LABELS.keys()).index(self.current_roi_key)
        label = self.ROI_LABELS[self.current_roi_key]
        self.roi_listbox.delete(idx)
        self.roi_listbox.insert(idx, f"[SET] {label}")
        self.roi_listbox.selection_set(idx)

        # Auto-capture template image when ROI is set by drag
        saved_msg = ""
        if self.screenshot and self.current_roi_key in self.CAPTURABLE_ROIS:
            cropped = self.screenshot.crop((
                real_x, real_y, real_x + real_w, real_y + real_h,
            ))
            self._save_captured_image(cropped)
            saved_msg = " + template image saved"

        self.drag_start = None
        self._display_screenshot()
        self.status_var.set(
            f"ROI '{self.current_roi_key}' updated: {real_x},{real_y} "
            f"{real_w}x{real_h}{saved_msg}"
        )

    def _apply_manual(self):
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI first")
            return
        try:
            x = int(self.manual_vars["x"].get())
            y = int(self.manual_vars["y"].get())
            w = int(self.manual_vars["w"].get())
            h = int(self.manual_vars["h"].get())
        except ValueError:
            messagebox.showerror("Error", "Invalid coordinates")
            return

        self.config["roi"][self.current_roi_key] = {"x": x, "y": y, "w": w, "h": h}
        idx = list(self.ROI_LABELS.keys()).index(self.current_roi_key)
        label = self.ROI_LABELS[self.current_roi_key]
        self.roi_listbox.delete(idx)
        self.roi_listbox.insert(idx, f"[SET] {label}")
        self.roi_listbox.selection_set(idx)
        self._display_screenshot()
        self.status_var.set(f"ROI '{self.current_roi_key}' manually set")

    def _save_all(self):
        if self.on_save:
            self.on_save(self.config)
        self.status_var.set("All ROIs saved!")
        messagebox.showinfo("Saved", "ROI settings saved successfully!")

    def _capture_roi_from_screenshot(self):
        """Crop the selected ROI from the already-captured screenshot and save as template image."""
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI from the list first")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            messagebox.showinfo("Info", "This ROI is not associated with a template image.")
            return
        if self.screenshot is None:
            messagebox.showwarning("Warning", "Capture the screen first (click 'Capture Screen')")
            return

        roi = self.config["roi"].get(self.current_roi_key, {})
        if roi.get("w", 0) <= 5 or roi.get("h", 0) <= 5:
            messagebox.showwarning("Warning", "ROI is too small. Drag to set the region first.")
            return

        # Crop from the stored screenshot (already window-relative)
        cropped = self.screenshot.crop((
            roi["x"], roi["y"],
            roi["x"] + roi["w"], roi["y"] + roi["h"],
        ))
        self._save_captured_image(cropped)

    def _capture_roi_live(self):
        """Capture the selected ROI region directly from the live screen."""
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI from the list first")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            messagebox.showinfo("Info", "This ROI is not associated with a template image.")
            return

        roi = self.config["roi"].get(self.current_roi_key, {})
        if roi.get("w", 0) <= 5 or roi.get("h", 0) <= 5:
            messagebox.showwarning("Warning", "ROI is too small. Set the region first.")
            return

        # Minimize window, capture live, restore
        self.withdraw()
        self.update()
        time.sleep(0.5)

        # Convert window-relative ROI to absolute screen coords for capture
        abs_x = roi["x"]
        abs_y = roi["y"]
        if self._window_id:
            self._window_rect = get_window_rect(self._window_id)
            if self._window_rect:
                abs_x += self._window_rect["x"]
                abs_y += self._window_rect["y"]

        with mss.mss() as sct:
            monitor = {
                "left": abs_x, "top": abs_y,
                "width": roi["w"], "height": roi["h"],
            }
            grab = sct.grab(monitor)
            cropped = Image.frombytes("RGB", grab.size, grab.rgb)

        self.deiconify()
        self._save_captured_image(cropped)

    def _save_captured_image(self, image):
        """Save a captured PIL image as the template for the current ROI key."""
        # Map ROI key to image config key (some differ)
        image_key_map = {
            "item_slot": "item_icon",
            "scarecrow_search": "scarecrow",
            "level_display": "level_up_effect",
            "exit_button": "exit_button",
            "delete_button": "exit_button",
            "delete_popup": "delete_popup",
        }
        image_key = image_key_map.get(self.current_roi_key, self.current_roi_key)

        dest = os.path.join(self.images_dir, f"{image_key}.png")
        image.save(dest)
        self.config.setdefault("images", {})[image_key] = dest

        self.capture_preview_label.config(
            text=f"Saved: {image_key}.png ({image.width}x{image.height})"
        )
        self.status_var.set(
            f"ROI '{self.current_roi_key}' captured as template image -> {dest}"
        )


class WindowSelectDialog(tk.Toplevel):
    """Dialog to list and select an active window for capture."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Select Window to Capture")
        self.selected_window_id = None
        self._windows = []
        self.geometry("500x400")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        ttk.Label(self, text="Select a window to capture:",
                  font=("", 11, "bold")).pack(padx=10, pady=(10, 5))

        # Refresh button
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10)
        ttk.Button(top_frame, text="Refresh", command=self._refresh_list).pack(side=tk.RIGHT)

        # Window list
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.window_listbox = tk.Listbox(list_frame, font=("", 10),
                                         yscrollcommand=scrollbar.set)
        self.window_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.window_listbox.yview)

        self.window_listbox.bind("<Double-1>", lambda e: self._on_select())

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Capture", command=self._on_select).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self._refresh_list()

    def _refresh_list(self):
        self.window_listbox.delete(0, tk.END)
        self._windows = list_all_windows()
        for wid, title in self._windows:
            self.window_listbox.insert(tk.END, title)
        if not self._windows:
            self.window_listbox.insert(tk.END, "(No windows found)")

    def _on_select(self):
        selection = self.window_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        if idx >= len(self._windows):
            return
        self.selected_window_id = self._windows[idx][0]
        self.destroy()


class ClickPositionEditor(tk.Toplevel):
    """Editor for click positions (single x,y points)."""

    POSITION_LABELS = {
        "knight_verify_click": "Knight Verify Click Position",
        "name_input_click": "Name Input Click Position",
        "character_slot_click": "Character Slot Click Position",
        "tab_click": "Tab Click Position",
        "after_enter_click": "After Enter Game Click Position",
        "exit_confirm_click": "Exit Confirm Click Position",
        "delete_click": "Delete Button Click Position",
        "character_center": "Character Center (Screen Center)",
    }

    def __init__(self, parent, config, on_save=None):
        super().__init__(parent)
        self.title("Click Position Editor")
        self.config = config
        self.on_save = on_save
        # Window-relative mode
        self._window_id = None
        self._window_rect = None
        self._resolve_target_window()
        self.geometry("500x650")
        self._build_ui()

    def _resolve_target_window(self):
        title = self.config.get("target_window_title", "")
        if not title:
            return
        windows = find_windows_by_title(title)
        if windows:
            self._window_id = windows[0][0]
            self._window_rect = get_window_rect(self._window_id)

    def _build_ui(self):
        ttk.Label(self, text="Click Positions", font=("", 14, "bold")).pack(pady=10)

        # Window info
        win_title = self.config.get("target_window_title", "")
        if win_title:
            status = "Found" if self._window_id else "NOT FOUND"
            ttk.Label(self,
                      text=f"Target: {win_title} [{status}]\n"
                      "Coordinates are window-relative.",
                      foreground="green" if self._window_id else "red",
                      wraplength=450).pack(pady=5)
        else:
            ttk.Label(self,
                      text="No target window. Coordinates are screen-absolute.\n"
                      "Click 'Pick' to select a position by clicking on screen.",
                      wraplength=450).pack(pady=5)

        self.entries = {}
        scroll_frame = ttk.Frame(self)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Keys stored at config top-level instead of click_positions
        self._toplevel_keys = {"character_center"}

        for key, label in self.POSITION_LABELS.items():
            frame = ttk.LabelFrame(scroll_frame, text=label)
            frame.pack(fill=tk.X, pady=3)

            if key in self._toplevel_keys:
                pos = self.config.get(key, {"x": 0, "y": 0})
            else:
                pos = self.config.get("click_positions", {}).get(key, {"x": 0, "y": 0})
            x_var = tk.StringVar(value=str(pos.get("x", 0)))
            y_var = tk.StringVar(value=str(pos.get("y", 0)))

            inner = ttk.Frame(frame)
            inner.pack(fill=tk.X, padx=5, pady=3)

            ttk.Label(inner, text="X:").pack(side=tk.LEFT)
            ttk.Entry(inner, textvariable=x_var, width=6).pack(side=tk.LEFT, padx=2)
            ttk.Label(inner, text="Y:").pack(side=tk.LEFT, padx=(10, 0))
            ttk.Entry(inner, textvariable=y_var, width=6).pack(side=tk.LEFT, padx=2)

            pick_btn = ttk.Button(
                inner, text="Pick",
                command=lambda k=key, xv=x_var, yv=y_var: self._pick_position(k, xv, yv),
            )
            pick_btn.pack(side=tk.RIGHT, padx=5)

            self.entries[key] = (x_var, y_var)

        ttk.Button(self, text="Save All Positions", command=self._save_all).pack(pady=10)

    def _pick_position(self, key, x_var, y_var):
        """Open the screen picker (window-aware)."""
        # Re-resolve target window each time (it may have moved or appeared)
        self._resolve_target_window()
        if not self._window_id:
            messagebox.showwarning(
                "Warning",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.\n"
                "Coordinates must be window-relative for automation to work correctly.",
            )
            return

        self.withdraw()
        self.update()

        picker = ScreenPicker(
            self,
            window_id=self._window_id,
            callback=lambda x, y: self._on_pick(key, x_var, y_var, x, y),
        )
        picker.wait_window()
        self.deiconify()

    def _on_pick(self, key, x_var, y_var, x, y):
        x_var.set(str(x))
        y_var.set(str(y))

    def _save_all(self):
        for key, (x_var, y_var) in self.entries.items():
            try:
                x = int(x_var.get())
                y = int(y_var.get())
            except ValueError:
                messagebox.showerror("Error", f"Invalid coordinates for {key}")
                return
            if key in self._toplevel_keys:
                self.config[key] = {"x": x, "y": y}
            else:
                self.config.setdefault("click_positions", {})[key] = {"x": x, "y": y}

        if self.on_save:
            self.on_save(self.config)
        messagebox.showinfo("Saved", "All click positions saved!")


class ScreenPicker(tk.Toplevel):
    """Pick a screen position.

    If window_id is set, shows only that window's capture and returns
    window-relative coordinates.  Otherwise shows a fullscreen overlay
    and returns absolute screen coordinates (converted to window-relative
    when the target window rect is known).
    """

    def __init__(self, parent, window_id=None, callback=None):
        super().__init__(parent)
        self.callback = callback
        self._window_id = window_id
        self._window_rect = None
        self.scale_factor = 1.0

        if window_id:
            self._window_rect = get_window_rect(window_id)

        if self._window_rect:
            self._build_window_mode()
        else:
            self._build_fullscreen_mode()

    def _build_fullscreen_mode(self):
        """Fullscreen overlay. Converts to window-relative if target window is known."""
        # Try to get window rect for conversion even in fullscreen mode
        if self._window_id and not self._window_rect:
            self._window_rect = get_window_rect(self._window_id)

        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.3)
        self.configure(bg="black")
        self.config(cursor="crosshair")

        self.bind("<ButtonPress-1>", self._on_click_fullscreen)
        self.bind("<Escape>", lambda e: self.destroy())

        if self._window_rect:
            hint = ("Click on the target window to set position.\n"
                    "Coordinates will be converted to window-relative. (ESC to cancel)")
        else:
            hint = "Click anywhere to set position (ESC to cancel)"
        label = tk.Label(
            self, text=hint,
            fg="white", bg="black", font=("", 16),
        )
        label.place(relx=0.5, rely=0.1, anchor=tk.CENTER)

    def _build_window_mode(self):
        """Capture target window and let user click on the image."""
        time.sleep(0.3)
        img, rect = capture_window(self._window_id)
        if img is None:
            self.destroy()
            return

        self._window_rect = rect
        self._capture_img = img

        # Size the picker window to fit image (max 80% of screen)
        with mss.mss() as sct:
            scr_w = sct.monitors[1]["width"]
            scr_h = sct.monitors[1]["height"]
        max_w = int(scr_w * 0.85)
        max_h = int(scr_h * 0.85)
        self.scale_factor = min(max_w / img.width, max_h / img.height, 1.0)
        disp_w = int(img.width * self.scale_factor)
        disp_h = int(img.height * self.scale_factor)

        self.title("Click to set position (ESC to cancel)")
        self.geometry(f"{disp_w}x{disp_h + 40}")
        self.resizable(False, False)

        label = ttk.Label(self,
                          text="Click on the target window image to pick a position. "
                          "Coordinates are window-relative. ESC to cancel.")
        label.pack(pady=5)

        self.canvas = tk.Canvas(self, width=disp_w, height=disp_h,
                                bg="gray20", cursor="crosshair")
        self.canvas.pack()

        display = img.resize((disp_w, disp_h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(display)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

        self.canvas.bind("<ButtonPress-1>", self._on_click_window)
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()
        self.grab_set()

    def _on_click_fullscreen(self, event):
        x = event.x_root
        y = event.y_root
        # Convert absolute screen coords to window-relative if possible
        if self._window_rect:
            x -= self._window_rect["x"]
            y -= self._window_rect["y"]
        if self.callback:
            self.callback(x, y)
        self.destroy()

    def _on_click_window(self, event):
        # Convert canvas coords back to window-relative pixel coords
        win_x = int(event.x / self.scale_factor)
        win_y = int(event.y / self.scale_factor)
        if self.callback:
            self.callback(win_x, win_y)
        self.destroy()
