# lyrsmith

An AI-powered terminal UI for transcribing and editing time-synced song lyrics in [LRC format](https://en.wikipedia.org/wiki/LRC_(file_format)).

Point it at a directory, load a track, run Whisper to get a rough transcription, then nudge timestamps until they're right. Saves directly to the audio file's tags.

## Features

- **AI transcription** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — runs locally, no cloud
- **Waveform display** for visual timing reference
- **LRC timestamp editing** — stamp, nudge (fine/medium/rough), merge, split, delete, undo
- **Plain text mode** for unsynced lyrics
- Reads and writes lyrics tags on **MP3, FLAC, OGG, OPUS**

![lyrsmith screenshot](docs/lyrsmith_screenshot.png)

## Requirements

- Python 3.13+
- **libmpv** (audio playback)
- **FFmpeg libraries** (waveform decoding via PyAV)

On Fedora/RHEL:
```
dnf install mpv-libs ffmpeg-free
```

On Debian/Ubuntu:
```
apt install libmpv-dev ffmpeg
```

## Install

From source using [uv](https://docs.astral.sh/uv/):

```
git clone https://github.com/triluch/lyrsmith
cd lyrsmith
uv tool install .
```

Or with pipx:

```
pipx install .
```

## Usage

```
lyrsmith [DIRECTORY]
```

If no directory is given, the last-used directory is restored (or the current working directory on first run).

Due to how Whisper works, the first transcribed line always gets timestamp 0:00 regardless of when vocals start. Stamp it manually.

---

And yeah, of course it is slopped out, what did you expect in current times?
