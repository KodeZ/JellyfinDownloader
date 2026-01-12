import urllib.parse
import requests
import subprocess
import sys
import re
import json
from pathlib import Path

# Configuration management
CONFIG_FILE = Path.home() / ".jellydown_config.json"
DEFAULT_CONFIG = {
    "video_bitrate": 4_000_000  # Default 4 Mbps
}

def load_config() -> dict:
    """Load configuration from file or return default config."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config: dict):
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Configuration saved to {CONFIG_FILE}")
    except IOError as e:
        print(f"Error saving configuration: {e}", file=sys.stderr)

def show_config_menu():
    """Display interactive configuration menu."""
    config = load_config()
    
    while True:
        print("\n" + "="*50)
        print("JellyfinDownloader - Configuration Menu")
        print("="*50)
        current_bitrate = config.get("video_bitrate", DEFAULT_CONFIG["video_bitrate"])
        current_mbps = current_bitrate / 1_000_000
        print(f"\nCurrent video bitrate: {current_mbps:.1f} Mbps ({current_bitrate:,} bps)")
        print("\nOptions:")
        print("  1. Set custom bitrate")
        print("  2. Use preset bitrate")
        print("  3. Reset to default (4 Mbps)")
        print("  4. Save and exit")
        print("  5. Exit without saving")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == "1":
            try:
                bitrate_input = input("\nEnter bitrate in Mbps (e.g., 2.5 for 2.5 Mbps): ").strip()
                bitrate_mbps = float(bitrate_input)
                if bitrate_mbps <= 0:
                    print("Bitrate must be positive!")
                    continue
                config["video_bitrate"] = int(bitrate_mbps * 1_000_000)
                print(f"Bitrate set to {bitrate_mbps} Mbps ({config['video_bitrate']:,} bps)")
            except ValueError:
                print("Invalid input! Please enter a number.")
        
        elif choice == "2":
            print("\nPreset bitrates:")
            presets = [
                ("1", "Low (1 Mbps)", 1_000_000),
                ("2", "Medium (2 Mbps)", 2_000_000),
                ("3", "High (4 Mbps)", 4_000_000),
                ("4", "Very High (8 Mbps)", 8_000_000),
                ("5", "Ultra (16 Mbps)", 16_000_000),
            ]
            for num, label, _ in presets:
                print(f"  {num}. {label}")
            
            preset_choice = input("\nSelect preset (1-5): ").strip()
            preset_map = {num: bitrate for num, _, bitrate in presets}
            
            if preset_choice in preset_map:
                config["video_bitrate"] = preset_map[preset_choice]
                mbps = config["video_bitrate"] / 1_000_000
                print(f"Bitrate set to {mbps} Mbps ({config['video_bitrate']:,} bps)")
            else:
                print("Invalid preset selection!")
        
        elif choice == "3":
            config["video_bitrate"] = DEFAULT_CONFIG["video_bitrate"]
            print(f"Bitrate reset to default: 4 Mbps ({config['video_bitrate']:,} bps)")
        
        elif choice == "4":
            save_config(config)
            print("Configuration saved. Exiting...")
            break
        
        elif choice == "5":
            print("Exiting without saving...")
            break
        
        else:
            print("Invalid choice! Please enter 1-5.")

def sanitize_filename(s: str) -> str:
    # Windows-safe: remove <>:"/\|?* and control chars; collapse whitespace
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Avoid trailing dots/spaces (Windows)
    return s.rstrip(" .")

def pick_media_source_id(item_json: dict) -> str:
    ms = item_json.get("MediaSources") or []
    if not ms or "Id" not in ms[0]:
        raise ValueError("No MediaSources[].Id found in item metadata.")
    return ms[0]["Id"]

def derive_output_name(item_json: dict, default_ext: str = ".mp4") -> str:
    item_type = (item_json.get("Type") or "").lower()

    if item_type == "episode":
        series = item_json.get("SeriesName") or "Unknown Series"
        season = item_json.get("ParentIndexNumber")
        episode = item_json.get("IndexNumber")
        title = item_json.get("Name") or "Unknown Episode"

        # Format SxxExx when numbers exist
        if isinstance(season, int) and isinstance(episode, int):
            se = f"S{season:02d}E{episode:02d}"
            base = f"{series} - {se} - {title}"
        else:
            base = f"{series} - {title}"

    elif item_type == "movie":
        name = item_json.get("Name") or "Unknown Movie"
        year = item_json.get("ProductionYear")
        base = f"{name} ({year})" if isinstance(year, int) else name

    else:
        # Fallback for other item types
        base = item_json.get("Name") or "output"

    return sanitize_filename(base) + default_ext

def parse_download_url(download_url: str):
    parsed = urllib.parse.urlparse(download_url)
    qs = urllib.parse.parse_qs(parsed.query)

    api_key = qs.get("api_key", [None])[0]
    if not api_key:
        raise ValueError("api_key missing in URL")

    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "Items":
        raise ValueError("Expected /Items/{id}/Download style URL")

    item_id = parts[1]
    base = f"{parsed.scheme}://{parsed.netloc}"
    return base, item_id, api_key

def build_stream_url(base: str, item_id: str, api_key: str, item_json: dict, video_bitrate=4_000_000) -> str:
    media_source_id = pick_media_source_id(item_json)

    return (
        f"{base}/Videos/{item_id}/master.m3u8"
        f"?api_key={api_key}"
        f"&MediaSourceId={media_source_id}"
        f"&VideoCodec=h264"
        f"&AudioCodec=aac"
        f"&VideoBitrate={video_bitrate}"
        f"&MaxStreamingBitrate={video_bitrate}"
        f"&AudioBitrate=128000"
        f"&MaxAudioChannels=2"
        f"&SubtitleMethod=Encode"
    )

def download_with_ffmpeg(stream_url: str, output_path: Path):
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-stats",
        "-i", stream_url,
        "-c", "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)

def fetch_item_json(base: str, item_id: str, api_key: str) -> dict:
    r = requests.get(f"{base}/Items/{item_id}", params={"api_key": api_key}, timeout=30)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    # Check for config flag
    if len(sys.argv) >= 2 and sys.argv[1] == "--config":
        show_config_menu()
        sys.exit(0)
    
    if len(sys.argv) < 2:
        print('Usage:')
        print('  python jellydown.py "<download_url>" [output_file_or_dir]')
        print('  python jellydown.py --config  (to configure settings)')
        sys.exit(1)

    download_url = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) >= 3 else None

    # Load configuration
    config = load_config()
    video_bitrate = config.get("video_bitrate", DEFAULT_CONFIG["video_bitrate"])
    
    base, item_id, api_key = parse_download_url(download_url)
    item_json = fetch_item_json(base, item_id, api_key)

    stream_url = build_stream_url(base, item_id, api_key, item_json, video_bitrate=video_bitrate)
    print("Streaming URL:\n" + stream_url)

    # Determine output path
    derived_name = derive_output_name(item_json, default_ext=".mp4")

    if out_arg is None:
        output_path = Path(derived_name)
    else:
        p = Path(out_arg)
        output_path = (p / derived_name) if p.exists() and p.is_dir() else p

    print(f"\nDownloading to:\n{output_path}")
    print(f"Using bitrate: {video_bitrate / 1_000_000} Mbps")
    download_with_ffmpeg(stream_url, output_path)
