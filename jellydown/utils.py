"""Utility functions for JellyfinDownloader."""

import re

def sanitize_filename(s: str) -> str:
    """Remove invalid characters from filename."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(" .")

def episode_filename(item: dict, default_ext: str = ".mp4") -> str:
    """Generate filename for episode."""
    series = item.get("SeriesName") or "Unknown Series"
    season = item.get("ParentIndexNumber")
    epnum = item.get("IndexNumber")
    title = item.get("Name") or "Untitled"

    if isinstance(season, int) and isinstance(epnum, int):
        base = f"{series} - S{season:02d}E{epnum:02d} - {title}"
    else:
        base = f"{series} - {title}"

    return sanitize_filename(base) + default_ext

def safe_int(x):
    """Safely convert to int, returning None on failure."""
    try:
        return int(x)
    except Exception:
        return None

def format_episode_label(item):
    """Format episode label for display."""
    s = safe_int(item.get("ParentIndexNumber"))
    e = safe_int(item.get("IndexNumber"))
    name = item.get("Name") or "Untitled"
    if s is not None and e is not None:
        return f"S{s:02d}E{e:02d} - {name}"
    return name
