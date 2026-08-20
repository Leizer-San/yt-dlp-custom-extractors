"""Morencius extractor -- covers morencius.com (VidHide clone).

morencius.com uses the same engine as vidhide.com:
- Packed JS (Dean Edwards p,a,c,k,e,d) in the embed page
- JWPlayer with HLS sources
- CDN hosted on dramiyos-cdn.com / g7bomypteq4g.space
"""
import re
from html import unescape

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import float_or_none


_MORENCIUS_VALID_URL = (
    r"https?://(?:www\.)?morencius\.com/"
    r"(?:embed|e|v)/(?P<id>[A-Za-z0-9]+)"
)

_ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_META_RE = re.compile(r"<meta\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_PACKED_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\).+?\}\s*\(\s*'(?P<p>(?:[^'\\]|\\.)*)'\s*,\s*(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*'(?P<k>(?:[^'\\]|\\.)*)'\s*\.split\('\|'\)",
    re.DOTALL,
)
_HLS_RE = re.compile(
    r'(?:file\s*:\s*|["\'])(https?://[^"\']+\.m3u8[^"\']*)["\']',
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


class MorenciusIE(InfoExtractor):
    IE_NAME = "morencius"
    IE_DESC = "Morencius (morencius.com)"
    _VALID_URL = _MORENCIUS_VALID_URL

    _TESTS = [{
        "url": "https://morencius.com/embed/2oikevkycxhe",
        "info_dict": {
            "id": "2oikevkycxhe",
            "ext": "mp4",
            "title": str,
            "age_limit": 18,
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        embed_url = re.sub(r"/(?:v|e)/", "/embed/", url)

        webpage = self._download_webpage(
            embed_url,
            video_id,
            headers={"Referer": url},
        )

        title = (
            _strip_or_none(_search_meta(webpage, "og:title"))
            or _strip_or_none(_search_meta(webpage, "description"))
            or self._html_search_regex(
                r"<title>([^<]+)</title>", webpage, "title", default=video_id,
            )
        )

        thumbnail = _strip_or_none(_search_meta(webpage, "og:image"))

        unpacked = _decode_packed(webpage) or webpage

        # Extract M3U8 URLs from unpacked JS
        hls_urls = []
        seen = set()
        for m in _HLS_RE.finditer(unpacked):
            hls_url = _strip_or_none(m.group(1))
            if hls_url and hls_url not in seen:
                seen.add(hls_url)
                hls_urls.append(hls_url)

        dur_m = _DURATION_RE.search(unpacked)
        duration = float_or_none(dur_m.group(1)) if dur_m else None

        if not hls_urls:
            self.raise_no_formats(
                "Could not find downloadable media in Morencius page", expected=True
            )

        formats = []
        for hls_url in hls_urls:
            fmts = self._extract_m3u8_formats(
                hls_url, video_id, ext="mp4",
                entry_protocol="m3u8_native", m3u8_id="hls", fatal=False,
                headers={"Referer": embed_url},
            )
            formats.extend(fmts)

        return {
            "id": video_id,
            "title": title or video_id,
            "thumbnail": thumbnail,
            "duration": duration,
            "formats": formats,
            "age_limit": 18,
        }
