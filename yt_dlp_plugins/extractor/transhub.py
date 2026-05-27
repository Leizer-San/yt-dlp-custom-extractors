import random
import re
import string
import time
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import decode_packed_codes, float_or_none


_TRANSHUB_VALID_URL = (
    r"https?://(?:www\.)?transhub\.to/"
    r"(?P<section>[^/?#]+)/(?P<id>[^/?#]+)/?"
    r"(?:[?#].*)?$"
)
_LULU_VALID_URL = (
    r"https?://(?:www\.)?(?:luluvdo|luluvdoo|luluvid|lulustream)\.com/"
    r"(?:e|embed|v|d)/(?P<id>[A-Za-z0-9]+)"
)
_LULU_URL_RE = re.compile(_LULU_VALID_URL, re.IGNORECASE)
_STREAMTAPE_VALID_URL = r"https?://(?:www\.)?streamtape\.com/(?:e|v)/(?P<id>[^/?#]+)"
_STREAMTAPE_URL_RE = re.compile(_STREAMTAPE_VALID_URL, re.IGNORECASE)
_DOODSTER_VALID_URL = (
    r"https?://(?:www\.)?(?:dooodster|vidply|playmogo)\.com/"
    r"(?:e|d)/(?P<id>[^/?#]+)"
)
_DOODSTER_URL_RE = re.compile(_DOODSTER_VALID_URL, re.IGNORECASE)
_STREAMTAPE_VIDEO_LINK_RE = re.compile(
    r"<(?:div|span)[^>]+id=[\"'](?P<id>robotlink|botlink)[\"'][^>]*>(?P<url>//[^<]+)</",
    re.IGNORECASE,
)
_STREAMTAPE_JS_LINK_RE = re.compile(
    r"getElementById\([\"'](?P<id>robotlink|botlink)[\"']\)\.innerHTML\s*=\s*"
    r"(?P<quote>[\"'])(?P<prefix>//[^\"']+)(?P=quote)\s*\+\s*(?:[\"'][\"']\s*\+\s*)?"
    r"\([\"'](?P<suffix>[^\"']+)[\"']\)(?P<substrings>(?:\.substring\(\d+\))+)",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_IFRAME_RE = re.compile(r"<iframe\b(?P<attrs>[^>]+)>", re.IGNORECASE)
_LINK_RE = re.compile(r"<link\b(?P<attrs>[^>]+)>", re.IGNORECASE)
_META_RE = re.compile(r"<meta\b(?P<attrs>[^>]+)>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>(?P<value>.*?)</title>", re.IGNORECASE | re.DOTALL)
_ENTRY_TITLE_RE = re.compile(
    r"<h1\b[^>]*class=[\"'][^\"']*\bentry-title\b[^\"']*[\"'][^>]*>(?P<value>.*?)</h1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_ANCHOR_RE = re.compile(
    r"<a\b[^>]+href=[\"']https?://(?:www\.)?transhub\.to/tag/[^\"']+[\"'][^>]*>"
    r"(?P<value>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_PACKED_JS_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\).*?(?:</script>|$)",
    re.IGNORECASE | re.DOTALL,
)
_MEDIA_URL_RE = re.compile(
    r"https?://[^\"'<>\\\s]+\.(?:m3u8|mp4)(?:\?[^\"'<>\\\s]*)?",
    re.IGNORECASE,
)
_JW_IMAGE_RE = re.compile(r"\bimage\s*:\s*[\"'](?P<url>https?://[^\"']+)", re.IGNORECASE)
_JW_DURATION_RE = re.compile(r"\bduration\s*:\s*[\"']?(?P<value>\d+(?:\.\d+)?)", re.IGNORECASE)
_DOODSTER_PASS_MD5_RE = re.compile(r"(?P<url>/pass_md5/[^\"'<>\\\s]+)", re.IGNORECASE)
_DOODSTER_TOKEN_RE = re.compile(r"[?&]token=(?P<token>[A-Za-z0-9]+)", re.IGNORECASE)


def _strip_or_none(value):
    if not isinstance(value, str):
        return None
    value = unescape(value).replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _clean_html_text(value):
    value = _strip_or_none(value)
    if not value:
        return None
    return _strip_or_none(re.sub(r"<[^>]+>", " ", value))


def _clean_title(value):
    value = _clean_html_text(value)
    if not value:
        return None
    return _strip_or_none(re.sub(r"\s*-\s*TransHub\s*$", "", value, flags=re.IGNORECASE))


def _url_or_none(url):
    url = _strip_or_none(url)
    if not url:
        return None
    if url.startswith("//"):
        url = f"https:{url}"
    if not re.match(r"https?://", url, re.IGNORECASE):
        return None
    return url


def _extract_attrs(attrs_text):
    return {
        match.group("name").lower(): _strip_or_none(match.group("value"))
        for match in _ATTR_RE.finditer(attrs_text or "")
    }


def _search_meta(webpage, name):
    name = name.lower()
    for match in _META_RE.finditer(webpage):
        attrs = _extract_attrs(match.group("attrs"))
        if (attrs.get("property") or attrs.get("name") or "").lower() != name:
            continue
        return _strip_or_none(attrs.get("content"))
    return None


def _search_title(webpage):
    match = _TITLE_RE.search(webpage)
    if not match:
        return None
    return _clean_title(match.group("value"))


def _search_entry_title(webpage):
    match = _ENTRY_TITLE_RE.search(webpage)
    if not match:
        return None
    return _clean_title(match.group("value"))


def _search_canonical(webpage):
    for match in _LINK_RE.finditer(webpage):
        attrs = _extract_attrs(match.group("attrs"))
        rel = attrs.get("rel") or ""
        if "canonical" not in rel.lower().split():
            continue
        return _url_or_none(attrs.get("href"))
    return None


def _is_supported_embed_url(url):
    return bool(
        _LULU_URL_RE.match(url or "")
        or _STREAMTAPE_URL_RE.match(url or "")
        or _DOODSTER_URL_RE.match(url or "")
    )


def _guess_embed_id(url):
    for pattern in (_LULU_URL_RE, _STREAMTAPE_URL_RE, _DOODSTER_URL_RE):
        match = pattern.match(url or "")
        if match:
            return match.group("id")
    return None


def _extract_video_embed_url(webpage):
    for match in _IFRAME_RE.finditer(webpage):
        attrs = _extract_attrs(match.group("attrs"))
        for attr_name in ("data-litespeed-src", "data-src", "data-lazy-src", "src"):
            candidate = _url_or_none(attrs.get(attr_name))
            if candidate and _is_supported_embed_url(candidate):
                return candidate

    for pattern in (_LULU_URL_RE, _STREAMTAPE_URL_RE, _DOODSTER_URL_RE):
        match = pattern.search(webpage)
        if match:
            return match.group(0)
    return None


def _parse_timestamp(value):
    value = _strip_or_none(value)
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _upload_date(timestamp):
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d")


def _extract_tags(webpage):
    tags = []
    seen = set()
    for match in _TAG_ANCHOR_RE.finditer(webpage):
        tag = _clean_html_text(match.group("value"))
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _section_to_category(section):
    section = _strip_or_none(section)
    if not section:
        return None
    return section.replace("-", " ").title()


def _guess_display_id(url):
    match = re.match(_TRANSHUB_VALID_URL, url or "", re.IGNORECASE)
    return match.group("id") if match else None


def _guess_section(url):
    match = re.match(_TRANSHUB_VALID_URL, url or "", re.IGNORECASE)
    return match.group("section") if match else None


def parse_transhub_html(webpage, url):
    canonical_url = _search_canonical(webpage) or url
    display_id = _guess_display_id(canonical_url) or _guess_display_id(url)
    embed_url = _extract_video_embed_url(webpage)
    if not embed_url:
        raise ValueError("Could not find video embed URL in TransHub page")

    title = (
        _search_entry_title(webpage)
        or _clean_title(_search_meta(webpage, "og:title"))
        or _clean_title(_search_meta(webpage, "twitter:title"))
        or _search_title(webpage)
    )
    if not title:
        raise ValueError("Could not find video title in TransHub page")

    timestamp = _parse_timestamp(_search_meta(webpage, "og:updated_time"))
    category = (
        _strip_or_none(_search_meta(webpage, "article:section"))
        or _section_to_category(_guess_section(canonical_url) or _guess_section(url))
    )
    info = {
        "id": display_id or _guess_embed_id(embed_url),
        "display_id": display_id,
        "title": title,
        "description": (
            _strip_or_none(_search_meta(webpage, "description"))
            or _strip_or_none(_search_meta(webpage, "og:description"))
            or _strip_or_none(_search_meta(webpage, "twitter:description"))
        ),
        "thumbnail": (
            _url_or_none(_search_meta(webpage, "og:image"))
            or _url_or_none(_search_meta(webpage, "twitter:image"))
        ),
        "timestamp": timestamp,
        "upload_date": _upload_date(timestamp),
        "categories": [category] if category else None,
        "tags": _extract_tags(webpage),
        "age_limit": 18,
        "webpage_url": canonical_url,
        "embed_url": embed_url,
    }
    return {key: value for key, value in info.items() if value not in (None, [], "")}


def _decode_packed_scripts(webpage):
    decoded = []
    for match in _PACKED_JS_RE.finditer(webpage):
        try:
            decoded.append(decode_packed_codes(match.group(0)))
        except Exception:
            continue
    return decoded


def _extract_luluvdo_media(webpage):
    urls = []
    seen = set()
    for text in [webpage, *_decode_packed_scripts(webpage)]:
        for match in _MEDIA_URL_RE.finditer(text):
            url = _url_or_none(match.group(0))
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _extract_streamtape_video_url(webpage):
    for match in _STREAMTAPE_VIDEO_LINK_RE.finditer(webpage):
        video_url = _url_or_none(match.group("url"))
        if video_url and "/get_video" in video_url:
            return video_url

    for match in _STREAMTAPE_JS_LINK_RE.finditer(webpage):
        suffix = match.group("suffix")
        for offset in re.findall(r"\.substring\((\d+)\)", match.group("substrings")):
            suffix = suffix[int(offset):]
        video_url = _url_or_none(f"{match.group('prefix')}{suffix}")
        if video_url and "/get_video" in video_url:
            return video_url

    return None


def parse_luluvdo_html(webpage, url):
    match = re.match(_LULU_VALID_URL, url, re.IGNORECASE)
    video_id = match.group("id") if match else None
    decoded_scripts = _decode_packed_scripts(webpage)
    decoded_text = "\n".join(decoded_scripts)

    thumbnail = (
        _url_or_none(_search_meta(webpage, "og:image"))
        or _url_or_none(_search_meta(webpage, "twitter:image"))
        or _url_or_none(_JW_IMAGE_RE.search(decoded_text).group("url") if _JW_IMAGE_RE.search(decoded_text) else None)
    )
    duration_match = _JW_DURATION_RE.search(decoded_text)
    return {
        "id": video_id,
        "title": video_id,
        "thumbnail": thumbnail,
        "duration": float_or_none(duration_match.group("value")) if duration_match else None,
        "media_urls": _extract_luluvdo_media(webpage),
    }


class LuluVdoIE(InfoExtractor):
    IE_NAME = "luluvdo"
    _VALID_URL = _LULU_VALID_URL

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(
            url,
            video_id,
            headers={"Referer": "https://transhub.to/"},
        )
        lulu_info = parse_luluvdo_html(webpage, url)

        formats = []
        headers = {"Referer": url}
        media_urls = lulu_info.get("media_urls") or []
        for media_url in media_urls:
            if ".m3u8" in media_url:
                formats.extend(self._extract_m3u8_formats(
                    media_url,
                    video_id,
                    ext="mp4",
                    m3u8_id="hls",
                    fatal=len(media_urls) == 1,
                    headers=headers,
                ))
            else:
                formats.append({
                    "url": media_url,
                    "format_id": "http",
                    "http_headers": headers,
                })

        if not formats:
            self.raise_no_formats("Could not find downloadable media in LuluVdo page", expected=True)

        return {
            "id": video_id,
            "title": lulu_info.get("title") or video_id,
            "thumbnail": lulu_info.get("thumbnail"),
            "duration": lulu_info.get("duration"),
            "formats": formats,
            "http_headers": headers,
        }


class StreamtapeIE(InfoExtractor):
    IE_NAME = "streamtape"
    _VALID_URL = _STREAMTAPE_VALID_URL

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)
        video_url = _extract_streamtape_video_url(webpage)
        if not video_url:
            self.raise_no_formats("Could not find Streamtape video URL", expected=True)

        title = (
            _clean_title(_search_meta(webpage, "og:title"))
            or _search_title(webpage)
            or video_id
        )
        thumbnail = (
            _url_or_none(_search_meta(webpage, "og:image"))
            or _url_or_none(_search_meta(webpage, "twitter:image"))
            or _url_or_none(self._search_regex(
                r"<video[^>]+poster=[\"'](?P<url>[^\"']+)",
                webpage,
                "thumbnail",
                group="url",
                default=None,
            ))
        )
        headers = {"Referer": url}

        return {
            "id": video_id,
            "title": title,
            "thumbnail": thumbnail,
            "formats": [{
                "url": video_url,
                "format_id": "http",
                "ext": "mp4",
                "http_headers": headers,
            }],
            "http_headers": headers,
        }


