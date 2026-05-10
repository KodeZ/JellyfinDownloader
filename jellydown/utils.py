"""Utility functions for JellyfinDownloader."""

import re

# Common language name/code aliases. Maps any alias to a canonical 3-letter code.
# Used by normalize_lang and lang_matches for fuzzy matching across the
# different forms Jellyfin can return (3-letter, 2-letter, full name, regional).
_LANG_ALIASES = {
    "eng": "eng", "en": "eng", "english": "eng",
    "spa": "spa", "es": "spa", "spanish": "spa", "esp": "spa", "castellano": "spa",
    "fre": "fre", "fra": "fre", "fr": "fre", "french": "fre", "francais": "fre",
    "ger": "ger", "deu": "ger", "de": "ger", "german": "ger", "deutsch": "ger",
    "ita": "ita", "it": "ita", "italian": "ita", "italiano": "ita",
    "por": "por", "pt": "por", "portuguese": "por",
    "rus": "rus", "ru": "rus", "russian": "rus",
    "jpn": "jpn", "ja": "jpn", "japanese": "jpn",
    "chi": "chi", "zho": "chi", "zh": "chi", "chinese": "chi", "mandarin": "chi", "cantonese": "chi",
    "kor": "kor", "ko": "kor", "korean": "kor",
    "ara": "ara", "ar": "ara", "arabic": "ara",
    "hin": "hin", "hi": "hin", "hindi": "hin",
    "ben": "ben", "bn": "ben", "bengali": "ben",
    "tam": "tam", "ta": "tam", "tamil": "tam",
    "tel": "tel", "te": "tel", "telugu": "tel",
    "mar": "mar", "mr": "mar", "marathi": "mar",
    "pan": "pan", "pa": "pan", "punjabi": "pan",
    "urd": "urd", "ur": "urd", "urdu": "urd",
    "nld": "dut", "dut": "dut", "nl": "dut", "dutch": "dut",
    "swe": "swe", "sv": "swe", "swedish": "swe",
    "nor": "nor", "no": "nor", "norwegian": "nor", "nob": "nor", "nb": "nor", "nno": "nor", "nn": "nor",
    "dan": "dan", "da": "dan", "danish": "dan",
    "fin": "fin", "fi": "fin", "finnish": "fin",
    "pol": "pol", "pl": "pol", "polish": "pol",
    "tur": "tur", "tr": "tur", "turkish": "tur",
    "ces": "cze", "cze": "cze", "cs": "cze", "czech": "cze",
    "hun": "hun", "hu": "hun", "hungarian": "hun",
    "gre": "gre", "ell": "gre", "el": "gre", "greek": "gre",
    "heb": "heb", "he": "heb", "hebrew": "heb",
    "tha": "tha", "th": "tha", "thai": "tha",
    "vie": "vie", "vi": "vie", "vietnamese": "vie",
    "ind": "ind", "id": "ind", "indonesian": "ind",
    "may": "may", "msa": "may", "ms": "may", "malay": "may",
    "ukr": "ukr", "uk": "ukr", "ukrainian": "ukr",
    "ron": "rum", "rum": "rum", "ro": "rum", "romanian": "rum",
    "und": "und", "undefined": "und", "unknown": "und",
}


def normalize_lang(s) -> str:
    """Normalize a language string to a canonical 3-letter code where possible.

    Handles 2/3-letter codes, full names, and regional suffixes ('en-US' -> 'eng').
    Returns 'und' for empty/None input. Unknown values are lowercased and stripped.
    """
    if not s:
        return "und"
    raw = str(s).strip().lower()
    # Strip region suffix like en-US, pt-BR, zh-Hans
    raw = re.split(r"[-_]", raw, 1)[0]
    return _LANG_ALIASES.get(raw, raw)


def lang_matches(track_lang, preferred) -> bool:
    """Return True if a track's language matches the user's preference.

    Uses normalized canonical codes; falls back to substring match against the
    raw track value (so a track listed as 'English (Director's Cut)' still
    matches 'eng').
    """
    if not preferred:
        return False
    pref = normalize_lang(preferred)
    if pref == "und":
        return False
    if normalize_lang(track_lang) == pref:
        return True
    # Substring fallback against the raw track value.
    raw = str(track_lang or "").lower()
    return pref in raw or any(
        alias in raw for alias, code in _LANG_ALIASES.items() if code == pref and len(alias) > 2
    )


def lang_display(code) -> str:
    """Human-friendly label for a language code, e.g. 'eng' -> 'English (eng)'."""
    norm = normalize_lang(code)
    # Reverse lookup: pick the longest alias mapping to this code as the display name.
    name = max(
        (a for a, c in _LANG_ALIASES.items() if c == norm and len(a) > 3),
        key=len,
        default=None,
    )
    if name:
        return f"{name.title()} ({norm})"
    return norm

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
