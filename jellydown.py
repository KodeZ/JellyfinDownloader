import sys
import math
import requests
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlencode

TIMEOUT = 30
CONFIG_FILE = Path(__file__).with_name("jellydown.json")

def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}

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

def build_4mbps_hls(base, api_key, item_id, media_source_id=None):
    # Some servers require MediaSourceId; if omitted and server rejects, user can fetch it later.
    params = {
        "api_key": api_key,
        "VideoCodec": "h264",
        "AudioCodec": "aac",
        "VideoBitrate": 4_000_000,
        "MaxStreamingBitrate": 4_000_000,
        "AudioBitrate": 128_000,
        "MaxAudioChannels": 2,
        "SubtitleMethod": "Encode",
    }
    if media_source_id:
        params["MediaSourceId"] = media_source_id

    return f"{base.rstrip('/')}/Videos/{item_id}/master.m3u8?{urlencode(params)}"

def main():
    cfg = load_config()

    base = (cfg.get("server_url") or "").strip()
    if not base:
        base = input("Jellyfin server URL (e.g. http://10.0.0.11:8096): ").strip()

    if not base.startswith(("http://", "https://")):
        base = "http://" + base

    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        api_key = input("API key: ").strip()

    cfg["server_url"] = base
    cfg["api_key"] = api_key
    save_config(cfg)

    # Determine UserId (required for many library listing calls)
    me = jget(base, "/Users/Me", api_key)
    user_id = me.get("Id")
    if not user_id:
        print("Could not determine UserId from /Users/Me")
        sys.exit(1)

    print(f"\nConnected as: {me.get('Name','(unknown)')}  UserId: {user_id}")

    # Get Series from the user's library (paged)
    start_index = 0
    limit = 200
    series_items = []

    while True:
        data = jget(
            base, f"/Users/{user_id}/Items", api_key,
            params={
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "Fields": "PrimaryImageAspectRatio",
                "StartIndex": start_index,
                "Limit": limit,
            }
        )
        items = data.get("Items", [])
        series_items.extend(items)
        total = data.get("TotalRecordCount", len(series_items))
        start_index += len(items)
        if start_index >= total or not items:
            break

    if not series_items:
        print("No series found.")
        return

    # Interactive navigation loop
    while True:
        series_opts = [{"label": (s.get("Name") or "(no name)"), "value": s} for s in series_items]
        series = pick(series_opts, title="Series")
        if series in (None, "BACK"):
            continue

        series_id = series["Id"]
        series_name = series.get("Name") or "(no name)"
        print(f"\nSelected series: {series_name}")

        # List seasons for selected series
        seasons_data = jget(
            base, f"/Shows/{series_id}/Seasons", api_key,
            params={"UserId": user_id}
        )
        seasons = seasons_data.get("Items", seasons_data)  # some servers return list, some dict

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
        print(f"\nSelected season: {season_label}")

        # List episodes in the season
        eps_data = jget(
            base, f"/Shows/{series_id}/Episodes", api_key,
            params={
                "UserId": user_id,
                "SeasonId": season_id,
                "Fields": "MediaSources,ProductionYear,Overview,RunTimeTicks",
                "SortBy": "IndexNumber",
                "SortOrder": "Ascending",
            }
        )
        episodes = eps_data.get("Items", [])

        if not episodes:
            print("No episodes found in that season.")
            continue
        # List episodes in the season (ensure MediaSources included)
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

        def episode_stream_url(ep_item: dict) -> str:
            ep_id = ep_item["Id"]
            ms = ep_item.get("MediaSources") or []
            media_source_id = None
            if ms and isinstance(ms, list) and isinstance(ms[0], dict):
                media_source_id = ms[0].get("Id")

            # If your server *requires* MediaSourceId and it isn't present, fetch full item JSON.
            if not media_source_id:
                full = jget(base, f"/Items/{ep_id}", api_key)
                ms2 = full.get("MediaSources") or []
                if ms2 and isinstance(ms2, list) and isinstance(ms2[0], dict):
                    media_source_id = ms2[0].get("Id")

            return build_4mbps_hls(base, api_key, ep_id, media_source_id=media_source_id)

        # Show URL for the selected episode
        ep_item = episodes[selected_index]
        url = episode_stream_url(ep_item)
        print("\n4 Mbps HLS URL:")
        print(url)

        # Download options
        dl = input("\nDownload? (y/N): ").strip().lower()
        if dl == "y":
            count = prompt_int("How many consecutive episodes to download (including this one)? [default 1]: ", default=1)
            out_dir_raw = input("Output directory (blank = current folder): ").strip()
            out_dir = Path(out_dir_raw) if out_dir_raw else Path(".")

            for i in range(selected_index, min(len(episodes), selected_index + count)):
                item = episodes[i]
                stream_url = episode_stream_url(item)
                filename = episode_filename(item, ".mp4")
                output_path = out_dir / filename

                print(f"\nDownloading {format_episode_label(item)}")
                print(f"-> {output_path}")
                download_with_ffmpeg(stream_url, output_path)

            print("\nDone.")

        input("\nPress Enter to continue...")

        # List episodes in the season (ensure MediaSources included)
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

        def episode_stream_url(ep_item: dict) -> str:
            ep_id = ep_item["Id"]
            ms = ep_item.get("MediaSources") or []
            media_source_id = None
            if ms and isinstance(ms, list) and isinstance(ms[0], dict):
                media_source_id = ms[0].get("Id")

            # If your server *requires* MediaSourceId and it isn't present, fetch full item JSON.
            if not media_source_id:
                full = jget(base, f"/Items/{ep_id}", api_key)
                ms2 = full.get("MediaSources") or []
                if ms2 and isinstance(ms2, list) and isinstance(ms2[0], dict):
                    media_source_id = ms2[0].get("Id")

            return build_4mbps_hls(base, api_key, ep_id, media_source_id=media_source_id)

        # Show URL for the selected episode
        ep_item = episodes[selected_index]
        url = episode_stream_url(ep_item)
        print("\n4 Mbps HLS URL:")
        print(url)

        # Download options
        dl = input("\nDownload? (y/N): ").strip().lower()
        if dl == "y":
            count = prompt_int("How many consecutive episodes to download (including this one)? [default 1]: ", default=1)
            out_dir_raw = input("Output directory (blank = current folder): ").strip()
            out_dir = Path(out_dir_raw) if out_dir_raw else Path(".")

            for i in range(selected_index, min(len(episodes), selected_index + count)):
                item = episodes[i]
                stream_url = episode_stream_url(item)
                filename = episode_filename(item, ".mp4")
                output_path = out_dir / filename

                print(f"\nDownloading {format_episode_label(item)}")
                print(f"-> {output_path}")
                download_with_ffmpeg(stream_url, output_path)

            print("\nDone.")

        input("\nPress Enter to continue...")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"\nHTTP error: {e}")
        if e.response is not None:
            try:
                print("Response body:")
                print(e.response.text)
            except Exception:
                pass
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(0)
