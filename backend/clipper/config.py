import os
from pathlib import Path


def _default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Klipnara"
    return Path.home() / ".klipnara"


DATA_DIR = Path(os.environ.get("CLIPPER_DATA_DIR", _default_data_dir())).resolve()
SOURCE_DIR = DATA_DIR / "sources"
WORK_DIR = DATA_DIR / "work"
CLIP_DIR = DATA_DIR / "clips"
DB_PATH = DATA_DIR / "clipper.sqlite3"
MAX_UPLOAD_BYTES = int(os.environ.get("CLIPPER_MAX_UPLOAD_BYTES", 2 * 1024**3))
MIN_FREE_BYTES = 1024**3
