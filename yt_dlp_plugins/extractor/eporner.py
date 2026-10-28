import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import int_or_none, parse_duration, str_to_int


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

    def _real_extract(self, url):
        match = self._match_valid_url(url)
        video_id = match.group("id")
        display_id = match.group("display_id") or video_id
        webpage, urlh = self._download_webpage_handle(url, display_id)
        page_url = urlh.url

        formats = _extract_download_formats(webpage, page_url)
        if not formats:
            self.raise_no_formats("Could not find MP4 download links in Eporner page", expected=True)

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
