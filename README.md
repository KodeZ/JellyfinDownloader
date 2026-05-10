# JellyfinDownloader

A Python tool for downloading movies and TV series from your Jellyfin server. Streams directly with server-side transcoding (so it benefits from any hardware acceleration on the server) or grabs the original file untouched. Downloads typically run 10–20× faster than real time.

The default UI is a Textual-based TUI with a Midnight-Commander-style library tree on the left and a live downloads pane on the right. The legacy text-menu CLI is still available under `--classic`.

## Features

- **TUI by default** — tree navigation, multi-select, modal download dialog, live download progress in a side pane.
- **Background download manager** — multiple downloads run in parallel; each can be cancelled or removed independently.
- **Server-side transcoding or original files** — set Video Bitrate to 0 to always download originals, or let the tool skip transcoding when the original is already smaller than the transcoded result would be.
- **Per-item language tracks** — when you trigger a download, the audio and subtitle pickers are populated from the actual tracks on that file (or the union of tracks across a batch), via the Jellyfin API.
- **Series batch downloads** — mark multiple episodes with `space`, hit `d`, pick shared language settings once, and the tool queues them all.
- **In-tree settings** — settings live as a branch in the library tree; press Enter on a leaf to edit, Enter to save, Esc to cancel.
- **Persistent configuration** — server URL, credentials, language preferences, and last-used download path are remembered in `jellydown.json`.
- **Classic CLI fallback** — `python jellydown.py --classic` for the original text-menu workflow (useful for scripting).

## Prerequisites

- **Python 3.10+**
- Python packages: `requests`, `rich`, `textual` (see [requirements.txt](requirements.txt))

### Installing Python

#### Windows

```powershell
winget install Python.Python.3.12
```

