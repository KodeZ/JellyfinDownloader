"""Jellyfin API interactions."""

import requests
from urllib.parse import urlencode

TIMEOUT = 30

def jget(base, path, api_key, params=None):
    """Make GET request to Jellyfin API."""
    params = dict(params or {})
    params["api_key"] = api_key
    url = base.rstrip("/") + path
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def authenticate(base, username, password):
    """Authenticate with Jellyfin using username and password."""
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

def build_stream_url(base, api_key, item_id, cfg, media_source_id=None, audio_index=None):
    """Build stream URL with transcoding parameters."""
    params = {
        "api_key": api_key,
        "container": "mp4",
        "VideoCodec": cfg.get("VideoCodec", "h264"),
        "AudioCodec": cfg.get("AudioCodec", "aac"),
        "VideoBitrate": cfg.get("VideoBitrate", 4_000_000),
        "MaxStreamingBitrate": cfg.get("MaxStreamingBitrate", 4_000_000),
        "AudioBitrate": cfg.get("AudioBitrate", 128_000),
        "MaxAudioChannels": cfg.get("MaxAudioChannels", 2),
        "SubtitleMethod": cfg.get("SubtitleMethod", "Encode"),
        "allowVideoStreamCopy": "true",
        "allowAudioStreamCopy": "true",
    }
    if media_source_id:
        params["MediaSourceId"] = media_source_id
    if audio_index is not None:
        params["AudioStreamIndex"] = audio_index

    return f"{base.rstrip('/')}/Videos/{item_id}/stream.mp4?{urlencode(params)}"

def list_library_items(base, api_key, user_id, item_type):
    """List all items of a given type from user's library."""
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


"""Process download or streaming for selected item."""
def get_media_id(cfg, api_key, base, item: dict) -> tuple[str, str]:
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

    return item_id, media_source_id