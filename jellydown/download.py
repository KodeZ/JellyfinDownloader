"""Download functions for JellyfinDownloader."""

import os
import time
import logging
import threading
import requests
from pathlib import Path

from .utils import lang_matches, normalize_lang

log = logging.getLogger(__name__)

TIMEOUT = 30


class DownloadCancelled(Exception):
    """Raised inside a download loop when its cancel_event has been set."""

SUBTITLE_CODEC_EXT = {
    "subrip": "srt",
    "srt": "srt",
    "ass": "ass",
    "ssa": "ass",
    "mov_text": "srt",
    "vtt": "vtt",
    "pgssub": "sup",
    "pgs": "sup",
}


def fetch_subtitle_tracks(base: str, api_key: str, user_id: str, item_id: str) -> list[dict]:
    """Return subtitle track metadata for a Jellyfin item via PlaybackInfo."""
    session = requests.Session()
    session.headers.update({"X-Emby-Token": api_key})
    try:
        resp = session.post(
            f"{base.rstrip('/')}/Items/{item_id}/PlaybackInfo",
            params={"userId": user_id},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("Failed to reach PlaybackInfo: %s", e)
        return []

    tracks = []
    for source in data.get("MediaSources", []):
        s_id = source.get("Id")
        for stream in source.get("MediaStreams", []):
            if stream.get("Type") != "Subtitle":
                continue
            raw_codec = (stream.get("Codec") or "srt").lower()
            tracks.append({
                "stream_index": stream.get("Index"),
                "source_id": s_id,
                "title": stream.get("DisplayTitle", "Subtitle"),
                "lang": stream.get("Language", "und"),
                "ext": SUBTITLE_CODEC_EXT.get(raw_codec, "srt"),
                "codec": raw_codec,
            })
    return tracks


def download_subtitle(base: str, api_key: str, item_id: str, sub: dict,
                      base_filename: str, out_dir) -> bool:
    """Download a single subtitle track to {out_dir}/{base_filename}.{lang}.{ext}.

    Returns True on success.
    """
    out_dir = str(out_dir)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    base_filename = os.path.splitext(base_filename)[0]
    url = (
        f"{base.rstrip('/')}/Videos/{item_id}/{sub['source_id']}"
        f"/Subtitles/{sub['stream_index']}/Stream.{sub['ext']}"
    )
    try:
        res = requests.get(url, params={"api_key": api_key}, timeout=TIMEOUT)
    except Exception as e:
        log.error("Subtitle download failed: %s", e)
        return False
    if res.status_code != 200:
        log.error("Subtitle error %s for %s.", res.status_code, sub['title'])
        return False
    clean_name = f"{base_filename}.{sub['lang']}.{sub['ext']}"
    with open(os.path.join(out_dir, clean_name), "wb") as f:
        f.write(res.content)
    log.info("Saved subtitle: %s", clean_name)
    return True


def filter_subs_by_choice(tracks: list[dict], choice) -> list[dict]:
    """Pick subtitle tracks based on a batch choice.

    `choice` is one of: 'none', 'all', or a language code/string. Falls back to
    an empty list when 'none', the full list when 'all', or all matching tracks
    by language. If a language was requested but missing, returns []."""
    if not tracks or choice == "none" or choice is None:
        return []
    if choice == "all":
        return tracks
    return [t for t in tracks if lang_matches(t.get("lang"), choice)]


def fetch_audio_tracks(base: str, api_key: str, item_id: str) -> list[dict]:
    """Return audio track metadata for a Jellyfin item."""
    url = f"{base.rstrip('/')}/Items/{item_id}?api_key={api_key}"
    resp = requests.get(url, timeout=TIMEOUT).json()
    return [
        {
            "index": s["Index"],
            "language": s.get("Language", "und"),
            "codec": s.get("Codec"),
            "title": s.get("DisplayTitle") or s.get("Title") or "",
        }
        for s in resp.get("MediaSources", [{}])[0].get("MediaStreams", [])
        if s.get("Type") == "Audio"
    ]


def pick_default_track(tracks: list[dict], preferred_lang: str) -> int:
    """Return the index in `tracks` whose language matches preferred_lang, else 0."""
    for i, t in enumerate(tracks):
        if lang_matches(t.get("language"), preferred_lang):
            return i
    return 0


def select_track(tracks: list[dict], preferred_lang: str, kind: str = "audio") -> dict | None:
    """Show available tracks, pre-select the preferred language, prompt to confirm/change.

    Returns the chosen track dict (containing 'index', 'language', etc.) or None
    if no tracks were provided.
    """
    if not tracks:
        return None

    default_idx = pick_default_track(tracks, preferred_lang)
    print(f"\n--- Available {kind.capitalize()} Tracks ---")
    for i, t in enumerate(tracks):
        marker = "*" if i == default_idx else " "
        title = f" - {t['title']}" if t.get("title") else ""
        print(f" {marker} [{i}] {t.get('language', 'und')}{title}")

    default = tracks[default_idx]
    label = default.get("language", "und")
    while True:
        raw = input(
            f"\nSelected {kind}: [{label}]. Press Enter to accept or enter number to change: "
        ).strip()
        if raw == "":
            print(f"Using {kind} track [{default_idx}] {label}.")
            return default
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(tracks):
                chosen = tracks[idx]
                print(f"Using {kind} track [{idx}] {chosen.get('language', 'und')}.")
                return chosen
        print(f"Invalid input. Enter a number 0-{len(tracks) - 1} or press Enter.")


def get_audio_index(base: str, api_key: str, item_id: str, preferred_lang: str = "eng") -> int | None:
    """Interactive audio track selection for a single item."""
    tracks = fetch_audio_tracks(base, api_key, item_id)
    if not tracks:
        log.warning("No audio tracks found.")
        return None
    chosen = select_track(tracks, preferred_lang, kind="audio")
    return chosen["index"] if chosen else None


def resolve_audio_index(base: str, api_key: str, item_id: str, preferred_lang: str) -> tuple[int | None, str]:
    """Non-interactive lookup: pick the audio stream index matching preferred_lang.

    Returns (stream_index, language_label) or (None, '') if no audio present.
    Falls back to the first track if no language match is found.
    """
    tracks = fetch_audio_tracks(base, api_key, item_id)
    if not tracks:
        return None, ""
    idx = pick_default_track(tracks, preferred_lang)
    chosen = tracks[idx]
    return chosen["index"], chosen.get("language", "und")



def _stream_to_file(response, output_path: Path, estimated_size: int = 0,
                    progress=None, task_id=None,
                    cancel_event: threading.Event | None = None,
                    progress_cb=None):
    """Write a streaming HTTP response to disk with progress reporting.

    Reporting precedence (first match wins):
      - `progress_cb(downloaded, total, speed)` — generic callback for any UI.
      - `progress` + `task_id` — rich.progress task to update.
      - stdout fallback — single-line CR-overwrite updates.

    If `cancel_event` is set during the download, raises DownloadCancelled.
    The partially-written file is not deleted; callers decide cleanup policy.
    """
    total_size = int(response.headers.get("content-length", 0))
    if not total_size and estimated_size:
        total_size = estimated_size
    if progress is not None and task_id is not None and total_size:
        progress.update(task_id, total=total_size)

    downloaded = 0
    start_time = time.time()
    last_update = start_time
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled()
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)

            if progress_cb is not None:
                now = time.time()
                if now - last_update < 0.25 and downloaded < (total_size or downloaded + 1):
                    continue
                elapsed = now - start_time
                speed = downloaded / elapsed if elapsed > 0 else 0
                progress_cb(downloaded, total_size, speed)
                last_update = now
                continue

            if progress is not None and task_id is not None:
                progress.update(task_id, completed=downloaded)
                continue

            now = time.time()
            if now - last_update < 0.5:
                continue
            elapsed = now - start_time
            speed = downloaded / elapsed if elapsed > 0 else 0
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                remaining = total_size - downloaded
                eta = remaining / speed if speed > 0 else 0
                print(
                    f"\rProgress: {percent:.1f}% ({downloaded / 1e6:.1f}/{total_size / 1e6:.1f} MB) "
                    f"Speed: {speed / 1e6:.1f} MB/s ETA: {int(eta)}s",
                    end="",
                )
            else:
                print(
                    f"\rDownloaded: {downloaded / 1e6:.1f} MB Speed: {speed / 1e6:.1f} MB/s",
                    end="",
                )
            last_update = now

    if progress_cb is not None:
        elapsed = time.time() - start_time
        speed = downloaded / elapsed if elapsed > 0 else 0
        progress_cb(downloaded, total_size or downloaded, speed)
    elif progress is None or task_id is None:
        elapsed = time.time() - start_time
        speed = downloaded / elapsed if elapsed > 0 else 0
        print(f"\nCompleted: {downloaded / 1e6:.1f} MB in {elapsed:.1f}s (avg: {speed / 1e6:.1f} MB/s)")
    return downloaded


