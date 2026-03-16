"""Utility for finding and capturing a target window by title."""
import sys
import subprocess

import mss
from PIL import Image


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

    Returns (PIL.Image, rect_dict) or (None, None).
    """
    rect = get_window_rect(window_id)
    if not rect or rect["w"] <= 0 or rect["h"] <= 0:
        return None, None
    with mss.mss() as sct:
        monitor = {
            "left": rect["x"], "top": rect["y"],
            "width": rect["w"], "height": rect["h"],
        }
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
    return img, rect


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
