
"""Theme + settings for the Vice City wallet.

Everything lives in %APPDATA%/ViceCity/settings.json. Colors are plain hex
strings; the cover is either a built-in preset name or a user image file
(copied into APPDATA/ViceCity/covers/cover.<ext> at apply time).
The wallet name is a local label shown in the UI (on-chain unique naming is
a Tier-2 roadmap item, not in this file's scope).
"""
import os
import json
import json
import shutil
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ViceCity"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
COVERS_DIR = CONFIG_DIR / "covers"

PRESETS = {
    "vice": {
        "title": "Vice (по умолчанию)",
        "accent": "#ff2d95", "accent2": "#00e6ff", "gold": "#ffc428",
        "bg": "#0b0a18", "panel": "#171233", "panel2": "#1d1740",
        "border": "#2a2150", "dim": "#a99dd6", "green": "#39ff88",
        "red": "#ff5566",
        "cover": "builtin:sunset",
    },
    "abyss": {
        "title": "Abyss (глубина)",
        "accent": "#00b4ff", "accent2": "#7cffcb", "gold": "#e9e2ff",
        "bg": "#050d1f", "panel": "#0e1a35", "panel2": "#14224a",
        "border": "#1e3a6e", "dim": "#8fb0d8", "green": "#39ff88",
        "red": "#ff5566",
        "cover": "builtin:ocean",
    },
    "aurora": {
        "title": "Aurora (северное сияние)",
        "accent": "#59ff9c", "accent2": "#b36bff", "gold": "#ffd166",
        "bg": "#0a0f14", "panel": "#101a24", "panel2": "#16242f",
        "border": "#22384a", "dim": "#9db8c8", "green": "#59ff9c",
        "red": "#ff5566",
        "cover": "builtin:aurora",
    },
    "noir": {
        "title": "Gold Noir (чёрное золото)",
        "accent": "#ffc428", "accent2": "#f5f5f5", "gold": "#ffc428",
        "bg": "#0d0c0a", "panel": "#191713", "panel2": "#232019",
        "border": "#3a3222", "dim": "#c9b98a", "green": "#39ff88",
        "red": "#ff5566",
        "cover": "builtin:noir",
    },
    "sakura": {
        "title": "Sakura Dawn",
        "accent": "#ff6fae", "accent2": "#ffb86b", "gold": "#ffe08a",
        "bg": "#1a0f1c", "panel": "#2a1828", "panel2": "#371f33",
        "border": "#54304c", "dim": "#d8b3cc", "green": "#39ff88",
        "red": "#ff5566",
        "cover": "builtin:sakura",
    },
}

BUILTIN_COVERS = list(PRESETS.keys())


def load_settings() -> dict:
    defaults = {
        "theme": "vice",
        "custom_colors": {},       # overrides over the preset: hex fields
        "custom_cover": "",        # path to a user image, overrides preset
        "wallet_name": "My Vice Wallet",
        "node_url": "http://127.0.0.1:9332",
        "pool_min_ram_gb": 96,     # gate: pool mode hardware minimums
        "pool_min_threads": 14,
        "pool_port": 9342,
    }
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                defaults[k] = v
        except Exception:
            pass
    return defaults


def save_settings(s: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def effective_theme(s: dict) -> dict:
    """Preset colors overridden by custom_colors."""
    base = dict(PRESETS.get(s.get("theme", "vice"), PRESETS["vice"]))
    base.update(s.get("custom_colors", {}))
    base["title"] = PRESETS.get(s.get("theme", "vice"),
                                PRESETS["vice"])["title"]
    return base


def set_custom_cover(path: str) -> None:
    """Copy a user image into covers/ as the active cover file."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(path)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    dst = COVERS_DIR / ("cover" + src.suffix.lower())
    shutil.copyfile(src, dst)


def active_cover_path(s: dict) -> Path | None:
    """User file cover wins; built-ins are rendered by art.make_banner-style
    presets in the app layer."""
    if s.get("custom_cover"):
        p = Path(s["custom_cover"])
        if p.exists():
            return p
    for f in COVERS_DIR.glob("cover.*"):
        return f
    return None
