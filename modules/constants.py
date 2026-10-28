# Media Cataloger
# Author: GlacialPigeon
# GitHub: https://github.com/GlacialPigeon

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Media Cataloger"
APP_VERSION = "1.0.0"
MIN_PYTHON = (3, 10)

APP_ROOT = Path(os.path.abspath(__file__)).parent.parent
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "MediaCataloger.db"
LEGACY_DB_PATH = DATA_DIR / "MediaCatalog.db"     # the name before the tool was called Media Cataloger
CONFIG_PATH = DATA_DIR / "config.json"
BACKUP_DIR = DATA_DIR / "backups"
REPORTS_DIR = APP_ROOT / "reports"
LOGS_DIR = APP_ROOT / "logs"
PATHLISTS_DIR = APP_ROOT / "pathlists"
LOCALES_DIR = APP_ROOT / "locales"
