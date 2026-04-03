# yt-dlp-pimpbunny-extractor

A [yt-dlp](https://github.com/yt-dlp/yt-dlp) extractor plugin for **PimpBunny**.

## Supported URLs

- `https://pimpbunny.com/videos/<slug>/`
- `https://pimpbunny.com/<lang>/videos/<slug>/`

## Features

- Extracts multiple quality formats (when available)
- Parses metadata: title, uploader/cast, thumbnail, description, duration, upload date, tags, categories
- Handles geo-restricted `function/` URLs via locale fallback
- Supports JSON-LD, player config, and OpenGraph metadata sources

## Installation

Requires **yt-dlp** `2023.01.02` or above.

### pip (recommended)

```bash
python -m pip install -U "git+https://github.com/Leizer-San/yt-dlp-pimpbunny-extractor.git"
```

### Manual

Download the latest release and place the `yt_dlp_plugins` folder in one of the [plugin directories](https://github.com/yt-dlp/yt-dlp#installing-plugins) recognized by yt-dlp.

## Usage

```bash
yt-dlp "https://pimpbunny.com/videos/example-video/"
```

```bash
# List available formats
yt-dlp -F "https://pimpbunny.com/videos/example-video/"
```

## Development

See the [Plugin Development](https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development) section of the yt-dlp wiki.

## License

[Unlicense](LICENSE)
