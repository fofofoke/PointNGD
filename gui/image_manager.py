"""Image manager GUI for capturing and managing template images."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import mss
import os
import shutil
import time

from gui.window_utils import find_windows_by_title, get_window_rect, capture_window


class ImageManager(tk.Toplevel):
    """GUI for managing template images used in automation."""

    IMAGE_LABELS = {
        "empty_slot": "Empty Character Slot",
        "knight_icon": "Knight Class Icon",
        "knight_verify": "Knight Verification Image",
        "confirm_button": "Confirm/OK Button",
        "item_icon": "Item Icon (Inventory)",
        "popup_text": "Popup Text Image",
        "scarecrow": "Scarecrow Image",
        "exit_button": "Exit Confirm Button",
        "delete_popup": "Delete Confirmation Popup",
        "death_screen": "Death Screen Image (HP=0)",
        "revival_button": "Revival Button Image",
    }

    def __init__(self, parent, config, images_dir="images", on_save=None):
        super().__init__(parent)
        self.title("Image Manager")
        self.config = config
        self.images_dir = images_dir
        self.on_save = on_save
        self._window_id = None
        self._window_rect = None
        self._resolve_target_window()
        self.geometry("900x700")

        os.makedirs(images_dir, exist_ok=True)
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
        # Header
        ttk.Label(self, text="Template Image Manager", font=("", 14, "bold")).pack(pady=10)

        # Window info
        win_title = self.config.get("target_window_title", "")
        if win_title:
            status = "Found" if self._window_id else "NOT FOUND"
            ttk.Label(self,
                      text=f"Target: {win_title} [{status}]",
                      foreground="green" if self._window_id else "red").pack(pady=2)

        # Main content
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left: image list
        left_frame = ttk.Frame(main_frame, width=350)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        left_frame.pack_propagate(False)

        self.image_listbox = tk.Listbox(left_frame, font=("", 10))
        self.image_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        self.image_listbox.bind("<<ListboxSelect>>", self._on_select)

        self._refresh_list()

        # Buttons
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="Load from File", command=self._load_from_file).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Capture from Screen", command=self._capture_from_screen).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Capture ROI Region", command=self._capture_roi).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Clear Selected", command=self._clear_selected).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Save All", command=self._save_all).pack(fill=tk.X, pady=2)

        # Right: preview
        right_frame = ttk.LabelFrame(main_frame, text="Preview")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        self.preview_canvas = tk.Canvas(right_frame, bg="gray30")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.preview_info = tk.StringVar(value="Select an image to preview")
        ttk.Label(right_frame, textvariable=self.preview_info).pack(pady=5)

        self.preview_photo = None

    def _refresh_list(self):
        self.image_listbox.delete(0, tk.END)
        for key, label in self.IMAGE_LABELS.items():
            path = self.config["images"].get(key, "")
            status = "SET" if path and os.path.exists(path) else "---"
            self.image_listbox.insert(tk.END, f"[{status}] {label}")

    def _get_selected_key(self):
        selection = self.image_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select an image from the list first")
            return None
        idx = selection[0]
        return list(self.IMAGE_LABELS.keys())[idx]

    def _on_select(self, event):
        key = self._get_selected_key()
        if not key:
            return
        path = self.config["images"].get(key, "")
        if path and os.path.exists(path):
            self._show_preview(path)
            self.preview_info.set(f"{self.IMAGE_LABELS[key]}\n{path}")
        else:
            self.preview_canvas.delete("all")
            self.preview_info.set(f"{self.IMAGE_LABELS[key]}\nNo image set")

    def _show_preview(self, path):
        try:
            img = Image.open(path)
            canvas_w = self.preview_canvas.winfo_width() or 400
            canvas_h = self.preview_canvas.winfo_height() or 400
            scale = min(canvas_w / img.width, canvas_h / img.height, 1.0)
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(new_size, Image.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(img)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                canvas_w // 2, canvas_h // 2, anchor=tk.CENTER, image=self.preview_photo
            )
        except Exception as e:
            self.preview_info.set(f"Error loading image: {e}")

    def _load_from_file(self):
        key = self._get_selected_key()
        if not key:
            return
        filepath = filedialog.askopenfilename(
            title=f"Select image for: {self.IMAGE_LABELS[key]}",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")],
        )
        if filepath:
            # Copy to images directory
            ext = os.path.splitext(filepath)[1]
            dest = os.path.join(self.images_dir, f"{key}{ext}")
            shutil.copy2(filepath, dest)
            self.config["images"][key] = dest
            self._refresh_list()
            self._show_preview(dest)
            self.preview_info.set(f"Loaded: {dest}")

    def _capture_from_screen(self):
        """Capture a region from target window as template + auto-set ROI."""
        key = self._get_selected_key()
        if not key:
            return

        # Re-resolve target window
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

        capturer = ScreenRegionCapture(
            self,
            window_id=self._window_id,
            callback=lambda img, x, y, w, h: self._on_capture(key, img, x, y, w, h),
            return_coords=True,
        )
        capturer.wait_window()
        self.deiconify()

    def _capture_roi(self):
        """Capture the ROI region for the selected image key."""
        key = self._get_selected_key()
        if not key:
            return

        # Check for matching ROI key
        roi_key = self.IMAGE_TO_ROI_MAP.get(key, key)
        roi = self.config.get("roi", {}).get(roi_key)
        if not roi or roi.get("w", 0) <= 10:
            messagebox.showwarning("Warning", f"ROI for '{roi_key}' is not configured.\nSet the ROI first.")
            return

        # Require target window
        self._resolve_target_window()
        if not self._window_id:
            messagebox.showerror(
                "Error",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.",
            )
            return

        rect = get_window_rect(self._window_id)
        if not rect:
            messagebox.showerror("Error", "Failed to get target window geometry.")
            return

        abs_x = roi["x"] + rect["x"]
        abs_y = roi["y"] + rect["y"]

        with mss.mss() as sct:
            monitor = {
                "left": abs_x, "top": abs_y,
                "width": roi["w"], "height": roi["h"],
            }
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

        dest = os.path.join(self.images_dir, f"{key}.png")
        img.save(dest)
        self.config["images"][key] = dest
        self._refresh_list()
        self._show_preview(dest)
        self.preview_info.set(f"Captured from ROI: {dest}")

    # Mapping from image key to ROI key (reverse of ROIEditor's map)
    IMAGE_TO_ROI_MAP = {
        "empty_slot": "empty_slot",
        "knight_icon": "knight_icon",
        "knight_verify": "knight_verify",
        "confirm_button": "confirm_button",
        "item_icon": "item_slot",
        "popup_text": "popup_text",
        "scarecrow": "scarecrow_search",
        "exit_button": "exit_button",
        "delete_popup": "delete_popup",
    }

    def _on_capture(self, key, img, x=0, y=0, w=0, h=0):
        if img is None:
            return
        dest = os.path.join(self.images_dir, f"{key}.png")
        img.save(dest)
        self.config["images"][key] = dest

        # Auto-set ROI from the captured region coordinates
        roi_key = self.IMAGE_TO_ROI_MAP.get(key)
        roi_msg = ""
        if roi_key and w > 5 and h > 5:
            self.config.setdefault("roi", {})[roi_key] = {
                "x": x, "y": y, "w": w, "h": h,
            }
            roi_msg = f" + ROI '{roi_key}' set ({x},{y} {w}x{h})"

        self._refresh_list()
        self._show_preview(dest)
        self.preview_info.set(f"Captured: {dest}{roi_msg}")

    def _clear_selected(self):
        key = self._get_selected_key()
        if not key:
            return
        self.config["images"][key] = ""
        self._refresh_list()
        self.preview_canvas.delete("all")
        self.preview_info.set("Image cleared")

    def _save_all(self):
        if self.on_save:
            self.on_save(self.config)
        messagebox.showinfo("Saved", "Image settings saved!")


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
            # No target window -- cannot proceed
            messagebox.showerror(
                "Error",
                "Target window not found.\n"
                "Please set target_window_title in settings and ensure the window is open.",
            )
            self.after(10, self._cancel)

    def _build_window_mode(self):
        """Capture from target window only."""
        time.sleep(0.3)
        img, rect = capture_window(self._window_id)
        if img is None:
            self._cancel()
            return

        self._window_rect = rect
        self.full_image = img

        # Size the window to fit image (max 85% of screen)
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

        # Convert canvas coords to actual pixel coords (window-relative)
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
