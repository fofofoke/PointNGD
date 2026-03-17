"""Scarecrow detection editor: multi-direction templates + HSV color tuning."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import os
import shutil

from core.image_recognition import ImageRecognition
from gui.window_utils import find_windows_by_title, get_window_rect


class ScarecrowEditor(tk.Toplevel):
    """GUI for managing scarecrow multi-direction templates and HSV filter."""

    def __init__(self, parent, config, images_dir="images", on_save=None):
        super().__init__(parent)
        self.title("Scarecrow Detection Editor")
        self.config = config
        self.images_dir = images_dir
        self.on_save = on_save
        self.recognizer = ImageRecognition()
        self._window_id = None
        self._window_rect = None
        self._resolve_target_window()
        self.geometry("1000x750")

        os.makedirs(images_dir, exist_ok=True)
        self._build_ui()
        self._load_from_config()

    def _resolve_target_window(self):
        title = self.config.get("target_window_title", "")
        if not title:
            return
        windows = find_windows_by_title(title)
        if windows:
            self._window_id = windows[0][0]
            self._window_rect = get_window_rect(self._window_id)

    def _abs_roi(self, roi):
        """Convert window-relative ROI to absolute screen ROI."""
        if not roi:
            return roi
        result = dict(roi)
        if self._window_id:
            rect = get_window_rect(self._window_id)
            if rect:
                result["x"] = roi["x"] + rect["x"]
                result["y"] = roi["y"] + rect["y"]
        return result

    def _build_ui(self):
        # === Top: title ===
        ttk.Label(self, text="Scarecrow Detection Settings",
                  font=("", 14, "bold")).pack(pady=5)

        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # === Left panel: Multi-direction templates ===
        left_frame = ttk.LabelFrame(main_pane, text="Multi-Direction Templates")
        main_pane.add(left_frame, weight=1)

        ttk.Label(left_frame,
                  text="Add scarecrow images for each direction.\n"
                  "All templates are tried; best match wins.",
                  wraplength=350).pack(padx=5, pady=5)

        # Template listbox
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tmpl_listbox = tk.Listbox(list_frame, font=("", 10), height=10)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tmpl_listbox.yview)
        self.tmpl_listbox.config(yscrollcommand=scrollbar.set)
        self.tmpl_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tmpl_listbox.bind("<<ListboxSelect>>", self._on_template_select)

        # Template buttons
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(btn_frame, text="Add from File",
                   command=self._add_from_file).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="Capture from Screen",
                   command=self._add_from_screen).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="Capture from ROI",
                   command=self._add_from_roi).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="Remove Selected",
                   command=self._remove_selected).pack(fill=tk.X, pady=1)

        # Template preview
        self.tmpl_preview_frame = ttk.LabelFrame(left_frame, text="Preview")
        self.tmpl_preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.tmpl_preview_canvas = tk.Canvas(self.tmpl_preview_frame, bg="gray30",
                                             height=120)
        self.tmpl_preview_canvas.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        self.tmpl_preview_photo = None

        # === Right panel: HSV color filter ===
        right_frame = ttk.LabelFrame(main_pane, text="HSV Color Filter")
        main_pane.add(right_frame, weight=1)

        # Enable checkbox
        self.hsv_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right_frame, text="Enable HSV Color Filter",
                        variable=self.hsv_enabled_var).pack(anchor=tk.W, padx=10, pady=5)

        ttk.Label(right_frame,
                  text="Filters the search area by color before template matching.\n"
                  "Also used as fallback if no template matches.",
                  wraplength=400).pack(padx=10, pady=2)

        # HSV sliders
        slider_frame = ttk.Frame(right_frame)
        slider_frame.pack(fill=tk.X, padx=10, pady=5)

        self.hsv_vars = {}
        hsv_params = [
            ("H Min:", "h_min", 0, 180, 10),
            ("H Max:", "h_max", 0, 180, 30),
            ("S Min:", "s_min", 0, 255, 50),
            ("S Max:", "s_max", 0, 255, 255),
            ("V Min:", "v_min", 0, 255, 50),
            ("V Max:", "v_max", 0, 255, 255),
        ]
        for i, (label, key, from_, to_, default) in enumerate(hsv_params):
            ttk.Label(slider_frame, text=label).grid(row=i, column=0, sticky=tk.W, padx=2)
            var = tk.IntVar(value=default)
            scale = ttk.Scale(slider_frame, from_=from_, to=to_, variable=var,
                              orient=tk.HORIZONTAL, length=200,
                              command=lambda v, k=key: self._on_hsv_change(k))
            scale.grid(row=i, column=1, padx=5, pady=2, sticky=tk.EW)
            val_label = ttk.Label(slider_frame, textvariable=var, width=4)
            val_label.grid(row=i, column=2, padx=2)
            self.hsv_vars[key] = var

        slider_frame.columnconfigure(1, weight=1)

        # HSV helper buttons
        hsv_btn_frame = ttk.Frame(right_frame)
        hsv_btn_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(hsv_btn_frame, text="Auto-detect from ROI",
                   command=self._auto_detect_hsv).pack(fill=tk.X, pady=1)
        ttk.Button(hsv_btn_frame, text="Preview Filter",
                   command=self._preview_hsv).pack(fill=tk.X, pady=1)
        ttk.Button(hsv_btn_frame, text="Test Detection",
                   command=self._test_detection).pack(fill=tk.X, pady=1)

        # HSV preview
        self.hsv_preview_frame = ttk.LabelFrame(right_frame, text="HSV Preview")
        self.hsv_preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.hsv_preview_canvas = tk.Canvas(self.hsv_preview_frame, bg="gray30",
                                            height=200)
        self.hsv_preview_canvas.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        self.hsv_preview_photo = None

        self.hsv_info_var = tk.StringVar(value="")
        ttk.Label(self.hsv_preview_frame, textvariable=self.hsv_info_var).pack(pady=2)

        # === Bottom: Save ===
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bottom, text="Save All", command=self._save_all).pack(side=tk.RIGHT)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var).pack(side=tk.BOTTOM, fill=tk.X)

    def _load_from_config(self):
        """Load existing settings into UI."""
        templates = self.config.get("scarecrow_templates", [])
        for path in templates:
            name = os.path.basename(path) if path else "(empty)"
            self.tmpl_listbox.insert(tk.END, name)

        hsv = self.config.get("scarecrow_hsv", {})
        self.hsv_enabled_var.set(hsv.get("enabled", False))
        for key, var in self.hsv_vars.items():
            var.set(hsv.get(key, var.get()))

    def _get_templates_list(self):
        """Get current template paths from config."""
        return list(self.config.get("scarecrow_templates", []))

    def _on_template_select(self, event):
        selection = self.tmpl_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        templates = self._get_templates_list()
        if idx < len(templates):
            self._show_template_preview(templates[idx])

    def _show_template_preview(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            img = Image.open(path)
            cw = self.tmpl_preview_canvas.winfo_width() or 300
            ch = self.tmpl_preview_canvas.winfo_height() or 120
            scale = min(cw / img.width, ch / img.height, 1.0)
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))), Image.LANCZOS)
            self.tmpl_preview_photo = ImageTk.PhotoImage(img)
            self.tmpl_preview_canvas.delete("all")
            self.tmpl_preview_canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER,
                                                  image=self.tmpl_preview_photo)
        except Exception:
            pass

    def _add_template(self, img_or_path):
        """Add a template image. Accepts PIL Image or file path string."""
        templates = self._get_templates_list()
        idx = len(templates) + 1

        if isinstance(img_or_path, str):
            ext = os.path.splitext(img_or_path)[1]
            dest = os.path.join(self.images_dir, f"scarecrow_dir{idx}{ext}")
            shutil.copy2(img_or_path, dest)
        else:
            dest = os.path.join(self.images_dir, f"scarecrow_dir{idx}.png")
            img_or_path.save(dest)

        templates.append(dest)
        self.config["scarecrow_templates"] = templates
        self.tmpl_listbox.insert(tk.END, os.path.basename(dest))
        self.status_var.set(f"Added template #{idx}: {os.path.basename(dest)}")

    def _add_from_file(self):
        files = filedialog.askopenfilenames(
            title="Select scarecrow template image(s)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")],
        )
        for f in files:
            self._add_template(f)

    def _add_from_screen(self):
        self.withdraw()
        self.update()
        from gui.roi_editor import ScreenRegionCapture
        capturer = ScreenRegionCapture(
            self,
            window_id=self._window_id,
            callback=self._on_screen_capture,
            return_coords=False,
        )
        capturer.wait_window()
        self.deiconify()

    def _on_screen_capture(self, img):
        if img is not None:
            self._add_template(img)

    def _add_from_roi(self):
        roi = self.config.get("roi", {}).get("scarecrow_search")
        if not roi or roi.get("w", 0) <= 10:
            messagebox.showwarning("Warning",
                                   "Set the 'Scarecrow Search Area' ROI first.")
            return
        import mss
        import time
        self.withdraw()
        self.update()
        time.sleep(0.5)

        # Convert window-relative ROI to absolute for capture
        abs_roi = self._abs_roi(roi)
        with mss.mss() as sct:
            monitor = {"left": abs_roi["x"], "top": abs_roi["y"],
                       "width": abs_roi["w"], "height": abs_roi["h"]}
            grab = sct.grab(monitor)
            img = Image.frombytes("RGB", grab.size, grab.rgb)
        self.deiconify()

        # Let user crop the scarecrow from the captured ROI
        messagebox.showinfo("Info",
                            "The full ROI was captured.\n"
                            "Now drag to select just the scarecrow in the next screen.")
        self.withdraw()
        from gui.roi_editor import ScreenRegionCapture
        capturer = ScreenRegionCapture(
            self,
            window_id=self._window_id,
            callback=self._on_screen_capture,
            return_coords=False,
        )
        capturer.wait_window()
        self.deiconify()

    def _remove_selected(self):
        selection = self.tmpl_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        templates = self._get_templates_list()
        if idx < len(templates):
            templates.pop(idx)
            self.config["scarecrow_templates"] = templates
            self.tmpl_listbox.delete(idx)
            self.tmpl_preview_canvas.delete("all")
            self.status_var.set(f"Removed template #{idx + 1}")

    def _get_hsv_range(self):
        return {key: var.get() for key, var in self.hsv_vars.items()}

    def _on_hsv_change(self, key):
        pass  # Could auto-preview, but may be too slow

    def _auto_detect_hsv(self):
        """Sample HSV from scarecrow search ROI and suggest range."""
        roi = self.config.get("roi", {}).get("scarecrow_search")
        if not roi or roi.get("w", 0) <= 10:
            messagebox.showwarning("Warning", "Set scarecrow search ROI first.")
            return

        messagebox.showinfo("Info",
                            "Position the game so the scarecrow is visible in the ROI area,\n"
                            "then click OK. The median color will be sampled.")

        abs_roi = self._abs_roi(roi)
        # Hide editor so we capture the target window, not ourselves
        self.withdraw()
        self.update()
        import time; time.sleep(0.3)
        result = self.recognizer.sample_hsv_from_region(abs_roi)
        self.deiconify()
        self.hsv_vars["h_min"].set(result["h_min"])
        self.hsv_vars["h_max"].set(result["h_max"])
        self.hsv_vars["s_min"].set(result["s_min"])
        self.hsv_vars["s_max"].set(result["s_max"])
        self.hsv_vars["v_min"].set(result["v_min"])
        self.hsv_vars["v_max"].set(result["v_max"])

        self.hsv_info_var.set(
            f"Detected median HSV: ({result['h_median']}, "
            f"{result['s_median']}, {result['v_median']})"
        )
        self.status_var.set("HSV auto-detected. Adjust sliders and preview to fine-tune.")

    def _preview_hsv(self):
        """Show HSV filter preview on the scarecrow search ROI."""
        roi = self.config.get("roi", {}).get("scarecrow_search")
        if not roi or roi.get("w", 0) <= 10:
            messagebox.showwarning("Warning", "Set scarecrow search ROI first.")
            return

        abs_roi = self._abs_roi(roi)
        hsv_range = self._get_hsv_range()
        # Hide editor so we capture the target window, not ourselves
        self.withdraw()
        self.update()
        import time; time.sleep(0.3)
        masked_img, pixel_count = self.recognizer.preview_hsv_mask(abs_roi, hsv_range)
        self.deiconify()

        cw = self.hsv_preview_canvas.winfo_width() or 400
        ch = self.hsv_preview_canvas.winfo_height() or 200
        scale = min(cw / masked_img.width, ch / masked_img.height, 1.0)
        resized = masked_img.resize(
            (max(1, int(masked_img.width * scale)),
             max(1, int(masked_img.height * scale))), Image.LANCZOS)
        self.hsv_preview_photo = ImageTk.PhotoImage(resized)
        self.hsv_preview_canvas.delete("all")
        self.hsv_preview_canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER,
                                             image=self.hsv_preview_photo)

        total = roi["w"] * roi["h"]
        pct = (pixel_count / total * 100) if total > 0 else 0
        self.hsv_info_var.set(f"Matching pixels: {pixel_count} ({pct:.1f}% of ROI)")

    def _test_detection(self):
        """Run full scarecrow detection and show result."""
        roi = self.config.get("roi", {}).get("scarecrow_search")
        if not roi or roi.get("w", 0) <= 10:
            messagebox.showwarning("Warning", "Set scarecrow search ROI first.")
            return

        templates = self._get_templates_list()
        # Include legacy
        legacy = self.config.get("images", {}).get("scarecrow", "")
        if legacy and legacy not in templates:
            templates = [legacy] + templates

        hsv_range = self._get_hsv_range() if self.hsv_enabled_var.get() else None

        abs_roi = self._abs_roi(roi)
        # Hide editor so we capture the target window, not ourselves
        self.withdraw()
        self.update()
        import time; time.sleep(0.3)
        found, ax, ay, conf, idx = self.recognizer.find_scarecrow(
            abs_roi, templates, hsv_range
        )
        self.deiconify()

        if found:
            method = f"template #{idx+1}" if idx >= 0 else "HSV fallback"
            # Convert absolute coords back to window-relative for display
            disp_x, disp_y = ax, ay
            if self._window_id and self._window_rect:
                disp_x -= self._window_rect.get("x", 0)
                disp_y -= self._window_rect.get("y", 0)
            self.status_var.set(
                f"FOUND at ({disp_x}, {disp_y}), confidence={conf:.3f}, method={method}"
            )
            messagebox.showinfo("Test Result",
                                f"Scarecrow found!\n"
                                f"Position: ({disp_x}, {disp_y}) [window-relative]\n"
                                f"Confidence: {conf:.3f}\n"
                                f"Method: {method}")
        else:
            self.status_var.set(f"NOT FOUND (best conf={conf:.3f})")
            messagebox.showwarning("Test Result",
                                   f"Scarecrow NOT found.\n"
                                   f"Best confidence: {conf:.3f}\n"
                                   f"Try adding more templates or adjusting HSV range.")

    def _save_all(self):
        # Save HSV settings
        hsv = self._get_hsv_range()
        hsv["enabled"] = self.hsv_enabled_var.get()
        self.config["scarecrow_hsv"] = hsv

        if self.on_save:
            self.on_save(self.config)

        self.status_var.set("Saved!")
        messagebox.showinfo("Saved", "Scarecrow detection settings saved!")
