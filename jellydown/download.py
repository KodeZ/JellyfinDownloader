"""Download functions for JellyfinDownloader."""

import time
import requests
from pathlib import Path

TIMEOUT = 30

def download_stream(stream_url: str, output_path: Path, estimated_size: int = 0):
    """Download stream directly using requests."""
    response = requests.get(stream_url, stream=True, timeout=TIMEOUT)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    if not total_size and estimated_size:
        total_size = estimated_size
    
    downloaded = 0
    start_time = time.time()
    last_update = start_time
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                current_time = time.time()
                
                # Update every 0.5 seconds
                if current_time - last_update >= 0.5:
                    elapsed = current_time - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        remaining = total_size - downloaded
                        eta = remaining / speed if speed > 0 else 0
                        print(f"\rProgress: {percent:.1f}% ({downloaded / 1e6:.1f}/{total_size / 1e6:.1f} MB) "
                              f"Speed: {speed / 1e6:.1f} MB/s ETA: {int(eta)}s", end='')
                    else:
                        print(f"\rDownloaded: {downloaded / 1e6:.1f} MB Speed: {speed / 1e6:.1f} MB/s", end='')
                    
                    last_update = current_time
    
    elapsed = time.time() - start_time
    speed = downloaded / elapsed if elapsed > 0 else 0
    print(f"\nCompleted: {downloaded / 1e6:.1f} MB in {elapsed:.1f}s (avg: {speed / 1e6:.1f} MB/s)")

def download_direct(base: str, api_key: str, item_id: str, output_path: Path):
    """Download original file directly without transcoding."""
    url = f"{base.rstrip('/')}/Items/{item_id}/Download?api_key={api_key}"
    
    print("Downloading original file (no transcoding)...")
    response = requests.get(url, stream=True, timeout=TIMEOUT)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    start_time = time.time()
    last_update = start_time
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                current_time = time.time()
                
                # Update every 0.5 seconds
                if current_time - last_update >= 0.5:
                    elapsed = current_time - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        remaining = total_size - downloaded
                        eta = remaining / speed if speed > 0 else 0
                        print(f"\rProgress: {percent:.1f}% ({downloaded / 1e6:.1f}/{total_size / 1e6:.1f} MB) "
                              f"Speed: {speed / 1e6:.1f} MB/s ETA: {int(eta)}s", end='')
                    else:
                        print(f"\rDownloaded: {downloaded / 1e6:.1f} MB Speed: {speed / 1e6:.1f} MB/s", end='')
                    
                    last_update = current_time
    
    elapsed = time.time() - start_time
    speed = downloaded / elapsed if elapsed > 0 else 0
    print(f"\nCompleted: {downloaded / 1e6:.1f} MB in {elapsed:.1f}s (avg: {speed / 1e6:.1f} MB/s)")

def should_skip_transcode(item: dict, bitrate: int) -> bool:
    """Check if original file should be downloaded without transcoding.
    
    Returns True if:
    - Bitrate is set to 0 (user wants original files always)
    - Original file is already smaller than transcoded would be
    """
    # If bitrate is 0, always download original
    if bitrate == 0:
        print("Bitrate set to 0 - downloading original file.")
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
        print(f"Original size ({original_size / 1e6:.1f} MB) is already optimal.")
        print(f"Skipping transcode (would be ~{expected_size / 1e6:.1f} MB).")
        return True
    
    return False
