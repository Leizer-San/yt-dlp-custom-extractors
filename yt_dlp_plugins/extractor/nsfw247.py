import json
import re
from datetime import datetime, timezone
from html import unescape

from yt_dlp.extractor.common import InfoExtractor


_VALID_URL = r"https?://(?:www\.)?nsfw247\.to/(?P<id>[^/?#]+)/?(?:[?#].*)?$"
_ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_SOURCE_RE = re.compile(r"<source\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_VIDEO_RE = re.compile(r"<video\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(r"<meta\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title>(?P<value>.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1\b[^>]*>(?P<value>.*?)</h1>", re.IGNORECASE | re.DOTALL)
_JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(?P<value>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


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
    return _strip_or_none(re.sub(r"\s+(?:OnlyFans leak free video via NSFW247|via NSFW247).*$", "", value, flags=re.IGNORECASE))


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


def _search_canonical(webpage):
    for match in _LINK_RE.finditer(webpage):
        attrs = _extract_attrs(match.group("attrs"))
        if "canonical" in (attrs.get("rel") or "").lower().split():
            return _url_or_none(attrs.get("href"))
    return None


def _search_title(webpage):
    match = _H1_RE.search(webpage) or _TITLE_RE.search(webpage)
    if not match:
        return None
    return _clean_title(match.group("value"))


def _iter_json_ld_candidates(value):
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_candidates(item)
    elif isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_ld_candidates(item)


def _find_json_ld(webpage):
    result = {"video": {}, "webpage": {}, "image": {}}
    for match in _JSON_LD_RE.finditer(webpage):
        try:
            parsed = json.loads(match.group("value").strip())
        except json.JSONDecodeError:
            continue
        for candidate in _iter_json_ld_candidates(parsed):
            item_type = candidate.get("@type")
            item_types = item_type if isinstance(item_type, list) else [item_type]
            if "VideoObject" in item_types and not result["video"]:
                result["video"] = candidate
            elif "WebPage" in item_types and not result["webpage"]:
                result["webpage"] = candidate
            elif "ImageObject" in item_types and not result["image"]:
                result["image"] = candidate
    return result


def _first_url(value):
    if isinstance(value, list):
        for item in value:
            url = _url_or_none(item)
            if url:
                return url
        return None
    return _url_or_none(value)


def _parse_timestamp(value):
    value = _strip_or_none(value)
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _split_csv(value):
    value = _strip_or_none(value)
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _extract_media_urls(webpage):
    seen = set()
    urls = []
    for tag_re in (_SOURCE_RE, _VIDEO_RE):
        for match in tag_re.finditer(webpage):
            attrs = _extract_attrs(match.group("attrs"))
            media_url = _url_or_none(attrs.get("src"))
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)
            urls.append(media_url)
    return urls


def parse_nsfw247_html(webpage, url):
    json_ld = _find_json_ld(webpage)
    video_ld = json_ld.get("video") or {}
    webpage_ld = json_ld.get("webpage") or {}
    image_ld = json_ld.get("image") or {}
    canonical_url = _search_canonical(webpage) or _url_or_none(webpage_ld.get("url")) or url
    canonical_match = re.match(_VALID_URL, canonical_url, re.IGNORECASE)
    url_match = canonical_match or re.match(_VALID_URL, url, re.IGNORECASE)

    media_urls = _extract_media_urls(webpage)
    if not media_urls:
        raise ValueError("Could not find video source URL in NSFW247 page")

    title = (
        _clean_title(video_ld.get("name"))
        or _search_title(webpage)
        or _clean_title(_search_meta(webpage, "og:title"))
        or _clean_title(webpage_ld.get("name"))
    )
    if not title:
        raise ValueError("Could not find video title in NSFW247 page")

    timestamp = (
        _parse_timestamp(video_ld.get("uploadDate"))
        or _parse_timestamp(webpage_ld.get("datePublished"))
        or _parse_timestamp(webpage_ld.get("dateModified"))
    )
    headers = {"Referer": canonical_url}
    formats = [{
        "url": media_url,
        "format_id": f"http-{index}" if len(media_urls) > 1 else "http",
        "ext": "mp4",
        "http_headers": headers,
    } for index, media_url in enumerate(media_urls, 1)]

    info = {
        "id": url_match.group("id"),
        "display_id": canonical_match.group("id") if canonical_match else None,
        "title": title,
        "description": (
            _strip_or_none(webpage_ld.get("description"))
            or _strip_or_none(video_ld.get("description"))
            or _strip_or_none(_search_meta(webpage, "description"))
            or _strip_or_none(_search_meta(webpage, "og:description"))
        ),
        "thumbnail": (
            _first_url(video_ld.get("thumbnailUrl"))
            or _url_or_none(_search_meta(webpage, "og:image"))
            or _url_or_none(_search_meta(webpage, "twitter:image"))
            or _url_or_none(image_ld.get("url"))
        ),
        "timestamp": timestamp,
        "upload_date": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d") if timestamp else None,
        "tags": _split_csv(video_ld.get("keywords")),
        "formats": formats,
        "age_limit": 18,
        "webpage_url": canonical_url,
        "http_headers": headers,
    }
    return {key: value for key, value in info.items() if value not in (None, [], "")}


class NSFW247IE(InfoExtractor):
    IE_NAME = "nsfw247"
    _VALID_URL = _VALID_URL

    def _real_extract(self, url):
        display_id = self._match_id(url)
        webpage = self._download_webpage(url, display_id)
        return parse_nsfw247_html(webpage, url)
