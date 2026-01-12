#!/usr/bin/env python3
import sys
import math
import requests
import json
import re
import subprocess
import getpass
import shutil
from pathlib import Path
from urllib.parse import urlencode

TIMEOUT = 30
CONFIG_FILE = Path(__file__).with_name("jellydown.json")

def load_config():
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
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2),
        encoding="utf-8"
    )

def sanitize_filename(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(" .")

def episode_filename(item: dict, default_ext: str = ".mp4") -> str:
    series = item.get("SeriesName") or "Unknown Series"
    season = item.get("ParentIndexNumber")
    epnum = item.get("IndexNumber")
    title = item.get("Name") or "Untitled"

    if isinstance(season, int) and isinstance(epnum, int):
        base = f"{series} - S{season:02d}E{epnum:02d} - {title}"
    else:
        base = f"{series} - {title}"

    return sanitize_filename(base) + default_ext

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

def prompt_int(prompt: str, default: int = 1, min_value: int = 1, max_value: int = 9999) -> int:
    raw = input(prompt).strip()
    if raw == "":
        return default
    if not raw.isdigit():
        print(f"Invalid number; using {default}.")
        return default
    v = int(raw)
    return max(min_value, min(max_value, v))

def jget(base, path, api_key, params=None):
    params = dict(params or {})
    params["api_key"] = api_key
    url = base.rstrip("/") + path
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def authenticate(base, username, password):
    url = base.rstrip("/") + "/Users/AuthenticateByName"
    headers = {
        "Content-Type": "application/json",
        "X-Emby-Authorization": 'MediaBrowser Client="JellyfinDownloader", Device="JellyfinDownloader", DeviceId="JellyfinDownloader", Version="1.0.0"'
    }
    payload = {
        "Username": username,
        "Pw": password
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("AccessToken")
    except Exception as e:
        print(f"Authentication failed: {e}")
        return None

def pick(options, title="Choose", page_size=25):
    if not options:
        return None

    page = 0
    pages = math.ceil(len(options) / page_size)

    while True:
        start = page * page_size
        end = min(len(options), start + page_size)
        print(f"\n{title} (showing {start+1}-{end} of {len(options)}; page {page+1}/{pages})")
        for i in range(start, end):
            print(f"  {i+1:4d}. {options[i]['label']}")

        print("\nCommands: number = select, n = next page, p = prev page, b = back, q = quit")
        cmd = input("> ").strip().lower()

        if cmd == "q":
            sys.exit(0)
        if cmd == "b":
            return "BACK"
        if cmd == "n":
            if page + 1 < pages:
                page += 1
            continue
        if cmd == "p":
            if page > 0:
                page -= 1
            continue

        if cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(options):
                return options[idx]["value"]

        print("Invalid input.")

def safe_int(x):
    try:
        return int(x)
    except Exception:
        return None

def format_episode_label(item):
    s = safe_int(item.get("ParentIndexNumber"))
    e = safe_int(item.get("IndexNumber"))
    name = item.get("Name") or "Untitled"
    if s is not None and e is not None:
        return f"S{s:02d}E{e:02d} - {name}"
    return name

def build_hls_url(base, api_key, item_id, cfg, media_source_id=None):
    # Some servers require MediaSourceId; if omitted and server rejects, user can fetch it later.
    params = {
        "api_key": api_key,
        "VideoCodec": cfg.get("VideoCodec", "h264"),
        "AudioCodec": cfg.get("AudioCodec", "aac"),
        "VideoBitrate": cfg.get("VideoBitrate", 4_000_000),
        "MaxStreamingBitrate": cfg.get("MaxStreamingBitrate", 4_000_000),
        "AudioBitrate": cfg.get("AudioBitrate", 128_000),
        "MaxAudioChannels": cfg.get("MaxAudioChannels", 2),
        "SubtitleMethod": cfg.get("SubtitleMethod", "Encode"),
    }
    if media_source_id:
        params["MediaSourceId"] = media_source_id

    return f"{base.rstrip('/')}/Videos/{item_id}/master.m3u8?{urlencode(params)}"

def ffmpeg_available():
    return shutil.which("ffmpeg") is not None

def settings_menu(cfg):
    while True:
        print("\n--- Settings ---")
        print(f"1. Video Codec ({cfg.get('VideoCodec')})")
        print(f"2. Audio Codec ({cfg.get('AudioCodec')})")
        print(f"3. Video Bitrate ({cfg.get('VideoBitrate')})")
        print(f"4. Audio Bitrate ({cfg.get('AudioBitrate')})")
        print(f"5. Max Audio Channels ({cfg.get('MaxAudioChannels')})")
        print("b. Back")
        
        choice = input("Select setting to edit: ").strip().lower()
        if choice == 'b':
            save_config(cfg)
            break
        
        if choice == '1':
            cfg["VideoCodec"] = input("Video Codec [h264]: ").strip() or "h264"
        elif choice == '2':
            cfg["AudioCodec"] = input("Audio Codec [aac]: ").strip() or "aac"
        elif choice == '3':
            cfg["VideoBitrate"] = prompt_int("Video Bitrate: ", default=4000000, max_value=100000000)
            cfg["MaxStreamingBitrate"] = cfg["VideoBitrate"]
        elif choice == '4':
            cfg["AudioBitrate"] = prompt_int("Audio Bitrate: ", default=128000, max_value=1000000)
        elif choice == '5':
            cfg["MaxAudioChannels"] = prompt_int("Max Audio Channels: ", default=2, max_value=8)

def list_library_items(base, api_key, user_id, item_type):
    start_index = 0
    limit = 200
    all_items = []

    while True:
        data = jget(
            base, f"/Users/{user_id}/Items", api_key,
            params={
                "IncludeItemTypes": item_type,
                "Recursive": "true",
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "Fields": "PrimaryImageAspectRatio,MediaSources",
                "StartIndex": start_index,
                "Limit": limit,
            }
        )
        items = data.get("Items", [])
        all_items.extend(items)
        total = data.get("TotalRecordCount", len(all_items))
        start_index += len(items)
        if start_index >= total or not items:
            break
    return all_items

def handle_series(base, api_key, user_id, cfg):
    series_items = list_library_items(base, api_key, user_id, "Series")
    if not series_items:
        print("No series found.")
        return

    while True:
        series_opts = [{"label": (s.get("Name") or "(no name)"), "value": s} for s in series_items]
        series = pick(series_opts, title="Series")
        if series in (None, "BACK"):
            break

        series_id = series["Id"]
        series_name = series.get("Name") or "(no name)"
        print(f"\nSelected series: {series_name}")

        # List seasons for selected series
        seasons_data = jget(
            base, f"/Shows/{series_id}/Seasons", api_key,
            params={"UserId": user_id}
        )
        seasons = seasons_data.get("Items", seasons_data)

        season_opts = []
        for s in seasons:
            snum = safe_int(s.get("IndexNumber"))
            label = s.get("Name") or (f"Season {snum}" if snum is not None else "Season")
            season_opts.append({"label": label, "value": s})

        season = pick(season_opts, title=f"Seasons of {series_name}")
        if season == "BACK":
            continue
        if season is None:
            continue

        season_id = season["Id"]
        season_label = season.get("Name") or "Season"
        
        # List episodes
        eps_data = jget(
            base, f"/Shows/{series_id}/Episodes", api_key,
            params={
                "UserId": user_id,
                "SeasonId": season_id,
                "Fields": "MediaSources,Overview,RunTimeTicks,SeriesName,ParentIndexNumber,IndexNumber,Name",
                "SortBy": "IndexNumber",
                "SortOrder": "Ascending",
            }
        )
        episodes = eps_data.get("Items", [])
        if not episodes:
            print("No episodes found in that season.")
            continue

        ep_opts = [{"label": format_episode_label(e), "value": i} for i, e in enumerate(episodes)]
        selected_index = pick(ep_opts, title=f"Episodes in {season_label}")
        if selected_index == "BACK":
            continue
        if selected_index is None:
            continue

        process_download_or_stream(base, api_key, episodes, selected_index, cfg)

def handle_movies(base, api_key, user_id, cfg):
    movies = list_library_items(base, api_key, user_id, "Movie")
    if not movies:
        print("No movies found.")
        return
    
    while True:
        movie_opts = [{"label": (m.get("Name") or "(no name)"), "value": i} for i, m in enumerate(movies)]
        selected_index = pick(movie_opts, title="Movies")
        if selected_index in (None, "BACK"):
            break
            
        process_download_or_stream(base, api_key, movies, selected_index, cfg)

def process_download_or_stream(base, api_key, items, selected_index, cfg):
    def get_stream_url(item: dict) -> str:
        item_id = item["Id"]
        ms = item.get("MediaSources") or []
        media_source_id = None
        if ms and isinstance(ms, list) and isinstance(ms[0], dict):
            media_source_id = ms[0].get("Id")

        if not media_source_id:
            full = jget(base, f"/Items/{item_id}", api_key)
            ms2 = full.get("MediaSources") or []
            if ms2 and isinstance(ms2, list) and isinstance(ms2[0], dict):
                media_source_id = ms2[0].get("Id")

        return build_hls_url(base, api_key, item_id, cfg, media_source_id=media_source_id)

    target_item = items[selected_index]
    url = get_stream_url(target_item)
    print("\nStream URL:")
    print(url)
    
    dl = input("\nDownload? (y/N): ").strip().lower()
    if dl == "y":
        count = 1
        # Only ask for count if it seems valid (e.g. series)
        if len(items) > 1 and selected_index < len(items) - 1:
             count = prompt_int("How many items to download (including this one)? [default 1]: ", default=1)
        
        out_dir_raw = input("Output directory (blank = current folder): ").strip()
        out_dir = Path(out_dir_raw) if out_dir_raw else Path(".")

        for i in range(selected_index, min(len(items), selected_index + count)):
            item = items[i]
            stream_url = get_stream_url(item)
            # For movies, episode_filename might produce weird results if fields missing, but defaults should handle it
            if item.get("Type") == "Movie":
                filename = sanitize_filename(item.get("Name") or "Movie") + ".mp4"
            else:
                filename = episode_filename(item, ".mp4")
                
            output_path = out_dir / filename

            print(f"\nDownloading {filename}")
            print(f"-> {output_path}")
            download_with_ffmpeg(stream_url, output_path)

        print("\nDone.")
    
    input("\nPress Enter to continue...")

def main():
    cfg = load_config()

    base = (cfg.get("server_url") or "").strip()
    if not base:
        base = input("Jellyfin server URL (e.g. http://192.168.0.1:8096): ").strip()

    if not base.startswith(("http://", "https://")):
        base = "http://" + base

    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        print("\nAuthentication required.")
        print("1. Login with Username/Password (recommended)")
        print("2. Enter API Key manually")
        print("Note: Username/password is used only once to generate an access token.")
        
        while not api_key:
            choice = input("Select [1/2]: ").strip()
            if choice == "1":
                username = input("Username: ").strip()
                password = getpass.getpass("Password: ")
                token = authenticate(base, username, password)
                if token:
                    api_key = token
                    print("Login successful.")
                else:
                    print("Login failed, please try again or use API key.")
            elif choice == "2":
                api_key = input("API key: ").strip()
            else:
                print("Invalid choice. Please enter 1 or 2.")

    cfg["server_url"] = base
    cfg["api_key"] = api_key
    save_config(cfg)
    
    # Check for ffmpeg absence
    if not ffmpeg_available():
         print("Warning: ffmpeg not found in PATH. Downloading will fail.")
    else:
        print("ffmpeg is available.")

    # Determine UserId
    me = jget(base, "/Users/Me", api_key)
    user_id = me.get("Id")
    if not user_id:
        print("Could not determine UserId from /Users/Me")
        sys.exit(1)

    print(f"\nConnected as: {me.get('Name','(unknown)')}  UserId: {user_id}")

    while True:
        print("\n--- Main Menu ---")
        print("1. Series")
        print("2. Movies")
        print("3. Settings")
        print("q. Quit")

        choice = input("Select an option: ").strip().lower()

        if choice == "1":
            handle_series(base, api_key, user_id, cfg)
        elif choice == "2":
            handle_movies(base, api_key, user_id, cfg)
        elif choice == "3":
            settings_menu(cfg)
        elif choice == "q":
            sys.exit(0)
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
