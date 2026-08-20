"""LuluVids extractor -- covers luluvids.top (LuluStream clone).

luluvids.top is structurally identical to lulustream.com:
- Same jQuery-cookie file_id pattern
- Same tnmr.org CDN
- Same /e/<id> embed URL format
- Sources are hidden inside a Dean-Edwards p,a,c,k,e,d packed JS block
"""
import re
from html import unescape

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import float_or_none


_LULUVIDS_VALID_URL = (
    r"https?://(?:www\.)?luluvids\.top/"
    r"(?:e|embed|v|d)/(?P<id>[A-Za-z0-9]+)"
)

_ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_META_RE = re.compile(r"<meta\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_CDN_BAD_CERT_RE = re.compile(
    r"https?://[^/?#]+\.cdn-tnmr\.org(?::\d+)?(?:[/?#]|$)", re.IGNORECASE
)

_PACKED_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\).+?\}\s*\(\s*'(?P<p>(?:[^'\\]|\\.)*)'\s*,\s*(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*'(?P<k>(?:[^'\\]|\\.)*)'\s*\.split\('\|'\)",
    re.DOTALL,
)

_HLS_RE = re.compile(
    r'(?:file\s*:\s*|["\'])(https?://[^"\']+\.m3u8[^"\']*)["\']',
    re.IGNORECASE,
)
_MP4_RE = re.compile(
    r'(?:file\s*:\s*|["\'])(https?://[^"\']+\.mp4[^"\']*)["\']',
    re.IGNORECASE,
)
_DURATION_RE = re.compile(r'duration\s*:\s*["\']?([0-9.]+)["\']?', re.IGNORECASE)

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _unbase(val, radix):
    res = 0
    for char in val:
        res = res * radix + _ALPHABET.index(char)
    return res


def _decode_packed(webpage):
    m = _PACKED_RE.search(webpage)
    if not m:
        return None
    p = m.group('p')
    a = int(m.group('a'))
    k = m.group('k').split('|')

    def replacer(match):
        word = match.group(0)
        try:
            idx = _unbase(word, a)
            if idx < len(k) and k[idx]:
                return k[idx]
        except Exception:
            pass
        return word

    return re.sub(r'\b\w+\b', replacer, p)


def _strip_or_none(value):
    if not isinstance(value, str):
        return None
    value = unescape(value).replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _search_meta(webpage, name):
    name = name.lower()
    for m in _META_RE.finditer(webpage):
        attrs = {
            match.group("name").lower(): _strip_or_none(match.group("value"))
            for match in _ATTR_RE.finditer(m.group("attrs") or "")
        }
        if (attrs.get("property") or attrs.get("name") or "").lower() == name:
            return _strip_or_none(attrs.get("content"))
    return None


def _extract_media(webpage):
    unpacked = _decode_packed(webpage) or webpage

    media = []
    seen = set()
    for pattern, ext in ((_HLS_RE, "m3u8"), (_MP4_RE, "mp4")):
        for m in pattern.finditer(unpacked):
            url = _strip_or_none(m.group(1))
            if url and url not in seen:
                seen.add(url)
                media.append((url, ext))

    return media


class LuluVidsIE(InfoExtractor):
    IE_NAME = "luluvids"
    IE_DESC = "LuluVids (luluvids.top)"
    _VALID_URL = _LULUVIDS_VALID_URL

    _TESTS = [{
        "url": "https://luluvids.top/e/kpkbqqyzoh3o",
        "info_dict": {
            "id": "kpkbqqyzoh3o",
            "ext": "mp4",
            "title": str,
            "age_limit": 18,
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        embed_url = re.sub(r"/(?:d|v)/", "/e/", url)

        webpage = self._download_webpage(
            embed_url,
            video_id,
            headers={"Referer": url},
        )

        title = (
            _strip_or_none(_search_meta(webpage, "og:title"))
            or _strip_or_none(_search_meta(webpage, "twitter:title"))
            or self._html_search_regex(
                r"<title>([^<]+)</title>", webpage, "title", default=video_id,
            )
        )
        if title:
            title = re.sub(
                r"\s*[-|]\s*Lulu(?:Vids|Stream|vdo)\b.*$", "", title,
                flags=re.IGNORECASE,
            ).strip() or title

        thumbnail = (
            _strip_or_none(_search_meta(webpage, "og:image"))
            or _strip_or_none(_search_meta(webpage, "twitter:image"))
        )

        unpacked = _decode_packed(webpage) or webpage
        dur_m = _DURATION_RE.search(unpacked)
        duration = float_or_none(dur_m.group(1)) if dur_m else None

        media = _extract_media(webpage)

        if not media:
            self.raise_no_formats(
                "Could not find downloadable media in LuluVids page", expected=True
            )

        formats = []
        for media_url, ext in media:
            if _CDN_BAD_CERT_RE.match(media_url):
                self.report_warning(
                    "LuluVids CDN certificate does not match its hostname; "
                    "you may need --no-check-certificates"
                )
            if ext == "m3u8":
                fmts = self._extract_m3u8_formats(
                    media_url, video_id, ext="mp4",
                    entry_protocol="m3u8_native", m3u8_id="hls", fatal=False,
                    headers={"Referer": embed_url},
                )
                formats.extend(fmts)
            else:
                formats.append({
                    "url": media_url,
                    "ext": ext,
                    "http_headers": {"Referer": embed_url},
                })

        return {
            "id": video_id,
            "title": title or video_id,
            "thumbnail": thumbnail,
            "duration": duration,
            "formats": formats,
            "age_limit": 18,
        }
