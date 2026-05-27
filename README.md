# yt-dlp extractor plugins

A [yt-dlp](https://github.com/yt-dlp/yt-dlp) extractor plugin package for **PimpBunny** and **TransHub**.

## Supported URLs

- `https://pimpbunny.com/videos/<slug>/`
- `https://pimpbunny.com/<lang>/videos/<slug>/`
- `https://transhub.to/<category>/<slug>/`

## Features

- Extracts multiple quality formats (when available)
- Parses metadata: title, uploader/cast, thumbnail, description, duration, upload date, tags, categories
- Handles geo-restricted `function/` URLs via locale fallback
- Supports JSON-LD, player config, and OpenGraph metadata sources
- Extracts TransHub embeds from LuluVdo/LuluVdoo/LuluVid/LuluStream, Streamtape, and Dooodster iframe pages

## Installation

Requires **yt-dlp** `2023.01.02` or above.

Some TransHub pages use Dooodster embeds protected by Cloudflare. The pip install includes a yt-dlp-compatible
`curl-cffi` version automatically. If you install the plugin manually by copying files, install it in the same
environment too:

```bash
python -m pip install -U "curl-cffi>=0.10,<0.15"
```

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
yt-dlp "https://transhub.to/anal/example-video/"
```

```bash
# List available formats
yt-dlp -F "https://pimpbunny.com/videos/example-video/"
```

## Development

See the [Plugin Development](https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development) section of the yt-dlp wiki.

## License

[Unlicense](LICENSE)