Or via the Microsoft Store, or the [official installer](https://www.python.org/downloads/) (tick "Add Python to PATH").

```powershell
python --version
```

#### Linux

Debian/Ubuntu:
```bash
sudo apt update && sudo apt install python3 python3-pip
```

Fedora:
```bash
sudo dnf install python3 python3-pip
```

Arch:
```bash
sudo pacman -S python python-pip
```

```bash
python3 --version
```

### Installing dependencies

```bash
pip install -r requirements.txt
```

A virtual environment is recommended:

```bash
python -m venv myenv
# Windows: myenv\Scripts\activate
# Linux:   source myenv/bin/activate
pip install -r requirements.txt
```

## Usage

### First run

```bash
python jellydown.py
```

You'll be prompted (in a regular terminal prompt, before the TUI starts) for:

1. **Server URL**, e.g. `http://192.168.1.100:8096`. If you omit the port the tool offers to add `8096`.
2. **Authentication** — username/password (a token is generated and saved) or an existing API key from your Jellyfin Dashboard.

Once authenticated, the TUI launches. Settings, server URL, and the auth token are persisted to `jellydown.json` next to the script.

### TUI layout

```
┌───────────── Library ──────────────┐┌──── Downloads ────┐
│ ▼ Library                          ││ File  Status  …   │
│   ▶ Series                         ││                   │
│   ▼ Movies                         ││                   │
│       Arrival                      ││                   │
│   ▶ Settings                       ││                   │
└────────────────────────────────────┘└───────────────────┘
 ← Collapse  → Expand  space Mark  d Download  c Cancel  r Remove  s Settings  ? Help  q Quit
```

### Library tree (left pane)

| Key | Action |
| --- | --- |
| `↑` / `↓` | Move cursor |
| `→` | Expand the focused branch, or descend to its first child |
| `←` | Collapse the focused branch, or ascend to its parent |
| `PageUp/Down` | Page through long lists |
| `space` | Toggle a mark on the focused movie/episode (shown as `[*]`) |
| `Enter` | Download the focused item (opens the modal). On a setting leaf, edit it. |
| `d` | Download all marked items, or the focused item if nothing is marked |

Tree branches are loaded lazily — series→seasons→episodes are fetched on first expand.

### Downloads pane (right pane)

| Key | Action |
| --- | --- |
| `↑` / `↓` | Focus a row |
| `c` | Cancel the focused download |
| `r` | Remove a finished/cancelled row |

### Download dialog

Triggered by Enter or `d`. Output directory, audio language, and subtitle choice are pre-filled from your config and from the actual tracks on the selected item(s).

| Key | Action |
| --- | --- |
| `↑` / `↓` | Move between fields (output dir → audio → subtitle → Cancel → Download, with wrap) |
| `Enter` | Activate the focused field — opens a Select dropdown, or submits the form on the Download button |
| `d` | Start the download |
| `c` / `Esc` | Cancel the dialog |
| `a` | Jump to the audio field |
| `s` | Jump to the subtitle field |

The audio and subtitle dropdowns list the language codes actually present on the selected items (union across a batch). Subtitle has **None** and **All** at the top in addition to the per-language options.

### Settings (in the tree)

Open with `s` or by expanding the **Settings** branch. Each setting is a leaf showing `Field: current value`.

| Key | Action |
| --- | --- |
| Enter | Begin editing — an edit bar appears at the bottom of the screen, prefilled with the current value |
| Enter (in the edit bar) | Save the new value |
| Esc | Cancel the edit without saving |

Editable fields:

- **Video codec** — `h264` (compatible) or `hevc` (efficient, needs hardware support)
- **Audio codec** — `aac`, `mp3`, `ac3`, `opus`
- **Video bitrate** — bits/sec; `0` means "always download original, no transcoding"
- **Audio bitrate** — bits/sec
- **Max audio channels**
- **Preferred audio language** — 3-letter code; pre-selects the matching track in the download dialog
- **Preferred subtitle language** — same, for subtitles
- **Parallel downloads** — number of items downloaded concurrently (1–16)

Editing **Video bitrate** also updates `MaxStreamingBitrate` to the same value.

### Help

`?` opens an in-app keybindings reference. `q` quits.

### Classic CLI (legacy)

The pre-TUI text-menu interface is still available for scripting or low-feature terminals:

```bash
python jellydown.py --classic
```

The classic flow is the original numeric-menu walkthrough: pick Series/Movies, paginate (`n`/`p`), pick by number, choose subtitles, optionally pick how many consecutive episodes to grab.

## Configuration file

Settings are stored in `jellydown.json` next to the script:

```json
{
  "server_url": "http://your-server:8096",
  "api_key": "your-token",
  "VideoCodec": "h264",
  "AudioCodec": "aac",
  "VideoBitrate": 4000000,
  "MaxStreamingBitrate": 4000000,
  "AudioBitrate": 128000,
  "MaxAudioChannels": 2,
  "SubtitleMethod": "Encode",
  "PreferredAudioLanguage": "eng",
  "PreferredSubtitleLanguage": "eng",
  "ParallelDownloads": 2,
  "download_path": "/path/to/downloads"
}
```

The file is gitignored by default (it contains an access token).

### Redirecting the config path

Set `JELLYDOWN_CONFIG_FILE` to point reads and writes at a different file. Useful for tests, scripting against multiple servers, or development:

```bash
JELLYDOWN_CONFIG_FILE=/tmp/jellydown-test.json python jellydown.py
```

## Tips

- **Always-original downloads**: set Video Bitrate to `0` in Settings.
- **Quality presets** (Mbps): 4 = decent 1080p, 8–15 = high-quality 1080p, 20+ = high-quality 4K.
- **Skip-transcode rule**: if the original file is already smaller (within 5%) than the transcoded result would be, the original is downloaded directly. Logged when it happens.
- **Cancellable downloads**: hit `c` on the focused download row at any time. The partially-written file is removed.

## Troubleshooting

### "Authentication failed"

- Double-check username/password.
- Confirm the server URL is reachable from this machine.
- Try an API key (Jellyfin Dashboard → API Keys) instead of username/password.

### Slow downloads

- Speed depends on your link to the server.
- Server-side transcoding is CPU-intensive — try Video Bitrate `0` to skip transcoding.

### TUI looks broken

- The download dialog needs ~70 columns. If your terminal is narrower, widen it.
- Set the `TERM` env var to a sensible value (e.g. `xterm-256color`) if colors are wrong.

### Reset configuration

Delete `jellydown.json` (or whatever `JELLYDOWN_CONFIG_FILE` points to). On next launch you'll be re-prompted for everything.

## License

See [LICENSE](LICENSE).