def download_stream(stream_url: str, output_path: Path, estimated_size: int = 0,
                    progress=None, task_id=None,
                    cancel_event: threading.Event | None = None,
                    progress_cb=None):
    """Download a transcoded stream URL to disk."""
    response = requests.get(stream_url, stream=True, timeout=TIMEOUT)
    response.raise_for_status()
    return _stream_to_file(response, output_path, estimated_size,
                           progress, task_id, cancel_event, progress_cb)


def download_direct(base: str, api_key: str, item_id: str, output_path: Path,
                    progress=None, task_id=None,
                    cancel_event: threading.Event | None = None,
                    progress_cb=None):
    """Download the original file directly without transcoding."""
    url = f"{base.rstrip('/')}/Items/{item_id}/Download?api_key={api_key}"
    if progress is None and progress_cb is None:
        log.info("Downloading original file (no transcoding)...")
    response = requests.get(url, stream=True, timeout=TIMEOUT)
    response.raise_for_status()
    return _stream_to_file(response, output_path, 0,
                           progress, task_id, cancel_event, progress_cb)

def estimate_transcode_size(item: dict, cfg: dict) -> int:
    """Estimate transcoded output size in bytes from item duration and config bitrates."""
    duration_ticks = item.get("RunTimeTicks")
    bitrate = cfg.get("VideoBitrate", 4_000_000)
    if not duration_ticks or not bitrate:
        return 0
    duration_seconds = duration_ticks / 10_000_000
    audio_bitrate = cfg.get("AudioBitrate", 128_000)
    total_bitrate = bitrate + audio_bitrate
    max_streaming = cfg.get("MaxStreamingBitrate")
    if max_streaming and max_streaming < total_bitrate:
        total_bitrate = max_streaming
    return int((total_bitrate * duration_seconds) / 8)


