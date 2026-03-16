"""Image manager GUI for capturing and managing template images."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import mss
import os
import shutil


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
        "level_up_effect": "Level-Up Effect Image",
        "exit_button": "Exit Confirm Button",
        "delete_popup": "Delete Confirmation Popup",
    }

    def __init__(self, parent, config, images_dir="images", on_save=None):
        super().__init__(parent)
        self.title("Image Manager")
        self.config = config
        self.images_dir = images_dir
        self.on_save = on_save
        self.geometry("900x700")

        os.makedirs(images_dir, exist_ok=True)
        self._build_ui()

    def _build_ui(self):
        # Header
        ttk.Label(self, text="Template Image Manager", font=("", 14, "bold")).pack(pady=10)

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
        """Capture a region from screen as template."""
        key = self._get_selected_key()
        if not key:
            return

        self.withdraw()
        self.update()

        capturer = ScreenRegionCapture(
            self, callback=lambda img: self._on_capture(key, img)
        )
        capturer.wait_window()
        self.deiconify()

    def _capture_roi(self):
        """Capture the ROI region for the selected image key."""
        key = self._get_selected_key()
        if not key:
            return

        roi = self.config.get("roi", {}).get(key)
        if not roi or roi.get("w", 0) <= 10:
            messagebox.showwarning("Warning", f"ROI for '{key}' is not configured.\nSet the ROI first.")
            return

        with mss.mss() as sct:
            monitor = {
                "left": roi["x"], "top": roi["y"],
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

    def _on_capture(self, key, img):
        if img is None:
            return
        dest = os.path.join(self.images_dir, f"{key}.png")
        img.save(dest)
        self.config["images"][key] = dest
        self._refresh_list()
        self._show_preview(dest)
        self.preview_info.set(f"Captured: {dest}")

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
    """Fullscreen overlay for capturing a screen region."""

    def __init__(self, parent, callback=None):
        super().__init__(parent)
        self.callback = callback
        self.drag_start = None
        self.drag_rect = None

        # Capture screen first
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            self.full_image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            self.screen_w = monitor["width"]
            self.screen_h = monitor["height"]

        self.attributes("-fullscreen", True)
        self.config(cursor="crosshair")

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.photo = ImageTk.PhotoImage(self.full_image)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # Instructions
        self.canvas.create_text(
            self.screen_w // 2, 30,
            text="Drag to select region. ESC to cancel.",
            fill="yellow", font=("", 16, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_start)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_end)
        self.bind("<Escape>", lambda e: self._cancel())

    def _on_start(self, event):
        self.drag_start = (event.x, event.y)

    def _on_drag(self, event):
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)
        self.drag_rect = self.canvas.create_rectangle(
            self.drag_start[0], self.drag_start[1], event.x, event.y,
            outline="lime", width=2,
        )

    def _on_end(self, event):
        if self.drag_start is None:
            return
        x1 = min(self.drag_start[0], event.x)
        y1 = min(self.drag_start[1], event.y)
        x2 = max(self.drag_start[0], event.x)
        y2 = max(self.drag_start[1], event.y)

        if x2 - x1 > 5 and y2 - y1 > 5:
            cropped = self.full_image.crop((x1, y1, x2, y2))
            if self.callback:
                self.callback(cropped)
        self.destroy()

    def _cancel(self):
        if self.callback:
            self.callback(None)
        self.destroy()
