# JellyfinDownloader

A Python script for downloading movies and TV series from your Jellyfin media server. Supports both direct downloads (original files) and transcoded downloads with customizable quality settings.

With hardware-accelerated transcoding support, you can optimize downloads for your device while minimizing server load. As the transcoding happens like a normal Jellyfin stream, you can take advantage of your server's hardware capabilities. The streaming typically goes 10-20x faster than real-time, making downloads quick and efficient.

## Features

- **Flexible Download Options**: Download original files or transcode to your preferred quality
- **Smart Transcoding**: Automatically skips transcoding if the original file is already optimal
- **Series Support**: Download multiple episodes in sequence
- **Customizable Settings**: Configure video/audio codecs, bitrates, and channels
- **Persistent Configuration**: Remembers your server, credentials, and download preferences
- **Progress Tracking**: Visual progress indicators for downloads

## Prerequisites

### Required Software

1. **Python 3.7+**
2. **FFmpeg** (required for transcoded downloads)
3. **Python packages**: `requests` (automatically installed)

### Installing Python

#### Windows

**Option 1: Using winget (Recommended)**
```powershell
winget install Python.Python.3.12
```

**Option 2: Microsoft Store**
1. Open the Microsoft Store app
2. Search for "Python 3.12" (or latest version)
3. Click "Get" or "Install"

**Option 3: Official Installer**
1. Download from [python.org](https://www.python.org/downloads/)
2. Run the installer
3. **Important**: Check "Add Python to PATH" during installation

**Verify installation:**
```powershell
python --version
```

#### Linux

**Debian/Ubuntu:**
```bash
sudo apt update
sudo apt install python3 python3-pip
```

**Fedora:**
```bash
sudo dnf install python3 python3-pip
```

**Arch Linux:**
```bash
sudo pacman -S python python-pip
```

**Verify installation:**
```bash
python3 --version
```

### Installing FFmpeg

#### Windows

**Option 1: Using winget (Recommended)**
```powershell
winget install Gyan.FFmpeg
```

**Option 2: Manual Installation**
1. Download FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html)
2. Extract the archive to a location (e.g., `C:\ffmpeg`)
3. Add the `bin` folder to your system PATH

**Note**: The script automatically searches for FFmpeg in the WinGet packages directory if it's not in your PATH.

#### Linux

**Debian/Ubuntu:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Fedora:**
```bash
sudo dnf install ffmpeg
```

**Arch Linux:**
```bash
sudo pacman -S ffmpeg
```

**From source:**
```bash
# Check your distribution's documentation for building from source
```

### Installing Python Dependencies

```bash
pip install requests
```

Or if you're using Python 3 specifically:
```bash
pip3 install requests
```

## Usage

### First Run

1. Run the script:
   ```bash
   python jellydown.py
   ```
   Or on Linux:
   ```bash
   python3 jellydown.py
   ```

2. Enter your Jellyfin server URL (e.g., `http://192.168.1.100:8096`)

3. Choose authentication method:
   - **Username/Password** (recommended): Generates an access token
   - **API Key**: Use an existing API key from Jellyfin

4. The script will save your configuration to `jellydown.json`

### Main Menu

```
1. Series    - Browse and download TV series
2. Movies    - Browse and download movies
3. Settings  - Configure transcoding options
q. Quit
```

### Downloading Content

1. Select **Series** or **Movies**
2. Browse through the available content (use `n`/`p` for pagination)
3. Select an item by entering its number
4. Review the stream URL
5. Type `y` to download
6. For series: Choose how many episodes to download in sequence
7. Specify output directory (or press Enter to use the saved path)

### Settings

Configure transcoding options in the Settings menu:

- **Video Codec**: H.264 (compatible) or H.265 (efficient, requires hardware support)
- **Audio Codec**: AAC (recommended), MP3, AC3, or OPUS
- **Video Bitrate**: Set quality (higher = better quality, larger files)
  - Set to **0** to always download original files without transcoding
- **Audio Bitrate**: Audio quality setting
- **Max Audio Channels**: Maximum number of audio channels

### Tips

- **Original Files**: Set Video Bitrate to `0` in Settings to always download original files
- **Batch Downloads**: When downloading series, you can specify how many consecutive episodes to download
- **Quality Presets**: 
  - 4 Mbps (default): Good quality for 1080p content
  - 8-15 Mbps: High quality for 1080p
  - 20+ Mbps: Very high quality or 4K content
- **Storage**: The script automatically skips transcoding if your original file is already smaller than the transcoded version would be

## Configuration File

Settings are stored in `jellydown.json`:

```json
{
  "VideoCodec": "h264",
  "AudioCodec": "aac",
  "VideoBitrate": 4000000,
  "MaxStreamingBitrate": 4000000,
  "AudioBitrate": 128000,
  "MaxAudioChannels": 2,
  "SubtitleMethod": "Encode",
  "server_url": "http://your-server:8096",
  "api_key": "your-api-key",
  "download_path": "/path/to/downloads"
}
```

## Troubleshooting

### "ffmpeg not found"
- **Windows**: Make sure FFmpeg is installed via winget or added to PATH
- **Linux**: Install ffmpeg using your package manager

### "Authentication failed"
- Verify your username and password
- Check that your Jellyfin server is accessible
- Try using an API key instead (generate one in Jellyfin Dashboard → API Keys)

### Downloads are slow
- You're downloading from your Jellyfin server - speed depends on your network
- Transcoding (when enabled) is CPU-intensive on the server side
- Consider downloading original files (set bitrate to 0) if server performance is an issue

### Last resort - remove the configuration file
- Delete `jellydown.json` to reset all settings and reconfigure

## License

See [LICENSE](LICENSE) file for details.