def download_episode_job(job: dict, base: str, api_key: str, user_id: str,
                         cfg: dict, progress=None,
                         cancel_event: threading.Event | None = None,
                         progress_cb=None) -> dict:
    """Worker that downloads one episode's video and subtitles.

    `job` keys: item, filename, output_path, audio_lang, sub_choice.
    Returns a result dict with status / error info.
    """
    from .api import get_media_id, build_stream_url

    item = job["item"]
    filename = job["filename"]
    output_path = Path(job["output_path"])
    audio_lang = job.get("audio_lang") or cfg.get("PreferredAudioLanguage", "eng")
    sub_choice = job.get("sub_choice", "none")

    task_id = None
    if progress is not None:
        est = estimate_transcode_size(item, cfg) or 1
        task_id = progress.add_task(filename, total=est, start=True)

    try:
        item_id, media_source_id = get_media_id(cfg, api_key, base, item)
        bitrate = cfg.get("VideoBitrate", 4_000_000)

        if should_skip_transcode(item, bitrate):
            download_direct(base, api_key, item["Id"], output_path,
                            progress=progress, task_id=task_id,
                            cancel_event=cancel_event, progress_cb=progress_cb)
        else:
            audio_index, audio_label = resolve_audio_index(base, api_key, item_id, audio_lang)
            if progress is None and progress_cb is None:
                if audio_label and lang_matches(audio_label, audio_lang):
                    log.info("Audio: %s", audio_label)
                else:
                    log.info("Audio: %s (preferred '%s' not available)",
                             audio_label or "first track", audio_lang)
            stream_url = build_stream_url(
                base, api_key, item_id, cfg,
                media_source_id=media_source_id, audio_index=audio_index,
            )
            download_stream(stream_url, output_path,
                            estimate_transcode_size(item, cfg),
                            progress=progress, task_id=task_id,
                            cancel_event=cancel_event, progress_cb=progress_cb)

        if sub_choice and sub_choice != "none":
            sub_tracks = fetch_subtitle_tracks(base, api_key, user_id, item_id)
            wanted = filter_subs_by_choice(sub_tracks, sub_choice)
            if not wanted and sub_choice != "all":
                log.warning("No subtitle matching '%s' for %s.", sub_choice, filename)
            for sub in wanted:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled()
                download_subtitle(base, api_key, item_id, sub, filename, output_path.parent)

        return {"filename": filename, "ok": True}
    except DownloadCancelled:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"filename": filename, "ok": False, "cancelled": True, "error": "cancelled"}
    except Exception as e:
        return {"filename": filename, "ok": False, "error": str(e)}
    finally:
        if progress is not None and task_id is not None:
            progress.update(task_id, visible=False)


