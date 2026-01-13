"""Configuration management for JellyfinDownloader."""

import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "jellydown.json"

def load_config():
    """Load configuration from file with defaults."""
    defaults = {
        "VideoCodec": "h264",
        "AudioCodec": "aac",
        "VideoBitrate": 4_000_000,
        "MaxStreamingBitrate": 4_000_000,
        "AudioBitrate": 128_000,
        "MaxAudioChannels": 2,
        "SubtitleMethod": "Encode"
    }
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
                return defaults
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    """Save configuration to file."""
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2),
        encoding="utf-8"
    )
