"""User interface functions for JellyfinDownloader."""

import sys
import math
from pathlib import Path

from .config import save_config
from .api import jget, build_stream_url
from .download import download_stream, download_direct, should_skip_transcode
from .utils import sanitize_filename, episode_filename, safe_int, format_episode_label

def prompt_int(prompt: str, default: int = 1, min_value: int = 1, max_value: int = 9999) -> int:
    """Prompt user for an integer with validation."""
    raw = input(prompt).strip()
    if raw == "":
        return default
    if not raw.isdigit():
        print(f"Invalid number; using {default}.")
        return default
    v = int(raw)
    return max(min_value, min(max_value, v))

def pick(options, title="Choose", page_size=25):
    """Interactive paginated picker for selecting from a list of options."""
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

def settings_menu(cfg):
    """Interactive settings menu for configuring transcoding options."""
    while True:
        print("\n--- Settings ---")
        print(f"1. Video Codec ({cfg.get('VideoCodec')})")
        print(f"2. Audio Codec ({cfg.get('AudioCodec')})")
        bitrate_display = "No transcoding (original files)" if cfg.get('VideoBitrate') == 0 else cfg.get('VideoBitrate')
        print(f"3. Video Bitrate ({bitrate_display})")
        print(f"4. Audio Bitrate ({cfg.get('AudioBitrate')})")
        print(f"5. Max Audio Channels ({cfg.get('MaxAudioChannels')})")
        print("b. Back")
        
        choice = input("Select setting to edit: ").strip().lower()
        if choice == 'b':
            save_config(cfg)
            break
        
        if choice == '1':
            options = [
                {"label": "H.264 (AVC) - Recommended, high compatibility", "value": "h264"},
                {"label": "H.265 (HEVC) - High efficiency, requires hardware support", "value": "hevc"},
                {"label": "Custom...", "value": "CUSTOM"}
            ]
            res = pick(options, title="Select Video Codec")
            if res and res != "BACK":
                if res == "CUSTOM":
                    cfg["VideoCodec"] = input("Video Codec [h264]: ").strip() or "h264"
                else:
                    cfg["VideoCodec"] = res

        elif choice == '2':
            options = [
                {"label": "AAC - Recommended, high compatibility", "value": "aac"},
                {"label": "MP3", "value": "mp3"},
                {"label": "AC3", "value": "ac3"},
                {"label": "OPUS", "value": "opus"},
                {"label": "Custom...", "value": "CUSTOM"}
            ]
            res = pick(options, title="Select Audio Codec")
            if res and res != "BACK":
                if res == "CUSTOM":
                    cfg["AudioCodec"] = input("Audio Codec [aac]: ").strip() or "aac"
                else:
                    cfg["AudioCodec"] = res

        elif choice == '3':
            print("Video Bitrate (set to 0 to always download original files without transcoding)")
            cfg["VideoBitrate"] = prompt_int("Video Bitrate: ", default=4000000, min_value=0, max_value=100000000)
            cfg["MaxStreamingBitrate"] = cfg["VideoBitrate"]
        elif choice == '4':
            cfg["AudioBitrate"] = prompt_int("Audio Bitrate: ", default=128000, max_value=1000000)
        elif choice == '5':
            cfg["MaxAudioChannels"] = prompt_int("Max Audio Channels: ", default=2, max_value=8)

def handle_series(base, api_key, user_id, cfg):
    """Handle series browsing and download."""
    from .api import list_library_items
    
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
    """Handle movie browsing and download."""
    from .api import list_library_items
    
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
    """Process download or streaming for selected item."""
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

        return build_stream_url(base, api_key, item_id, cfg, media_source_id=media_source_id)

    target_item = items[selected_index]
    url = get_stream_url(target_item)
    print("\nStream URL:")
    print(url)
    
    dl = input("\nDownload? (y/N): ").strip().lower()
    if dl == "y":
        count = 1
        # Only ask for count if it's a series episode (not a movie)
        if target_item.get("Type") != "Movie" and len(items) > 1 and selected_index < len(items) - 1:
             print("\nYou can download multiple items in sequence. If you want your choice and the next 2 episodes, enter 3.")
             count = prompt_int("How many items to download (including this one)? [default 1]: ", default=1)
        
        # Get download path from config or prompt
        default_path = cfg.get("download_path", "")
        if default_path:
            out_dir_raw = input(f"Output directory [blank = {default_path}]: ").strip()
        else:
            out_dir_raw = input("Output directory (blank = current folder): ").strip()
        
        if out_dir_raw:
            out_dir = Path(out_dir_raw)
            cfg["download_path"] = out_dir_raw
            save_config(cfg)
        elif default_path:
            out_dir = Path(default_path)
        else:
            out_dir = Path(".")

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
            
            # Check if transcode is needed
            bitrate = cfg.get("VideoBitrate", 4_000_000)
            if should_skip_transcode(item, bitrate):
                # Download original file directly
                download_direct(base, api_key, item["Id"], output_path)
            else:
                # Download transcoded stream
                # Calculate estimated size
                duration_ticks = item.get("RunTimeTicks")
                estimated_size = 0
                if duration_ticks and bitrate > 0:
                    duration_seconds = duration_ticks / 10_000_000
                    # Total bitrate includes video + audio
                    audio_bitrate = cfg.get("AudioBitrate", 128_000)
                    total_bitrate = bitrate + audio_bitrate
                    # If MaxStreamingBitrate is less, use that
                    max_streaming_bitrate = cfg.get("MaxStreamingBitrate")
                    print(f"Configured with VideoBitrate={bitrate}, AudioBitrate={audio_bitrate}, MaxStreamingBitrate={max_streaming_bitrate}")
                    if max_streaming_bitrate and max_streaming_bitrate < total_bitrate:
                        total_bitrate = max_streaming_bitrate
                    estimated_size = (total_bitrate * duration_seconds) / 8  # bits to bytes
                    print(f"Estimated size: ~{estimated_size / 1e6:.1f} MB (based on {total_bitrate / 1e6:.2f} Mbps and {duration_seconds:.0f} seconds)")
                
                download_stream(stream_url, output_path, estimated_size)

        print("\nDone.")
    
    input("\nPress Enter to continue...")
