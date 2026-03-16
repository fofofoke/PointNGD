"""Telegram notification module."""
import logging
import requests
import threading

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Send notifications via Telegram Bot API."""

    def __init__(self, bot_token="", chat_id=""):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def is_configured(self):
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text):
        """Send a text message. Returns True on success."""
        if not self.is_configured():
            logger.warning("Telegram not configured, skipping notification")
            return False
        try:
            url = TELEGRAM_API.format(token=self.bot_token)
            resp = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Telegram message sent: {text}")
                return True
            else:
                logger.error(f"Telegram error {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_message_async(self, text):
        """Send message in a background thread."""
        t = threading.Thread(target=self.send_message, args=(text,), daemon=True)
        t.start()

    def test_connection(self):
        """Send a test message to verify configuration."""
        return self.send_message("Lineage Bot: Test connection successful!")