class DoodsterIE(InfoExtractor):
    IE_NAME = "doodclone"
    _VALID_URL = _DOODSTER_VALID_URL

    def _real_extract(self, url):
        video_id = self._match_id(url)
        embed_url = re.sub(r"/d/", "/e/", url)
        headers = {"Referer": "https://transhub.to/"}
        webpage, urlh = self._download_webpage_handle(
            embed_url,
            video_id,
            headers=headers,
            impersonate=True,
            require_impersonation=True,
        )
        page_url = urlh.url

        pass_md5_url = self._search_regex(
            _DOODSTER_PASS_MD5_RE,
            webpage,
            "Dood-like pass_md5 URL",
            group="url",
        )
        token_match = _DOODSTER_TOKEN_RE.search(pass_md5_url) or _DOODSTER_TOKEN_RE.search(webpage)
        token = token_match.group("token") if token_match else None

        expiry = str(int(time.time() * 1000))
        pass_md5_url = urljoin(page_url, unescape(pass_md5_url))
        if pass_md5_url.endswith("expiry="):
            pass_md5_url += expiry

        video_url_base = self._download_webpage(
            pass_md5_url,
            video_id,
            note="Downloading Dood-like video URL",
            headers={"Referer": page_url},
            impersonate=True,
            require_impersonation=True,
        ).strip()
        video_url_base = _url_or_none(video_url_base) or urljoin(page_url, video_url_base)

        query = f"expiry={expiry}"
        if token:
            query = f"token={token}&{query}"
        video_url = f"{video_url_base}{''.join(random.choices(string.ascii_letters + string.digits, k=10))}?{query}"

        title = (
            _clean_title(_search_meta(webpage, "og:title"))
            or _search_title(webpage)
            or video_id
        )
        thumbnail = (
            _url_or_none(_search_meta(webpage, "og:image"))
            or _url_or_none(_search_meta(webpage, "twitter:image"))
        )
        media_headers = {"Referer": page_url}

        return {
            "id": video_id,
            "title": title,
            "thumbnail": thumbnail,
            "formats": [{
                "url": video_url,
                "format_id": "http",
                "ext": "mp4",
                "http_headers": media_headers,
                "impersonate": True,
            }],
            "http_headers": media_headers,
        }


class TransHubIE(InfoExtractor):
    IE_NAME = "transhub"
    _VALID_URL = _TRANSHUB_VALID_URL

    def _real_extract(self, url):
        display_id = self._match_id(url)
        webpage = self._download_webpage(url, display_id)
        info = parse_transhub_html(webpage, url)
        embed_url = info.pop("embed_url")

        info.update({
            "_type": "url_transparent",
            "url": embed_url,
        })
        if _LULU_URL_RE.match(embed_url):
            info["ie_key"] = LuluVdoIE.ie_key()
        elif _STREAMTAPE_URL_RE.match(embed_url):
            info["ie_key"] = StreamtapeIE.ie_key()
        elif _DOODSTER_URL_RE.match(embed_url):
            info["ie_key"] = DoodsterIE.ie_key()
        return info
