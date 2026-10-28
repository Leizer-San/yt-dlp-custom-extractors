import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.networking import HEADRequest
from yt_dlp.utils import encode_base_n, int_or_none, parse_duration, str_to_int, url_or_none


_VALID_URL = (
    r"https?://(?:www\.)?eporner\.com/"
    r"(?:(?:hd-porn|embed)/|video-)"
    r"(?P<id>[\w]+)"
    r"(?:/(?P<display_id>[\w-]+))?"
)


class _DownloadLinksParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._div_depth = 0
        self._inside_downloads = False
        self._anchor = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self._div_depth += 1
            if attrs.get("id") == "downloaddiv":
                self._inside_downloads = True
                self._download_depth = self._div_depth
        elif tag == "a" and self._inside_downloads and attrs.get("href"):
            self._anchor = {"url": attrs["href"], "text": ""}

    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            self.links.append(self._anchor)
            self._anchor = None
        elif tag == "div" and self._inside_downloads:
            if self._div_depth == self._download_depth:
                self._inside_downloads = False
            self._div_depth = max(0, self._div_depth - 1)
        elif tag == "div":
            self._div_depth = max(0, self._div_depth - 1)


def _extract_download_formats(webpage, page_url):
    parser = _DownloadLinksParser()
    parser.feed(webpage)
    formats = []
    seen = set()

    for link in parser.links:
        media_url = urljoin(page_url, unescape(link["url"]).strip())
        path = urlsplit(media_url).path
        if not path.lower().endswith(".mp4") or media_url in seen:
            continue
        seen.add(media_url)

        filename = path.rsplit("/", 1)[-1]
        height_match = re.search(r"(?:^|[/_-])(\d{3,4})p(?:[/_.-]|$)", path, re.IGNORECASE)
        if not height_match:
            height_match = re.search(r"/(\d{3,4})/", path)
        if not height_match:
            continue
        height = int(height_match.group(1))

        is_av1 = bool(re.search(r"(?:-av1|\bav1\b)", filename + " " + link["text"], re.IGNORECASE))
        codec = "av1" if is_av1 else "h264"
        formats.append({
            "url": media_url,
            "format_id": f"{height}p-{codec}",
            "ext": "mp4",
            "height": height,
            "vcodec": codec,
            "http_headers": {"Referer": page_url},
        })

    return formats


class EpornerIE(InfoExtractor):
    IE_NAME = "eporner"
    _VALID_URL = _VALID_URL

    def _extract_player_formats(self, webpage, video_id, display_id, page_url):
        video_hash = self._search_regex(
            r"hash\s*[:=]\s*['\"]([\da-f]{32})",
            webpage, "video hash", default=None)
        if not video_hash:
            return []

        api_hash = "".join(
            encode_base_n(int(video_hash[offset:offset + 8], 16), 36)
            for offset in range(0, 32, 8))
        video = self._download_json(
            f"https://www.eporner.com/xhr/video/{video_id}",
            display_id,
            note="Downloading player video sources",
            query={
                "hash": api_hash,
                "device": "generic",
                "domain": "www.eporner.com",
                "fallback": "false",
            },
            fatal=False,
        )
        if not isinstance(video, dict) or video.get("available") is False:
            return []

        formats = []
        for kind, sources in (video.get("sources") or {}).items():
            if not isinstance(sources, dict):
                continue
            for format_id, source in sources.items():
                if not isinstance(source, dict):
                    continue
                media_url = url_or_none(source.get("src"))
                if not media_url:
                    continue
                if kind == "hls":
                    formats.extend(self._extract_m3u8_formats(
                        media_url, display_id, ext="mp4", m3u8_id="hls",
                        fatal=False, headers={"Referer": page_url}))
                    continue

                height = int_or_none(self._search_regex(
                    r"(\d{3,4})p", format_id, "height", default=None))
                fps = int_or_none(self._search_regex(
                    r"(\d+)fps", format_id, "fps", default=None))
                formats.append({
                    "url": media_url,
                    "format_id": format_id,
                    "height": height,
                    "fps": fps,
                    "http_headers": {"Referer": page_url},
                })
        return formats

    def _download_links_require_login(self, formats, video_id):
        if not formats:
            return False
        response = self._request_webpage(
            HEADRequest(formats[0]["url"]),
            video_id,
            note="Checking Eporner download link access",
            errnote=False,
            fatal=False,
        )
        return not response or "/login/" in response.url.lower()

    def _real_extract(self, url):
        match = self._match_valid_url(url)
        video_id = match.group("id")
        display_id = match.group("display_id") or video_id
        webpage, urlh = self._download_webpage_handle(url, display_id)
        page_url = urlh.url

        formats = _extract_download_formats(webpage, page_url)
        if self._download_links_require_login(formats, display_id):
            self.report_warning(
                "Eporner download links require login; falling back to public player sources")
            formats = self._extract_player_formats(webpage, video_id, display_id, page_url)
        if not formats:
            self.raise_no_formats("Could not find accessible video formats in Eporner page", expected=True)

        title = (
            self._og_search_title(webpage, default=None)
            or self._html_search_regex(r"<title>(.*?)</title>", webpage, "title", default=display_id)
        )
        title = re.sub(r"\s*-\s*EPORNER\s*$", "", unescape(title), flags=re.IGNORECASE).strip()
        description = self._og_search_description(webpage, default=None)
        thumbnail = self._og_search_thumbnail(webpage, default=None) or self._search_regex(
            r"<video\b[^>]*\bposter=['\"]([^'\"]+)", webpage, "thumbnail", default=None)
        duration = parse_duration(self._html_search_meta("duration", webpage, default=None))
        view_count = str_to_int(self._search_regex(
            r"id=['\"]cinemaviews1['\"][^>]*>\s*([0-9,]+)",
            webpage, "view count", default=None))

        return {
            "id": video_id,
            "display_id": display_id,
            "title": title,
            "description": description,
            "thumbnail": thumbnail,
            "duration": duration,
            "view_count": view_count,
            "formats": formats,
            "age_limit": 18,
        }
