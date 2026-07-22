from __future__ import annotations

from pathlib import Path

APP_TITLE = "RSS Reader"
APP_VERSION = "1.1.0"
USER_AGENT = f"RSS-Reader-Streamlit/{APP_VERSION}"
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_BACKOFF_SECONDS = 1.5
AUTO_UPDATE_ENABLED = True
AUTO_UPDATE_CHECK_SECONDS = 5
DEFAULT_HIDDEN_EXPIRE_DAYS = 30
DATA_MAINTENANCE_VERSION = 2

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
SETTINGS_PATH = DATA_DIR / "settings.json"
