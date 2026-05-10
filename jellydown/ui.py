"""User interface functions for JellyfinDownloader."""

import sys
import math
from pathlib import Path
from collections import Counter

from .config import save_config
from .api import jget
from .download import (
    download_stream, download_direct, should_skip_transcode,
    get_audio_index, fetch_audio_tracks, fetch_subtitle_tracks,
    download_subtitle, filter_subs_by_choice, download_episodes_parallel,
    estimate_transcode_size,
)
from .utils import (
    sanitize_filename, episode_filename, safe_int, format_episode_label,
    normalize_lang, lang_matches,
)


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
        print(f"6. Preferred Audio Language ({cfg.get('PreferredAudioLanguage')})")
        print(f"7. Preferred Subtitle Language ({cfg.get('PreferredSubtitleLanguage')})")
        print(f"8. Parallel Downloads for series ({cfg.get('ParallelDownloads')})")
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
        elif choice == '6':
            raw = input(f"Preferred audio language code or name [{cfg.get('PreferredAudioLanguage')}]: ").strip()
            if raw:
                cfg["PreferredAudioLanguage"] = normalize_lang(raw)
        elif choice == '7':
            raw = input(f"Preferred subtitle language code or name [{cfg.get('PreferredSubtitleLanguage')}]: ").strip()
            if raw:
                cfg["PreferredSubtitleLanguage"] = normalize_lang(raw)
        elif choice == '8':
            cfg["ParallelDownloads"] = prompt_int(
                "Parallel downloads for series: ", default=2, min_value=1, max_value=16
            )


def prompt_output_dir(cfg) -> Path:
    """Prompt for an output directory using the saved default if available."""
    default_path = cfg.get("download_path", "")
    if default_path:
        raw = input(f"Output directory [blank = {default_path}]: ").strip()
    else:
        raw = input("Output directory (blank = current folder): ").strip()

    if raw:
        cfg["download_path"] = raw
        save_config(cfg)
        return Path(raw)
    if default_path:
        return Path(default_path)
    return Path(".")


def select_subtitles_for_item(base, api_key, user_id, item_id, preferred_lang):
    """Single-item subtitle picker. Returns list of subtitle tracks to download (possibly empty)."""
    tracks = fetch_subtitle_tracks(base, api_key, user_id, item_id)
    if not tracks:
        print("No subtitles found.")
        return []

    default_idx = 0
    for i, t in enumerate(tracks):
        if lang_matches(t.get("lang"), preferred_lang):
            default_idx = i
            break

    print("\n--- Available Subtitles ---")
    for i, t in enumerate(tracks):
        marker = "*" if i == default_idx else " "
        print(f" {marker} [{i + 1}] {t.get('title')} [{t.get('lang')}] ({t.get('codec')})")

    default = tracks[default_idx]
    while True:
        raw = input(
            f"\nSelected subtitle: [{default.get('lang')}] {default.get('title')}. "
            f"Press Enter to accept, number to change, 'all' for all, or 'n' to skip: "
        ).strip().lower()
        if raw == "":
            return [default]
        if raw == "all":
            return list(tracks)
        if raw == "n":
            return []
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(tracks):
                return [tracks[idx]]
        print(f"Invalid input. Enter 1-{len(tracks)}, 'all', 'n', or press Enter.")


def filename_for(item) -> str:
    """Build the output filename for a movie or episode item."""
    if item.get("Type") == "Movie":
        return sanitize_filename(item.get("Name") or "Movie") + ".mp4"
    return episode_filename(item, ".mp4")


def download_single_item(base, api_key, user_id, item, cfg, out_dir):
    """Download a single movie or episode interactively (sequential, with prompts)."""
    from .api import get_media_id, build_stream_url

    filename = filename_for(item)
    output_path = out_dir / filename
    item_id, media_source_id = get_media_id(cfg, api_key, base, item)

    chosen_subs = []
    sub_option = ""
    while sub_option not in ("y", "n"):
        sub_option = input("\nDownload subtitles? (y/N): ").strip().lower() or "n"
        if sub_option == "y":
            chosen_subs = select_subtitles_for_item(
                base, api_key, user_id, item_id,
                cfg.get("PreferredSubtitleLanguage", "eng"),
            )
        elif sub_option != "n":
            print("Pick a valid option.")

    print(f"\nDownloading {filename}")
    print(f"-> {output_path}")

    bitrate = cfg.get("VideoBitrate", 4_000_000)
    if should_skip_transcode(item, bitrate):
        download_direct(base, api_key, item["Id"], output_path)
    else:
        audio_index = get_audio_index(
            base, api_key, item_id,
            preferred_lang=cfg.get("PreferredAudioLanguage", "eng"),
        )
        stream_url = build_stream_url(
            base, api_key, item_id, cfg,
            media_source_id=media_source_id, audio_index=audio_index,
        )
        estimated_size = estimate_transcode_size(item, cfg)
        if estimated_size:
            print(f"Estimated size: ~{estimated_size / 1e6:.1f} MB")
        download_stream(stream_url, output_path, estimated_size)

    for sub in chosen_subs:
        download_subtitle(base, api_key, item_id, sub, filename, out_dir)


