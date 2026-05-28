# yt-dlp extractor plugins

A [yt-dlp](https://github.com/yt-dlp/yt-dlp) custom extractor plugin package for **PimpBunny**, **TransHub**, **X-TG**, **NSFW247**, and more.

## Supported URLs

- `https://pimpbunny.com/videos/<slug>/`
- `https://pimpbunny.com/<lang>/videos/<slug>/`
- `https://transhub.to/<category>/<slug>/`
- `https://x-tg.tube/video/<id>/<slug>/`
- `https://x-tg.tube/embed/<id>`
- `https://x-tg.tube/models/<slug>/`
- `https://nsfw247.to/<slug>/`

## Features

- Extracts multiple quality formats (when available)
- Parses metadata: title, uploader/cast, thumbnail, description, duration, upload date, tags, categories
- Handles geo-restricted `function/` URLs via locale fallback
- Supports JSON-LD, player config, and OpenGraph metadata sources
- Extracts TransHub embeds from LuluVdo/LuluVdoo/LuluVid/LuluStream, Streamtape, Dooodster, Vidply/Playmogo/Do7go, and VOE iframe pages
- Extracts X-TG KVS player formats and model playlists through `curl-cffi` browser impersonation
- Extracts NSFW247 FluidPlayer MP4 pages without duplicate `noscript` playlist entries

## Installation

Requires **yt-dlp** `2023.01.02` or above.

Some TransHub embeds and X-TG pages require browser impersonation. The pip install includes a yt-dlp-compatible
`curl-cffi` version automatically. If you install the plugin manually by copying files, install it in the same
environment too:

```bash
python -m pip install -U "curl-cffi>=0.10,<0.15"
```

### pip (recommended)

```bash
python -m pip install -U "git+https://github.com/Leizer-San/yt-dlp-custom-extractors.git"
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
yt-dlp "https://x-tg.tube/video/371176/example-video/"
```

```bash
yt-dlp "https://x-tg.tube/models/example-model/"
```

```bash
yt-dlp "https://nsfw247.to/example-video/"
```

```bash
# List available formats
yt-dlp -F "https://pimpbunny.com/videos/example-video/"
```

## Development

See the [Plugin Development](https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development) section of the yt-dlp wiki.

## License

[Unlicense](LICENSE)
