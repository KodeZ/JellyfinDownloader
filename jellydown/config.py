"""Configuration management for JellyfinDownloader."""

import json
import os
from pathlib import Path

DEFAULT_CONFIG_FILE = Path(__file__).parent.parent / "jellydown.json"


def config_path() -> Path:
    """Resolve the config file path.

    Honors the JELLYDOWN_CONFIG_FILE env var so test scripts (and other
    embedders) can redirect writes away from the user's real config. This
    is checked on every call so tests can set the env var after import.
    """
    override = os.environ.get("JELLYDOWN_CONFIG_FILE")
    if override:
        return Path(override)
    return DEFAULT_CONFIG_FILE


def load_config():
    """Load configuration from file with defaults."""
    defaults = {
        "VideoCodec": "h264",
        "AudioCodec": "aac",
        "VideoBitrate": 4_000_000,
        "MaxStreamingBitrate": 4_000_000,
        "AudioBitrate": 128_000,
        "MaxAudioChannels": 2,
        "SubtitleMethod": "Encode",
        "PreferredAudioLanguage": "eng",
        "PreferredSubtitleLanguage": "eng",
        "ParallelDownloads": 2,
    }
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
                return defaults
        except Exception:
            pass
    return defaults


def save_config(cfg: dict):
    """Save configuration to file."""
    config_path().write_text(
        json.dumps(cfg, indent=2),
        encoding="utf-8",
    )
