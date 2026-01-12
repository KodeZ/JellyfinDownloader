import urllib.parse
import requests
import subprocess
import sys
import re
from pathlib import Path

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
    if len(sys.argv) < 2:
        print('Usage: python jellyfin_stream.py "<download_url>" [output_file_or_dir]')
        sys.exit(1)

    download_url = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) >= 3 else None

    base, item_id, api_key = parse_download_url(download_url)
    item_json = fetch_item_json(base, item_id, api_key)

    stream_url = build_stream_url(base, item_id, api_key, item_json, video_bitrate=4_000_000)
    print("Streaming URL:\n" + stream_url)

    # Determine output path
    derived_name = derive_output_name(item_json, default_ext=".mp4")

    if out_arg is None:
        output_path = Path(derived_name)
    else:
        p = Path(out_arg)
        output_path = (p / derived_name) if p.exists() and p.is_dir() else p

    print(f"\nDownloading to:\n{output_path}")
    download_with_ffmpeg(stream_url, output_path)
