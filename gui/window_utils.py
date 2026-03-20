"""Utility for finding and capturing a target window by title."""
import sys
import subprocess
import logging

logger = logging.getLogger(__name__)

try:
    import mss
except ImportError:
    mss = None
    logger.warning("mss not installed. Window capture will be unavailable.")

try:
    import numpy as np
except ImportError:
    np = None
    logger.warning("numpy not installed. Window capture will be unavailable.")

try:
    from PIL import Image
except ImportError:
    Image = None
    logger.warning("Pillow not installed. Window capture will be unavailable.")


def list_all_windows():
    """List all visible windows with titles.

    Returns list of (window_id, title) tuples.
    """
    if sys.platform == "win32":
        return _find_windows_win32("")
    return _list_windows_linux()


def find_windows_by_title(title_substring):
    """Find visible windows whose title contains the substring (case-insensitive).

    Returns list of (window_id, title) tuples.
    window_id is hwnd (int) on Windows, string on Linux.
    """
    if not title_substring:
        return []
    if sys.platform == "win32":
        return _find_windows_win32(title_substring)
    return _find_windows_linux(title_substring)


def get_window_rect(window_id):
    """Get window client area position and size.

    Returns dict {"x": int, "y": int, "w": int, "h": int} or None.
    """
    if sys.platform == "win32":
        return _get_rect_win32(window_id)
    return _get_rect_linux(window_id)


def capture_window(window_id):
    """Capture the target window client area.

    Uses platform-specific APIs (PrintWindow on Windows) to capture the
    window content directly, even when another window is on top of it.

    Returns (PIL.Image, rect_dict) or (None, None).
    """
    if sys.platform == "win32":
        result = _capture_window_win32_direct(window_id)
        if result[0] is not None:
            return result

    # Fallback: screen capture at window coordinates (may capture overlapping windows)
    rect = get_window_rect(window_id)
    if not rect or rect["w"] <= 0 or rect["h"] <= 0:
        return None, None
    if not mss:
        logger.error("mss not installed, cannot capture window.")
        return None, None
    with mss.mss() as sct:
        monitor = {
            "left": rect["x"], "top": rect["y"],
            "width": rect["w"], "height": rect["h"],
        }
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
    return img, rect


def capture_window_region(window_id, roi):
    """Capture a window-relative ROI region from the target window.

    This captures the window content directly (not the screen), then crops
    to the specified ROI.

    Args:
        window_id: Target window handle/id.
        roi: dict with x, y, w, h (window-relative coordinates).

    Returns (PIL.Image, abs_roi_dict) or (None, None).
    abs_roi_dict has absolute screen coordinates for the ROI.
    """
    img, rect = capture_window(window_id)
    if img is None or rect is None:
        return None, None

    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    # Clamp to image bounds
    x2 = min(x + w, img.width)
    y2 = min(y + h, img.height)
    x = max(0, x)
    y = max(0, y)
    if x2 <= x or y2 <= y:
        return None, None

    cropped = img.crop((x, y, x2, y2))
    abs_roi = {
        "x": rect["x"] + x,
        "y": rect["y"] + y,
        "w": x2 - x,
        "h": y2 - y,
    }
    return cropped, abs_roi


def capture_window_by_title(title_substring):
    """Convenience: find first matching window and capture it.

    Returns (PIL.Image, rect_dict, window_id) or (None, None, None).
    """
    windows = find_windows_by_title(title_substring)
    if not windows:
        return None, None, None
    wid = windows[0][0]
    img, rect = capture_window(wid)
    return img, rect, wid


# ---------------------------------------------------------------------------
# Windows implementation
# ---------------------------------------------------------------------------

def _find_windows_win32(title_substring):
    import ctypes

    user32 = ctypes.windll.user32
    results = []
    title_lower = title_substring.lower()

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_lower in buf.value.lower():
                    results.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return results


def _get_rect_win32(hwnd):
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.windll.user32

    # Get client area dimensions (relative to window)
    client_rect = RECT()
    if not user32.GetClientRect(int(hwnd), ctypes.byref(client_rect)):
        return None

    # Convert client area (0,0) to screen coordinates
    pt = POINT(0, 0)
    user32.ClientToScreen(int(hwnd), ctypes.byref(pt))

    return {
        "x": pt.x,
        "y": pt.y,
        "w": client_rect.right,
        "h": client_rect.bottom,
    }


