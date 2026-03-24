"""Unified ROI & Image editor with visual selection on screen capture."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import shutil
import time
import logging

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk, ImageDraw
except ImportError:
    Image = ImageTk = ImageDraw = None
    logger.warning("Pillow not installed. ROI Editor image features will be unavailable.")

try:
    import mss
except ImportError:
    mss = None
    logger.warning("mss not installed. Screen capture will be unavailable.")

from gui.window_utils import find_windows_by_title, get_window_rect, capture_window, list_all_windows
from core.image_recognition import ImageRecognition


class ROIEditor(tk.Toplevel):
    """Unified ROI & Image editor.

    - Drag on screenshot: first time captures template + sets ROI;
      subsequent drags update ROI coordinates only (template kept).
    - "Replace Image" buttons let the user explicitly overwrite the template.
    - "Load from File" imports an external image as template.
    - All changes auto-save to config.json via the on_save callback.
    """

    ROI_LABELS = {
        "empty_slot": "Empty Slot (Character Select)",
        "knight_icon": "Knight Icon (Class Selection)",
        "knight_verify": "Knight Verify Area",
        "confirm_button": "Confirm Button",
        "item_slot": "Item Slot (Inventory)",
        "popup_text": "Popup Text Area",
        "scarecrow_search": "Scarecrow Search Area",
        "level_display": "Level Display Area",
        "level_5": "Level 5 Template (uses Level Display ROI)",
        "mp_display": "MP Display Area",
        "mp_2": "MP 2 Template (uses MP Display ROI)",
        "mp_3": "MP 3 Template (uses MP Display ROI)",
        "mp_4": "MP 4 Template (uses MP Display ROI)",
        "mp_5": "MP 5 Template (uses MP Display ROI)",
        "mp_6": "MP 6 Template (uses MP Display ROI)",
        "mp_7": "MP 7 Template (uses MP Display ROI)",
        "mp_8": "MP 8 Template (uses MP Display ROI)",
        "exit_button": "Exit Button Area",
        "delete_popup": "Delete Popup Area",
        "exp_display": "EXP Display Area (Stuck Detection)",
        "hp_display": "HP Display Area (Death Detection)",
        "game_entered": "Game Entered Screen (Post-Login Verify)",
    }

    # ROI keys that correspond to an image template in config["images"]
    CAPTURABLE_ROIS = {
        "empty_slot", "knight_icon", "knight_verify", "confirm_button",
        "item_slot", "popup_text", "scarecrow_search", "level_display",
        "mp_display", "exit_button", "delete_popup",
        "level_5", "mp_2", "mp_3", "mp_4", "mp_5", "mp_6", "mp_7", "mp_8",
        "game_entered",
    }

    # Template-only entries that share another entry's ROI coordinates.
    # These keys have no own ROI in config["roi"]; they borrow from the
    # parent ROI for capture/test but store a separate template image.
    SHARED_ROI = {
        "level_5": "level_display",
        "mp_2": "mp_display",
        "mp_3": "mp_display",
        "mp_4": "mp_display",
        "mp_5": "mp_display",
        "mp_6": "mp_display",
        "mp_7": "mp_display",
        "mp_8": "mp_display",
    }

    # Map ROI key -> image config key (where names differ)
    ROI_TO_IMAGE_KEY = {
        "item_slot": "item_icon",
        "scarecrow_search": "scarecrow",
        "exit_button": "exit_button",
        "delete_popup": "delete_popup",
    }

    # ROI key -> click_positions key to auto-fill using ROI center.
    ROI_TO_CLICK_KEY = {
        "knight_verify": "knight_verify_click",
        "empty_slot": "character_slot_click",
        "scarecrow_search": "after_enter_click",
    }

    def __init__(self, parent, config, images_dir="images", on_save=None):
        super().__init__(parent)
        self.title("ROI & Image Editor")
        self.config = config
        self.images_dir = images_dir
        self.on_save = on_save
        self.current_roi_key = None
        self.screenshot = None
        self.photo = None
        self.drag_start = None
        self.drag_rect = None
        self.scale_factor = 1.0
        self._preview_photo = None
        self.recognizer = ImageRecognition()
        # Window-relative mode
        self._window_id = None
        self._window_rect = None  # {"x","y","w","h"} of target window on screen

        os.makedirs(images_dir, exist_ok=True)
        self.geometry("1200x800")
        self._resolve_target_window()
        self._build_ui()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_target_window(self):
        """Find the target window from config."""
        title = self.config.get("target_window_title", "")
        if not title:
            return
        windows = find_windows_by_title(title)
        # Exclude our own windows to avoid capturing the bot UI
        own_titles = ("LC AB", "Scarecrow Detection Editor",
                      "ROI & Image Editor", "Click Position Editor")
        windows = [(wid, wtitle) for wid, wtitle in windows
                   if not wtitle.startswith(own_titles)]
        if windows:
            self._window_id = windows[0][0]
            self._window_rect = get_window_rect(self._window_id)

    def _image_key_for(self, roi_key):
        """Return the config['images'] key that corresponds to *roi_key*."""
        return self.ROI_TO_IMAGE_KEY.get(roi_key, roi_key)

    def _effective_roi_key(self, key):
        """Return the actual config['roi'] key to use for coordinates.

        Template-only entries (level_5, mp_2~mp_8) share the ROI of their
        parent entry (level_display, mp_display).
        """
        return self.SHARED_ROI.get(key, key)

    def _has_template(self, roi_key):
        """Return True if a template image file exists for *roi_key*."""
        image_key = self._image_key_for(roi_key)
        path = self.config.get("images", {}).get(image_key, "")
        return bool(path) and os.path.exists(path)

    def _auto_save(self):
        """Persist config to disk via the on_save callback."""
        if self.on_save:
            self.on_save(self.config)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Left panel
        left_frame = ttk.Frame(self, width=320)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        left_frame.pack_propagate(False)

        ttk.Label(left_frame, text="ROI & Image Editor",
                  font=("", 12, "bold")).pack(pady=5)

        # Window info
        win_title = self.config.get("target_window_title", "")
        if win_title:
            status = "Found" if self._window_id else "NOT FOUND"
            ttk.Label(left_frame, text=f"Target: {win_title} [{status}]",
                      foreground="green" if self._window_id else "red",
                      wraplength=300).pack(pady=2)
        else:
            ttk.Label(left_frame, text="No target window (full screen mode)",
                      foreground="gray").pack(pady=2)

        # ROI listbox
        self.roi_listbox = tk.Listbox(left_frame, font=("", 10))
        self.roi_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        self.roi_listbox.bind("<<ListboxSelect>>", self._on_roi_select)
        self._refresh_listbox()

        # Current ROI info
        info_frame = ttk.LabelFrame(left_frame, text="Selected ROI")
        info_frame.pack(fill=tk.X, pady=5)

        self.roi_info_var = tk.StringVar(value="Select a ROI from the list")
        ttk.Label(info_frame, textvariable=self.roi_info_var,
                  wraplength=300).pack(padx=5, pady=5)

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

        ttk.Button(manual_frame, text="Apply Manual",
                   command=self._apply_manual).pack(pady=5)

        # Template image section
        img_frame = ttk.LabelFrame(left_frame, text="Template Image")
        img_frame.pack(fill=tk.X, pady=5)

        ttk.Button(
            img_frame, text="Replace from Screenshot",
            command=self._replace_image_from_screenshot,
        ).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(
            img_frame, text="Replace from Live Screen",
            command=self._replace_image_live,
        ).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(
            img_frame, text="Load from File...",
            command=self._load_image_from_file,
        ).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(
            img_frame, text="Test Matching (Current ROI)",
            command=self._test_template_matching,
        ).pack(fill=tk.X, padx=5, pady=2)

        self.preview_canvas = tk.Canvas(img_frame, bg="gray30",
                                        height=80, width=280)
        self.preview_canvas.pack(padx=5, pady=5)
        self.preview_info_var = tk.StringVar(value="")
        ttk.Label(img_frame, textvariable=self.preview_info_var,
                  wraplength=300).pack(padx=5)

        # Screen capture buttons
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Capture Screen",
                   command=self._capture_screen).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Capture Window...",
                   command=self._capture_selected_window).pack(fill=tk.X, pady=2)

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

    # ------------------------------------------------------------------
    # Listbox helpers
    # ------------------------------------------------------------------

    def _roi_status(self, key):
        """Return a short status tag for the listbox entry."""
        effective_key = self._effective_roi_key(key)
        roi = self.config["roi"].get(effective_key, {})
        has_roi = roi.get("w", 0) > 10
        has_img = self._has_template(key) if key in self.CAPTURABLE_ROIS else None

        if has_img is None:
            # Non-capturable ROI – only coordinate status matters
            return "SET" if has_roi else "---"
        if has_roi and has_img:
            return "OK"
        if has_roi:
            return "ROI"
        if has_img:
            return "IMG"
        return "---"

    def _refresh_listbox(self):
        sel = self.roi_listbox.curselection()
        self.roi_listbox.delete(0, tk.END)
        for key, label in self.ROI_LABELS.items():
            tag = self._roi_status(key)
            self.roi_listbox.insert(tk.END, f"[{tag}] {label}")
        if sel:
            self.roi_listbox.selection_set(sel[0])

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    def _capture_screen(self):
        """Capture the target window (requires a valid target window)."""
        self._resolve_target_window()
        if not self._window_id:
            messagebox.showerror(
                "Error",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.",
            )
            return

        self.withdraw()
        self.update()
        time.sleep(0.5)

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

        self.deiconify()
        self._display_screenshot()
        self.status_var.set(
            f"Captured window ({rect['w']}x{rect['h']}). "
            f"Select a ROI, then drag on the image."
        )

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

    # ------------------------------------------------------------------
    # ROI selection
    # ------------------------------------------------------------------

    def _on_roi_select(self, event):
        selection = self.roi_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        self.current_roi_key = list(self.ROI_LABELS.keys())[idx]
        effective_key = self._effective_roi_key(self.current_roi_key)
        roi = self.config["roi"].get(effective_key, {})
        shared_note = ""
        if self.current_roi_key in self.SHARED_ROI:
            shared_note = f"\n(shares ROI with '{effective_key}')"
        self.roi_info_var.set(
            f"{self.ROI_LABELS[self.current_roi_key]}{shared_note}\n"
            f"X={roi.get('x', 0)}, Y={roi.get('y', 0)}, "
            f"W={roi.get('w', 0)}, H={roi.get('h', 0)}"
        )
        self.manual_vars["x"].set(str(roi.get("x", 0)))
        self.manual_vars["y"].set(str(roi.get("y", 0)))
        self.manual_vars["w"].set(str(roi.get("w", 0)))
        self.manual_vars["h"].set(str(roi.get("h", 0)))

        # Show template preview
        self._update_preview()

    def _update_preview(self):
        """Show the template image preview for the currently selected ROI."""
        self.preview_canvas.delete("all")
        self._preview_photo = None
        if self.current_roi_key is None:
            self.preview_info_var.set("")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            self.preview_info_var.set("(no template for this ROI)")
            return

        image_key = self._image_key_for(self.current_roi_key)
        path = self.config.get("images", {}).get(image_key, "")
        if path and os.path.exists(path):
            try:
                img = Image.open(path)
                cw = self.preview_canvas.winfo_width() or 280
                ch = self.preview_canvas.winfo_height() or 80
                scale = min(cw / img.width, ch / img.height, 1.0)
                new_size = (max(1, int(img.width * scale)),
                            max(1, int(img.height * scale)))
                img = img.resize(new_size, Image.LANCZOS)
                self._preview_photo = ImageTk.PhotoImage(img)
                self.preview_canvas.create_image(
                    cw // 2, ch // 2, anchor=tk.CENTER,
                    image=self._preview_photo)
                self.preview_info_var.set(f"{image_key}.png ({img.width}x{img.height})")
            except Exception as e:
                self.preview_info_var.set(f"Error: {e}")
        else:
            self.preview_info_var.set("No template image set")

    # ------------------------------------------------------------------
    # Drag: ROI setting (+ auto-capture on first time)
    # ------------------------------------------------------------------

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

        effective_key = self._effective_roi_key(self.current_roi_key)
        is_shared = self.current_roi_key in self.SHARED_ROI

        # For shared entries (level_5, mp_2~mp_8), update the parent ROI
        self.config["roi"][effective_key] = {
            "x": real_x, "y": real_y, "w": real_w, "h": real_h
        }
        # Record DPI scale alongside ROI for auto-adjustment on DPI change
        from gui.window_utils import get_dpi_scale
        scale = get_dpi_scale(self._window_id)
        self.config.setdefault("capture_dpi_scale", {})["roi"] = scale

        coord_type = "window-relative" if self._window_id else "screen"
        shared_note = f" (-> {effective_key})" if is_shared else ""
        self.roi_info_var.set(
            f"{self.ROI_LABELS[self.current_roi_key]}{shared_note}\n"
            f"X={real_x}, Y={real_y}, W={real_w}, H={real_h} ({coord_type})"
        )
        self.manual_vars["x"].set(str(real_x))
        self.manual_vars["y"].set(str(real_y))
        self.manual_vars["w"].set(str(real_w))
        self.manual_vars["h"].set(str(real_h))

        center_updated = self._maybe_set_click_position_from_roi(
            effective_key, self.config["roi"][effective_key]
        )

        # Auto-capture template image ONLY when no template exists yet.
        # For shared entries (template-only), always capture the template
        # since the drag's primary purpose is to capture the template image.
        saved_msg = ""
        if self.screenshot and self.current_roi_key in self.CAPTURABLE_ROIS:
            if is_shared:
                # Shared entries: always capture template (that's the whole point)
                cropped = self.screenshot.crop((
                    real_x, real_y, real_x + real_w, real_y + real_h,
                ))
                self._save_template_image(cropped)
                saved_msg = " + template saved"
            elif self._has_template(self.current_roi_key):
                saved_msg = " (ROI only, template kept)"
            else:
                cropped = self.screenshot.crop((
                    real_x, real_y, real_x + real_w, real_y + real_h,
                ))
                self._save_template_image(cropped)
                saved_msg = " + template saved"

        self._auto_save()
        self._refresh_listbox()
        self._update_preview()
        self.drag_start = None
        self._display_screenshot()
        self.status_var.set(
            f"ROI '{self.current_roi_key}' updated: {real_x},{real_y} "
            f"{real_w}x{real_h}{saved_msg}"
            + (" + click center auto-set" if center_updated else "")
        )

    def _maybe_set_click_position_from_roi(self, roi_key, roi):
        """Auto-fill mapped click position from ROI center if unset."""
        click_key = self.ROI_TO_CLICK_KEY.get(roi_key)
        if not click_key or not roi:
            return False

        click_positions = self.config.setdefault("click_positions", {})
        target = {
            "x": int(roi["x"] + roi["w"] / 2),
            "y": int(roi["y"] + roi["h"] / 2),
        }

        updated = False

        def _set_if_unset(key):
            nonlocal updated
            cur = click_positions.get(key, {"x": 0, "y": 0})
            if cur.get("x", 0) == 0 and cur.get("y", 0) == 0:
                click_positions[key] = dict(target)
                updated = True

        # Existing mapped key
        _set_if_unset(click_key)

        # For empty slot, also initialize the new per-step character slot keys.
        if roi_key == "empty_slot":
            _set_if_unset("enter_character_slot_click")
            _set_if_unset("delete_character_slot_click")

        return updated

    # ------------------------------------------------------------------
    # Manual ROI entry
    # ------------------------------------------------------------------

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

        effective = self._effective_roi_key(self.current_roi_key)
        self.config["roi"][effective] = {"x": x, "y": y, "w": w, "h": h}
        self._auto_save()
        self._refresh_listbox()
        self._display_screenshot()
        self.status_var.set(f"ROI '{effective}' manually set")

    # ------------------------------------------------------------------
    # Template image: replace / load
    # ------------------------------------------------------------------

    def _save_template_image(self, image):
        """Save a captured PIL image as the template for the current ROI key."""
        image_key = self._image_key_for(self.current_roi_key)
        dest = os.path.join(self.images_dir, f"{image_key}.png")
        image.save(dest)
        self.config.setdefault("images", {})[image_key] = dest
        # Record current DPI scale so templates can be auto-resized at
        # runtime if the user changes their display scaling.
        from gui.window_utils import get_dpi_scale
        scale = get_dpi_scale(self._window_id)
        self.config.setdefault("capture_dpi_scale", {})[image_key] = scale

    def _replace_image_from_screenshot(self):
        """Crop the selected ROI from the stored screenshot and save as template."""
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI from the list first")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            messagebox.showinfo("Info", "This ROI is not associated with a template image.")
            return
        if self.screenshot is None:
            messagebox.showwarning("Warning", "Capture the screen first")
            return

        effective = self._effective_roi_key(self.current_roi_key)
        roi = self.config["roi"].get(effective, {})
        if roi.get("w", 0) <= 5 or roi.get("h", 0) <= 5:
            messagebox.showwarning("Warning", "ROI is too small. Drag to set the region first.")
            return

        cropped = self.screenshot.crop((
            roi["x"], roi["y"],
            roi["x"] + roi["w"], roi["y"] + roi["h"],
        ))
        self._save_template_image(cropped)
        self._auto_save()
        self._refresh_listbox()
        self._update_preview()
        self.status_var.set(
            f"Template image replaced from screenshot for '{self.current_roi_key}'"
        )

    def _replace_image_live(self):
        """Capture the ROI region from the live screen and save as template."""
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI from the list first")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            messagebox.showinfo("Info", "This ROI is not associated with a template image.")
            return

        effective = self._effective_roi_key(self.current_roi_key)
        roi = self.config["roi"].get(effective, {})
        if roi.get("w", 0) <= 5 or roi.get("h", 0) <= 5:
            messagebox.showwarning("Warning", "ROI is too small. Set the region first.")
            return

        self.withdraw()
        self.update()
        time.sleep(0.5)

        self._resolve_target_window()
        if not self._window_id:
            self.deiconify()
            messagebox.showerror(
                "Error",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.",
            )
            return
        self._window_rect = get_window_rect(self._window_id)
        if not self._window_rect:
            self.deiconify()
            messagebox.showerror("Error", "Failed to get target window geometry.")
            return
        abs_x = roi["x"] + self._window_rect["x"]
        abs_y = roi["y"] + self._window_rect["y"]

        with mss.mss() as sct:
            monitor = {
                "left": abs_x, "top": abs_y,
                "width": roi["w"], "height": roi["h"],
            }
            grab = sct.grab(monitor)
            cropped = Image.frombytes("RGB", grab.size, grab.rgb)

        self.deiconify()
        self._save_template_image(cropped)
        self._auto_save()
        self._refresh_listbox()
        self._update_preview()
        self.status_var.set(
            f"Template image replaced from live screen for '{self.current_roi_key}'"
        )

    def _load_image_from_file(self):
        """Load an external image file as the template for the selected ROI."""
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI from the list first")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            messagebox.showinfo("Info", "This ROI is not associated with a template image.")
            return

        filepath = filedialog.askopenfilename(
            title=f"Select image for: {self.ROI_LABELS[self.current_roi_key]}",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")],
        )
        if not filepath:
            return

        image_key = self._image_key_for(self.current_roi_key)
        ext = os.path.splitext(filepath)[1]
        dest = os.path.join(self.images_dir, f"{image_key}{ext}")
        shutil.copy2(filepath, dest)
        self.config.setdefault("images", {})[image_key] = dest
        effective = self._effective_roi_key(self.current_roi_key)
        roi = self.config.get("roi", {}).get(effective, {})
        self._maybe_set_click_position_from_roi(self.current_roi_key, roi)

        self._auto_save()
        self._refresh_listbox()
        self._update_preview()
        self.status_var.set(f"Loaded template from file for '{self.current_roi_key}'")

    def _test_template_matching(self):
        """Test template matching for the currently selected ROI in GUI."""
        if self.current_roi_key is None:
            messagebox.showwarning("Warning", "Select a ROI from the list first")
            return
        if self.current_roi_key not in self.CAPTURABLE_ROIS:
            messagebox.showinfo("Info", "This ROI has no template matching target.")
            return

        image_key = self._image_key_for(self.current_roi_key)
        template_path = self.config.get("images", {}).get(image_key, "")
        if not template_path or not os.path.exists(template_path):
            messagebox.showwarning("Warning", f"No template image for '{image_key}'.")
            return

        effective = self._effective_roi_key(self.current_roi_key)
        roi = self.config.get("roi", {}).get(effective, {})
        if roi.get("w", 0) <= 5 or roi.get("h", 0) <= 5:
            messagebox.showwarning("Warning", "ROI is too small. Set the ROI first.")
            return

        self._resolve_target_window()
        if not self._window_id:
            messagebox.showerror("Error", "Target window not found.")
            return

        img, _rect = capture_window(self._window_id)
        if img is None:
            messagebox.showerror("Error", "Failed to capture target window.")
            return

        import cv2
        import numpy as np

        cropped = img.crop((roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]))
        bgr = cv2.cvtColor(np.array(cropped), cv2.COLOR_RGB2BGR)
        threshold = self.config.get("image_thresholds", {}).get(image_key)
        try:
            threshold = float(threshold) if threshold is not None else None
        except (TypeError, ValueError):
            threshold = None
        found, rel_x, rel_y, conf = self.recognizer.find_template(
            bgr, template_path, threshold=threshold
        )
        if found:
            messagebox.showinfo(
                "Matching Test",
                f"Match found!\n"
                f"ROI: {self.current_roi_key}\n"
                f"Position: ({rel_x}, {rel_y}) [ROI-relative]\n"
                f"Confidence: {conf:.3f}",
            )
            self.status_var.set(
                f"Template matched in '{self.current_roi_key}': ({rel_x}, {rel_y}), conf={conf:.3f}"
            )
        else:
            messagebox.showwarning(
                "Matching Test",
                f"No match found.\nROI: {self.current_roi_key}\nBest confidence: {conf:.3f}",
            )
            self.status_var.set(
                f"No match in '{self.current_roi_key}' (best conf={conf:.3f})"
            )


# ======================================================================
# ScreenRegionCapture  (used by ScarecrowEditor and others)
# ======================================================================

class ScreenRegionCapture(tk.Toplevel):
    """Capture a screen region by dragging on the target window.

    Requires a valid window_id.  The callback receives either:
      callback(image, x, y, w, h)   -- when return_coords=True (default)
      callback(image)               -- when return_coords=False (legacy)
    where x, y, w, h are window-relative pixel coordinates of the selected region.
    """

    def __init__(self, parent, window_id=None, callback=None, return_coords=True):
        super().__init__(parent)
        self.callback = callback
        self.return_coords = return_coords
        self.drag_start = None
        self.drag_rect = None
        self._window_id = window_id
        self._window_rect = None
        self.scale_factor = 1.0

        if window_id:
            self._window_rect = get_window_rect(window_id)

        if self._window_rect:
            self._build_window_mode()
        else:
            messagebox.showerror(
                "Error",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.",
            )
            self.after(10, self._cancel)

    def _build_window_mode(self):
        """Capture from target window only (uses PrintWindow on Windows)."""
        img, rect = capture_window(self._window_id)
        if img is None:
            self._cancel()
            return

        self._window_rect = rect
        self.full_image = img

        with mss.mss() as sct:
            scr_w = sct.monitors[1]["width"]
            scr_h = sct.monitors[1]["height"]
        max_w = int(scr_w * 0.85)
        max_h = int(scr_h * 0.85)
        self.scale_factor = min(max_w / img.width, max_h / img.height, 1.0)
        disp_w = int(img.width * self.scale_factor)
        disp_h = int(img.height * self.scale_factor)

        self.title("Drag to select region (ESC to cancel)")
        self.geometry(f"{disp_w}x{disp_h + 40}")
        self.resizable(False, False)

        label = ttk.Label(self,
                          text="Drag to select a region on the target window. ESC to cancel.")
        label.pack(pady=5)

        self.canvas = tk.Canvas(self, width=disp_w, height=disp_h,
                                bg="gray20", cursor="crosshair", highlightthickness=0)
        self.canvas.pack()

        display = img.resize((disp_w, disp_h), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(display)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        self.canvas.bind("<ButtonPress-1>", self._on_start)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_end_window)
        self.bind("<Escape>", lambda e: self._cancel())
        self.focus_set()
        self.grab_set()

    def _on_start(self, event):
        self.drag_start = (event.x, event.y)

    def _on_drag(self, event):
        if self.drag_start is None:
            return
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)
        self.drag_rect = self.canvas.create_rectangle(
            self.drag_start[0], self.drag_start[1], event.x, event.y,
            outline="lime", width=2,
        )

    def _on_end_window(self, event):
        """End drag in window mode - convert scaled coords to pixel coords."""
        if self.drag_start is None:
            return
        x1 = min(self.drag_start[0], event.x)
        y1 = min(self.drag_start[1], event.y)
        x2 = max(self.drag_start[0], event.x)
        y2 = max(self.drag_start[1], event.y)

        px1 = int(x1 / self.scale_factor)
        py1 = int(y1 / self.scale_factor)
        px2 = int(x2 / self.scale_factor)
        py2 = int(y2 / self.scale_factor)

        if px2 - px1 > 5 and py2 - py1 > 5:
            cropped = self.full_image.crop((px1, py1, px2, py2))
            if self.callback:
                if self.return_coords:
                    self.callback(cropped, px1, py1, px2 - px1, py2 - py1)
                else:
                    self.callback(cropped)
        self.destroy()

    def _cancel(self):
        if self.callback:
            if self.return_coords:
                self.callback(None, 0, 0, 0, 0)
            else:
                self.callback(None)
        self.destroy()


# ======================================================================
# Supporting dialogs (unchanged)
# ======================================================================

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

        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10)
        ttk.Button(top_frame, text="Refresh", command=self._refresh_list).pack(side=tk.RIGHT)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.window_listbox = tk.Listbox(list_frame, font=("", 10),
                                         yscrollcommand=scrollbar.set)
        self.window_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.window_listbox.yview)

        self.window_listbox.bind("<Double-1>", lambda e: self._on_select())

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
        "stat_click": "Stat Click Position (4x after verify)",
        "name_input_click": "Name Input Click Position",
        "character_slot_click": "Character Slot Click Position (Legacy Shared)",
        "enter_character_slot_click": "Enter Game Character Slot (Step 7)",
        "delete_character_slot_click": "Delete Character Slot (Step 13)",
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
                      text="No target window configured.\n"
                      "Please set target_window_title in settings first.",
                      foreground="red",
                      wraplength=450).pack(pady=5)

        self.entries = {}
        scroll_frame = ttk.Frame(self)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

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
    """Pick a screen position on the target window."""

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
            messagebox.showerror(
                "Error",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.",
            )
            self.after(10, self.destroy)

    def _build_window_mode(self):
        time.sleep(0.3)
        img, rect = capture_window(self._window_id)
        if img is None:
            self.destroy()
            return

        self._window_rect = rect
        self._capture_img = img

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

    def _on_click_window(self, event):
        win_x = int(event.x / self.scale_factor)
        win_y = int(event.y / self.scale_factor)
        if self.callback:
            self.callback(win_x, win_y)
        self.destroy()
