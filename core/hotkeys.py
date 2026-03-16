"""Global hotkey listener for controlling automation."""
import logging
import threading

logger = logging.getLogger(__name__)

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    logger.warning("pynput not installed. Global hotkeys disabled.")


class HotkeyManager:
    """Manage global hotkeys for start/stop/pause control.

    Default hotkeys:
        F9  = Start / Resume
        F10 = Pause
        F11 = Stop
    """

    def __init__(self, on_start=None, on_pause=None, on_stop=None):
        self.on_start = on_start
        self.on_pause = on_pause
        self.on_stop = on_stop
        self._listener = None
        self._running = False

    def start(self):
        if not PYNPUT_AVAILABLE:
            logger.warning("Cannot start hotkeys: pynput not available")
            return False
        if self._running:
            return True

        self._listener = keyboard.Listener(on_press=self._on_key_press)
        self._listener.daemon = True
        self._listener.start()
        self._running = True
        logger.info("Global hotkeys active: F9=Start/Resume, F10=Pause, F11=Stop")
        return True

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._running = False

    @property
    def is_running(self):
        return self._running

    def _on_key_press(self, key):
        try:
            if key == keyboard.Key.f9:
                if self.on_start:
                    self.on_start()
            elif key == keyboard.Key.f10:
                if self.on_pause:
                    self.on_pause()
            elif key == keyboard.Key.f11:
                if self.on_stop:
                    self.on_stop()
        except Exception as e:
            logger.error(f"Hotkey handler error: {e}")