def _capture_window_win32_direct(hwnd):
    """Capture window content using Win32 PrintWindow API.

    PrintWindow asks the window to paint itself into a memory DC, so it
    captures the correct content even when another window is on top.

    Returns (PIL.Image, rect_dict) or (None, None).
    """
    import ctypes

    rect = _get_rect_win32(hwnd)
    if not rect or rect["w"] <= 0 or rect["h"] <= 0:
        return None, None

    w, h = rect["w"], rect["h"]
    hwnd_int = int(hwnd)

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Create compatible DC and bitmap
    wnd_dc = user32.GetDC(hwnd_int)
    if not wnd_dc:
        return None, None

    mem_dc = gdi32.CreateCompatibleDC(wnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(wnd_dc, w, h)
    old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

    # PrintWindow with PW_CLIENTONLY captures client area content.
    # PW_RENDERFULLCONTENT (0x2, Windows 8.1+) ensures DX/composited
    # content is included.
    PW_CLIENTONLY = 0x1
    PW_RENDERFULLCONTENT = 0x2
    success = user32.PrintWindow(hwnd_int, mem_dc,
                                 PW_CLIENTONLY | PW_RENDERFULLCONTENT)
    if not success:
        # Retry without PW_RENDERFULLCONTENT for older Windows versions
        success = user32.PrintWindow(hwnd_int, mem_dc, PW_CLIENTONLY)

    if not success:
        gdi32.SelectObject(mem_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd_int, wnd_dc)
        return None, None

    # Read bitmap pixel data
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # negative = top-down row order
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0  # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(bmi), 0)

    # Cleanup GDI resources
    gdi32.SelectObject(mem_dc, old_bitmap)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd_int, wnd_dc)

    # Convert BGRA buffer to RGB PIL Image
    if not np or not Image:
        return None, None
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    img = Image.fromarray(arr[:, :, [2, 1, 0]], "RGB")

    return img, rect


# ---------------------------------------------------------------------------
# Linux implementation (xdotool / wmctrl)
# ---------------------------------------------------------------------------

def _find_windows_linux(title_substring):
    title_lower = title_substring.lower()
    results = []

    # Try wmctrl first
    try:
        output = subprocess.check_output(
            ["wmctrl", "-l"], text=True, stderr=subprocess.DEVNULL,
        )
        for line in output.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                wid = parts[0]
                title = parts[3]
                if title_lower in title.lower():
                    results.append((wid, title))
        return results
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Fallback: xdotool
    try:
        output = subprocess.check_output(
            ["xdotool", "search", "--name", title_substring],
            text=True, stderr=subprocess.DEVNULL,
        )
        for wid_str in output.strip().splitlines():
            wid = wid_str.strip()
            if wid:
                try:
                    name = subprocess.check_output(
                        ["xdotool", "getwindowname", wid],
                        text=True, stderr=subprocess.DEVNULL,
                    ).strip()
                except subprocess.CalledProcessError:
                    name = f"Window {wid}"
                results.append((wid, name))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return results


def _list_windows_linux():
    """List all visible windows on Linux."""
    results = []

    # Try wmctrl first
    try:
        output = subprocess.check_output(
            ["wmctrl", "-l"], text=True, stderr=subprocess.DEVNULL,
        )
        for line in output.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                wid = parts[0]
                title = parts[3]
                if title.strip():
                    results.append((wid, title))
        return results
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Fallback: xdotool
    try:
        output = subprocess.check_output(
            ["xdotool", "search", "--onlyvisible", "--name", ""],
            text=True, stderr=subprocess.DEVNULL,
        )
        for wid_str in output.strip().splitlines():
            wid = wid_str.strip()
            if wid:
                try:
                    name = subprocess.check_output(
                        ["xdotool", "getwindowname", wid],
                        text=True, stderr=subprocess.DEVNULL,
                    ).strip()
                except subprocess.CalledProcessError:
                    name = f"Window {wid}"
                if name:
                    results.append((wid, name))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return results


def _get_rect_linux(window_id):
    try:
        output = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", str(window_id)],
            text=True, stderr=subprocess.DEVNULL,
        )
        vals = {}
        for line in output.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = int(v.strip())
        x = vals.get("X", 0)
        y = vals.get("Y", 0)
        w = vals.get("WIDTH", 0)
        h = vals.get("HEIGHT", 0)
        if w > 0 and h > 0:
            return {"x": x, "y": y, "w": w, "h": h}
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        pass
    return None
