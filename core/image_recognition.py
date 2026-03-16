"""Image recognition engine: template matching, OCR, and screen capture."""
import cv2
import numpy as np
from PIL import Image
import mss
import os

try:
    import pytesseract
except ImportError:
    pytesseract = None


class ImageRecognition:
    """Handles screen capture, template matching, and OCR."""

    def __init__(self):
        self.sct = mss.mss()
        self.match_threshold = 0.8

    def capture_screen(self, region=None):
        """Capture screen or a specific region.
        region: dict with x, y, w, h keys or None for full screen.
        Returns numpy array (BGR).
        """
        if region:
            monitor = {
                "left": region["x"],
                "top": region["y"],
                "width": region["w"],
                "height": region["h"],
            }
        else:
            monitor = self.sct.monitors[1]

        screenshot = self.sct.grab(monitor)
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def capture_screen_pil(self, region=None):
        """Capture screen and return as PIL Image."""
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

    def check_level_by_image(self, template_path, region=None):
        """Check if level-up effect is visible on screen."""
        if region:
            screen = self.capture_screen(region)
        else:
            screen = self.capture_screen()
        found, _, _, conf = self.find_template(screen, template_path)
        return found

    def save_region_as_template(self, region, save_path):
        """Capture a screen region and save as a template image."""
        screen = self.capture_screen(region)
        cv2.imwrite(save_path, screen)
        return save_path

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
