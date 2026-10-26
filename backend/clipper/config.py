import os
from pathlib import Path


def _default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Klipnara"
    return Path.home() / ".klipnara"


DATA_DIR = Path(os.environ.get("CLIPPER_DATA_DIR", _default_data_dir())).resolve()
WORK_DIR = DATA_DIR / "work"
MOOD_DIR = DATA_DIR / "mood"
LEGACY_SOURCE_DIR = DATA_DIR / "sources"
LEGACY_CLIP_DIR = DATA_DIR / "clips"
SOURCE_DIR = Path(os.environ.get("CLIPPER_SOURCE_DIR", LEGACY_SOURCE_DIR)).resolve()
CLIP_DIR = Path(os.environ.get("CLIPPER_CLIP_DIR", LEGACY_CLIP_DIR)).resolve()
DB_PATH = DATA_DIR / "clipper.sqlite3"
MAX_UPLOAD_BYTES = int(os.environ.get("CLIPPER_MAX_UPLOAD_BYTES", 2 * 1024**3))
MIN_FREE_BYTES = 1024**3
