# F5-TTS Hotkey

Select text anywhere, press **Alt+X**, hear it spoken aloud — powered by [F5-TTS](https://github.com/SWivid/F5-TTS).

## Features

- **Global hotkey** — works in any app (browser, editor, PDF, etc.)
- **Voice cloning** — uses a reference audio to clone the speaker's voice
- **Zero UI** — no need to switch windows, just select + hotkey
- **Gradio backend** — runs on top of F5-TTS's built-in Gradio server

## Requirements

- Windows 10/11
- Python 3.10+ (conda environment recommended)
- F5-TTS installed and working ([guide](https://github.com/SWivid/F5-TTS))

## Quick Start

1. Install dependencies:
   ```
   pip install sounddevice soundfile requests
   ```

2. Edit `f5_tts_hotkey.py` — set your `GRADIO_URL` and `REF_AUDIO` path

3. Double-click `launch.cmd` (or start F5-TTS server separately, then run `python f5_tts_hotkey.py`)

4. Select text anywhere, press **Alt+X**

## Hotkeys

| Key | Action |
|-----|--------|
| `Alt+X` | Speak selected text |
| `Alt+Q` | Quit |

## How It Works

1. Detects `Alt+X` via Windows `RegisterHotKey` API
2. Simulates `Ctrl+C` via `SendInput` to copy selected text
3. Sends text to F5-TTS Gradio API (`/gradio_api/call/basic_tts`)
4. Downloads generated audio and plays it via `sounddevice`

## Configuration

Edit the top of `f5_tts_hotkey.py`:

```python
GRADIO_URL = "http://127.0.0.1:7860"  # F5-TTS server URL
REF_AUDIO = "path/to/reference.wav"     # Voice clone reference
```

## License

MIT