def scan_episode_languages(base, api_key, user_id, episodes):
    """Scan all episodes upfront, returning audio + subtitle language counts.

    Returns (audio_counts, sub_counts, per_episode_audio, per_episode_subs)
    where counts are Counter of canonical lang codes seen at least once per
    episode. Per-episode lists are kept for debugging/optional use.
    """
    print(f"\nScanning {len(episodes)} episodes for language tracks...")
    audio_counts = Counter()
    sub_counts = Counter()
    per_audio = []
    per_subs = []
    for i, ep in enumerate(episodes, 1):
        item_id = ep["Id"]
        try:
            audios = fetch_audio_tracks(base, api_key, item_id)
        except Exception as e:
            print(f"  [{i}/{len(episodes)}] audio scan failed: {e}")
            audios = []
        try:
            subs = fetch_subtitle_tracks(base, api_key, user_id, item_id)
        except Exception as e:
            print(f"  [{i}/{len(episodes)}] subtitle scan failed: {e}")
            subs = []

        a_codes = {normalize_lang(t.get("language")) for t in audios}
        s_codes = {normalize_lang(t.get("lang")) for t in subs}
        for c in a_codes:
            audio_counts[c] += 1
        for c in s_codes:
            sub_counts[c] += 1
        per_audio.append(audios)
        per_subs.append(subs)
        print(f"  [{i}/{len(episodes)}] {filename_for(ep)}: "
              f"audio={sorted(a_codes)}, subs={sorted(s_codes) or ['none']}")
    return audio_counts, sub_counts, per_audio, per_subs


def pick_batch_audio_lang(audio_counts: Counter, total: int, preferred: str) -> str:
    """Prompt user for the audio language to use across a batch."""
    if not audio_counts:
        print("No audio tracks detected.")
        return preferred

    sorted_codes = sorted(audio_counts.items(), key=lambda x: (-x[1], x[0]))
    default = preferred if audio_counts.get(normalize_lang(preferred), 0) > 0 else sorted_codes[0][0]

    print("\n--- Audio languages found ---")
    for i, (code, count) in enumerate(sorted_codes, 1):
        marker = "*" if code == default else " "
        print(f" {marker} [{i}] {code} ({count}/{total} episodes)")

    while True:
        raw = input(
            f"\nSelected audio: [{default}]. Press Enter to accept or number to change: "
        ).strip()
        if raw == "":
            return default
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(sorted_codes):
                return sorted_codes[idx][0]
        print(f"Invalid input. Enter 1-{len(sorted_codes)} or press Enter.")


def pick_batch_subtitle_choice(sub_counts: Counter, total: int, preferred: str) -> str:
    """Prompt user for batch subtitle selection. Returns 'none', 'all', or a lang code."""
    if not sub_counts:
        print("No subtitles detected in any selected episode.")
        return "none"

    sorted_codes = sorted(sub_counts.items(), key=lambda x: (-x[1], x[0]))
    pref_norm = normalize_lang(preferred)
    default = pref_norm if sub_counts.get(pref_norm, 0) > 0 else sorted_codes[0][0]

    print("\n--- Subtitle languages found ---")
    for i, (code, count) in enumerate(sorted_codes, 1):
        marker = "*" if code == default else " "
        print(f" {marker} [{i}] {code} ({count}/{total} episodes)")
    print(f"   [a] all subtitles per episode")
    print(f"   [n] no subtitles")

    while True:
        raw = input(
            f"\nSelected subtitle: [{default}]. Press Enter to accept, number to change, "
            f"'a' for all, 'n' for none: "
        ).strip().lower()
        if raw == "":
            return default
        if raw == "a":
            return "all"
        if raw == "n":
            return "none"
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(sorted_codes):
                return sorted_codes[idx][0]
        print(f"Invalid input.")


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
        if season in (None, "BACK"):
            continue

        season_id = season["Id"]
        season_label = season.get("Name") or "Season"

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
        if selected_index in (None, "BACK"):
            continue

        process_series_batch(base, api_key, user_id, episodes, selected_index, cfg)


def process_series_batch(base, api_key, user_id, episodes, selected_index, cfg):
    """Download one or more consecutive episodes with shared language settings."""
    target = episodes[selected_index]
    print(f"\nSelected: {format_episode_label(target)}")

    confirm = input("\nDownload? (y/N): ").strip().lower()
    if confirm != "y":
        return

    count = 1
    if len(episodes) > 1 and selected_index < len(episodes) - 1:
        print("\nYou can download multiple episodes. Enter 3 for this and the next 2.")
        count = prompt_int("How many episodes (including this one)? [default 1]: ", default=1)

    end = min(len(episodes), selected_index + count)
    selected = episodes[selected_index:end]

    out_dir = prompt_output_dir(cfg)

    if len(selected) == 1:
        download_single_item(base, api_key, user_id, selected[0], cfg, out_dir)
        print("\nDone.")
        input("\nPress Enter to continue...")
        return

    audio_counts, sub_counts, _, _ = scan_episode_languages(
        base, api_key, user_id, selected
    )
    audio_lang = pick_batch_audio_lang(
        audio_counts, len(selected),
        cfg.get("PreferredAudioLanguage", "eng"),
    )
    sub_choice = pick_batch_subtitle_choice(
        sub_counts, len(selected),
        cfg.get("PreferredSubtitleLanguage", "eng"),
    )

    jobs = []
    for ep in selected:
        filename = filename_for(ep)
        jobs.append({
            "item": ep,
            "filename": filename,
            "output_path": str(out_dir / filename),
            "audio_lang": audio_lang,
            "sub_choice": sub_choice,
        })

    results = download_episodes_parallel(jobs, base, api_key, user_id, cfg)
    failures = [r for r in results if not r.get("ok")]
    if failures:
        print(f"\n{len(failures)} download(s) failed:")
        for r in failures:
            print(f"  - {r['filename']}: {r.get('error')}")
    else:
        print("\nAll downloads completed.")
    input("\nPress Enter to continue...")


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

        movie = movies[selected_index]
        print(f"\nSelected: {movie.get('Name')}")
        confirm = input("\nDownload? (y/N): ").strip().lower()
        if confirm != "y":
            continue

        out_dir = prompt_output_dir(cfg)
        download_single_item(base, api_key, user_id, movie, cfg, out_dir)
        print("\nDone.")
        input("\nPress Enter to continue...")
