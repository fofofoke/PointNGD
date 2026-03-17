"""Image recognition engine: template matching, OCR, and screen capture."""
import cv2
import numpy as np
try:
    from PIL import Image
except ImportError:
    Image = None
import mss
import os

try:
    import pytesseract
except ImportError:
    pytesseract = None


class ImageRecognition:
    """Handles screen capture, template matching, and OCR."""

    def __init__(self):
        self.match_threshold = 0.8

    def capture_screen(self, region=None):
        """Capture screen or a specific region.
        region: dict with x, y, w, h keys or None for full screen.
        Returns numpy array (BGR).

        Creates a fresh mss instance each call to avoid thread-local DC
        errors when called from a worker thread different from the one
        that created the previous instance.
        """
        with mss.mss() as sct:
            if region:
                monitor = {
                    "left": region["x"],
                    "top": region["y"],
                    "width": region["w"],
                    "height": region["h"],
                }
            else:
                monitor = sct.monitors[1]

            screenshot = sct.grab(monitor)
            img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def capture_screen_pil(self, region=None):
        """Capture screen and return as PIL Image."""
        if Image is None:
            raise ImportError("Pillow is required: pip install Pillow")
        bgr = self.capture_screen(region)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def find_template(self, screen_img, template_path, threshold=None):
        """Find template image in screen image.
        Returns (found, center_x, center_y, confidence) or (False, 0, 0, 0).
        """
        if not os.path.exists(template_path):
            return False, 0, 0, 0

        threshold = threshold or self.match_threshold
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return False, 0, 0, 0

        result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = template.shape[:2]
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return True, center_x, center_y, max_val

        return False, 0, 0, max_val

    def find_template_in_region(self, template_path, region, threshold=None):
        """Find template within a specific screen region.
        Returns (found, abs_x, abs_y, confidence).
        """
        screen = self.capture_screen(region)
        found, rel_x, rel_y, conf = self.find_template(screen, template_path, threshold)
        if found:
            abs_x = region["x"] + rel_x
            abs_y = region["y"] + rel_y
            return True, abs_x, abs_y, conf
        return False, 0, 0, conf

    def find_all_templates(self, screen_img, template_path, threshold=None):
        """Find all occurrences of template in screen image.
        Returns list of (center_x, center_y, confidence).
        """
        if not os.path.exists(template_path):
            return []

        threshold = threshold or self.match_threshold
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return []

        result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)
        h, w = template.shape[:2]

        matches = []
        for pt in zip(*locations[::-1]):
            cx = pt[0] + w // 2
            cy = pt[1] + h // 2
            matches.append((cx, cy, result[pt[1], pt[0]]))

        # Remove overlapping detections (NMS-like)
        filtered = []
        for m in sorted(matches, key=lambda x: -x[2]):
            overlap = False
            for f in filtered:
                if abs(m[0] - f[0]) < w // 2 and abs(m[1] - f[1]) < h // 2:
                    overlap = True
                    break
            if not overlap:
                filtered.append(m)

        return filtered

    def ocr_region(self, region, config="--psm 7 --oem 3"):
        """OCR a specific screen region. Returns recognized text."""
        if pytesseract is None:
            return ""
        screen = self.capture_screen(region)
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        # Apply thresholding for better OCR
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(thresh, config=config).strip()
        return text

    def ocr_number(self, region):
        """OCR a region and extract a number. Returns int or None."""
        text = self.ocr_region(region, config="--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789")
        digits = "".join(c for c in text if c.isdigit())
        if digits:
            return int(digits)
        return None

    def save_region_as_template(self, region, save_path):
        """Capture a screen region and save as a template image."""
        screen = self.capture_screen(region)
        cv2.imwrite(save_path, screen)
        return save_path

    # --- Scarecrow multi-direction + HSV color detection ---

    def find_scarecrow(self, region, templates, hsv_range=None, threshold=None,
                       origin=None, image=None):
        """Find scarecrow using HSV color filter + multi-template matching.

        Matches are sorted by distance from origin (closest first).
        If origin is None, the center of the region is used.

        Args:
            region: ROI dict {x, y, w, h} to search in.
            templates: List of template image paths (different directions).
            hsv_range: Optional dict for HSV color pre-filtering.
            threshold: Match confidence threshold.
            origin: Optional dict {"x": int, "y": int} - reference point
                    (e.g. character position). Matches are sorted closest first.
            image: Optional pre-captured BGR numpy array.  When supplied the
                   region is only used for coordinate math, not for capture.

        Returns:
            (found, abs_x, abs_y, best_confidence, matched_template_index)
        """
        threshold = threshold or self.match_threshold
        screen = image if image is not None else self.capture_screen(region)

        # Origin in region-local coordinates
        if origin:
            ox = origin["x"] - region["x"]
            oy = origin["y"] - region["y"]
        else:
            ox = region["w"] // 2
            oy = region["h"] // 2

        # Phase 1: HSV color filtering to create candidate mask
        hsv_mask = None
        if hsv_range:
            hsv_mask = self._create_hsv_mask(screen, hsv_range)
            if cv2.countNonZero(hsv_mask) < 50:
                return False, 0, 0, 0, -1

        # Phase 2: Collect ALL matches from all templates above threshold
        all_matches = []  # (rel_x, rel_y, confidence, template_idx)

        for idx, tmpl_path in enumerate(templates):
            if not tmpl_path or not os.path.exists(tmpl_path):
                continue
            template = cv2.imread(tmpl_path, cv2.IMREAD_COLOR)
            if template is None:
                continue

            search_img = screen
            if hsv_mask is not None:
                search_img = cv2.bitwise_and(screen, screen, mask=hsv_mask)

            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            h, w = template.shape[:2]

            # Find all locations above threshold
            locations = np.where(result >= threshold)
            for pt in zip(*locations[::-1]):
                cx = pt[0] + w // 2
                cy = pt[1] + h // 2
                conf = float(result[pt[1], pt[0]])
                all_matches.append((cx, cy, conf, idx))

        # NMS: remove overlapping detections, keep higher confidence
        filtered = []
        for m in sorted(all_matches, key=lambda x: -x[2]):
            overlap = False
            for f in filtered:
                if abs(m[0] - f[0]) < 30 and abs(m[1] - f[1]) < 30:
                    overlap = True
                    break
            if not overlap:
                filtered.append(m)

        if filtered:
            # Sort by distance from origin (closest first)
            filtered.sort(key=lambda m: (m[0] - ox) ** 2 + (m[1] - oy) ** 2)

            best = filtered[0]
            abs_x = region["x"] + best[0]
            abs_y = region["y"] + best[1]
            return True, abs_x, abs_y, best[2], best[3]

        # Phase 3: Fallback - if templates fail, use HSV centroids sorted by distance
        if hsv_mask is not None:
            found, cx, cy = self._find_hsv_closest(hsv_mask, ox, oy, min_area=100)
            if found:
                abs_x = region["x"] + cx
                abs_y = region["y"] + cy
                return True, abs_x, abs_y, 0.5, -1

        best_conf = max((m[2] for m in all_matches), default=0.0)
        return False, 0, 0, best_conf, -1

    def _find_hsv_closest(self, mask, origin_x, origin_y, min_area=100):
        """Find the centroid of the contour closest to the origin point.
        Returns (found, center_x, center_y).
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False, 0, 0

        candidates = []
        for c in contours:
            if cv2.contourArea(c) < min_area:
                continue
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            dist = (cx - origin_x) ** 2 + (cy - origin_y) ** 2
            candidates.append((cx, cy, dist))

        if not candidates:
            return False, 0, 0

        candidates.sort(key=lambda x: x[2])
        return True, candidates[0][0], candidates[0][1]

    def _create_hsv_mask(self, bgr_img, hsv_range):
        """Create a binary mask from HSV color range."""
        hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
        lower = np.array([
            hsv_range.get("h_min", 0),
            hsv_range.get("s_min", 0),
            hsv_range.get("v_min", 0),
        ])
        upper = np.array([
            hsv_range.get("h_max", 180),
            hsv_range.get("s_max", 255),
            hsv_range.get("v_max", 255),
        ])
        mask = cv2.inRange(hsv, lower, upper)
        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask

    def _find_hsv_centroid(self, mask, min_area=100):
        """Find the centroid of the largest contour in a binary mask.
        Returns (found, center_x, center_y).
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False, 0, 0

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < min_area:
            return False, 0, 0

        M = cv2.moments(largest)
        if M["m00"] == 0:
            return False, 0, 0

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        return True, cx, cy

    def sample_hsv_from_region(self, region, image=None):
        """Capture a region and return the median HSV values + suggested range.
        Useful for GUI to help user pick HSV range for scarecrow color.
        Returns dict with h_median, s_median, v_median and suggested min/max.

        If *image* (BGR numpy array) is provided, it is used directly instead
        of capturing the screen.
        """
        screen = image if image is not None else self.capture_screen(region)
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        h_med = int(np.median(hsv[:, :, 0]))
        s_med = int(np.median(hsv[:, :, 1]))
        v_med = int(np.median(hsv[:, :, 2]))
        return {
            "h_median": h_med, "s_median": s_med, "v_median": v_med,
            "h_min": max(0, h_med - 15), "h_max": min(180, h_med + 15),
            "s_min": max(0, s_med - 50), "s_max": min(255, s_med + 50),
            "v_min": max(0, v_med - 50), "v_max": min(255, v_med + 50),
        }

    def preview_hsv_mask(self, region, hsv_range, image=None):
        """Capture region, apply HSV filter, return masked image as PIL for preview.

        If *image* (BGR numpy array) is provided, it is used directly instead
        of capturing the screen.
        """
        if Image is None:
            raise ImportError("Pillow is required: pip install Pillow")
        screen = image if image is not None else self.capture_screen(region)
        mask = self._create_hsv_mask(screen, hsv_range)
        masked = cv2.bitwise_and(screen, screen, mask=mask)
        rgb = cv2.cvtColor(masked, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb), cv2.countNonZero(mask)

    def check_hp_bar(self, region, red_threshold=None):
        """Check HP bar by analyzing red pixel ratio in the region.

        HP bars in Lineage are typically red. When HP is low/zero,
        the red pixel ratio drops significantly.

        Args:
            region: ROI dict {x, y, w, h} for the HP bar area.
            red_threshold: Dict with HSV range for "red" color detection.
                          Defaults to typical game HP bar red.

        Returns:
            dict with:
                - hp_ratio: float 0.0~1.0 (ratio of red pixels to total)
                - is_dead: bool (True if hp_ratio < 0.05)
                - pixel_count: int (number of red pixels found)
        """
        if not region or region.get("w", 0) <= 5:
            return {"hp_ratio": 1.0, "is_dead": False, "pixel_count": 0}

        screen = self.capture_screen(region)
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)

        if red_threshold is None:
            # Red wraps around in HSV (0-10 and 170-180)
            lower_red1 = np.array([0, 80, 80])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([170, 80, 80])
            upper_red2 = np.array([180, 255, 255])
            mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            mask = cv2.bitwise_or(mask1, mask2)
        else:
            lower = np.array([
                red_threshold.get("h_min", 0),
                red_threshold.get("s_min", 80),
                red_threshold.get("v_min", 80),
            ])
            upper = np.array([
                red_threshold.get("h_max", 10),
                red_threshold.get("s_max", 255),
                red_threshold.get("v_max", 255),
            ])
            mask = cv2.inRange(hsv, lower, upper)

        pixel_count = cv2.countNonZero(mask)
        total = region["w"] * region["h"]
        hp_ratio = pixel_count / total if total > 0 else 0

        return {
            "hp_ratio": hp_ratio,
            "is_dead": hp_ratio < 0.05,
            "pixel_count": pixel_count,
        }

    def compare_images(self, img1_path, img2_path):
        """Compare two images and return similarity score (0-1)."""
        img1 = cv2.imread(img1_path)
        img2 = cv2.imread(img2_path)
        if img1 is None or img2 is None:
            return 0.0
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        result = cv2.matchTemplate(img1, img2, cv2.TM_CCOEFF_NORMED)
        return float(result[0][0])