def download_episodes_parallel(jobs: list[dict], base: str, api_key: str,
                               user_id: str, cfg: dict) -> list[dict]:
    """Download episode jobs concurrently with a multi-line rich progress display.

    Thin adapter over DownloadManager: submits all jobs and renders progress
    via a subscriber that updates rich.Progress. Returns per-job results in
    the same shape the previous implementation produced.
    """
    from rich.progress import (
        Progress, TextColumn, BarColumn, DownloadColumn,
        TransferSpeedColumn, TimeRemainingColumn, TaskProgressColumn,
    )
    from .download_manager import (
        DownloadManager, EV_ADDED, EV_PROGRESS, EV_STATE,
        DONE, FAILED, CANCELLED,
    )

    workers = max(1, int(cfg.get("ParallelDownloads", 2)))
    log.info("Starting %d downloads, %d in parallel...", len(jobs), workers)

    columns = [
        TextColumn("[bold blue]{task.description}", justify="left"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ]

    job_to_task: dict[str, int] = {}
    completed_lock = threading.Lock()
    completed_count = [0]

    with Progress(*columns, transient=False) as progress:
        overall = progress.add_task(
            f"[green]Total ({len(jobs)} episodes)", total=len(jobs)
        )

        def on_event(ev, job):
            if ev == EV_ADDED:
                tid = progress.add_task(job.filename, total=1, start=True)
                job_to_task[job.id] = tid
            elif ev == EV_PROGRESS:
                tid = job_to_task.get(job.id)
                if tid is not None:
                    progress.update(
                        tid,
                        completed=job.downloaded,
                        total=job.total or job.downloaded or 1,
                    )
            elif ev == EV_STATE and job.status in (DONE, FAILED, CANCELLED):
                tid = job_to_task.get(job.id)
                if tid is not None:
                    progress.update(tid, visible=False)
                with completed_lock:
                    completed_count[0] += 1
                    progress.update(overall, completed=completed_count[0])
                if job.status == DONE:
                    progress.console.print(f"[green]Done:[/green] {job.filename}")
                elif job.status == CANCELLED:
                    progress.console.print(f"[yellow]Cancelled:[/yellow] {job.filename}")
                else:
                    progress.console.print(
                        f"[red]Failed:[/red] {job.filename} ({job.error})"
                    )

        manager = DownloadManager(base, api_key, user_id, cfg, workers=workers)
        manager.subscribe(on_event)
        submitted = [manager.submit(spec) for spec in jobs]
        try:
            manager.wait_all()
        except KeyboardInterrupt:
            progress.console.print("[yellow]Cancelling all downloads...[/yellow]")
            manager.cancel_all()
            manager.wait_all()
            raise
        finally:
            manager.shutdown(wait=True)

    results: list[dict] = []
    for j in submitted:
        if j.status == DONE:
            results.append({"filename": j.filename, "ok": True})
        elif j.status == CANCELLED:
            results.append({
                "filename": j.filename, "ok": False,
                "cancelled": True, "error": "cancelled",
            })
        else:
            results.append({
                "filename": j.filename, "ok": False, "error": j.error,
            })
    return results


def should_skip_transcode(item: dict, bitrate: int) -> bool:
    """Check if original file should be downloaded without transcoding.
    
    Returns True if:
    - Bitrate is set to 0 (user wants original files always)
    - Original file is already smaller than transcoded would be
    """
    # If bitrate is 0, always download original
    if bitrate == 0:
        log.info("Bitrate set to 0 - downloading original file.")
        return True
    
    duration_ticks = item.get("RunTimeTicks")
    ms = item.get("MediaSources") or []
    
    if not duration_ticks or not ms or not isinstance(ms, list) or not ms[0]:
        return False
    
    original_size = ms[0].get("Size")
    if not original_size:
        return False
    
    # Convert duration from ticks to seconds (10,000 ticks = 1ms)
    duration_seconds = duration_ticks / 10_000_000
    
    # Calculate expected transcoded size in bytes
    bitrate_bytes_per_sec = bitrate / 8
    expected_size = bitrate_bytes_per_sec * duration_seconds
    
    # If original is within 5% of expected, skip transcode
    if original_size <= expected_size * 1.05:
        log.info("Original size (%.1f MB) is already optimal; skipping transcode (would be ~%.1f MB).",
                 original_size / 1e6, expected_size / 1e6)
        return True
    
    return False
