import re
from datetime import datetime, timezone
from html import unescape

from yt_dlp.extractor.common import InfoExtractor


_VALID_URL = (
    r"https?://(?:[\w-]+\.)?hornysimp\.com\.[a-z]{2,}/"
    r"(?!(?:actor|category|tag|page|wp-content|wp-admin|wp-json)/)"
    r"(?P<id>[^/?#]+)/?(?:[?#].*)?$"
)

_ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_META_RE = re.compile(r"<meta\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link\b(?P<attrs>[^>]+)>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title>(?P<value>.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1\b[^>]*>(?P<value>.*?)</h1>", re.IGNORECASE | re.DOTALL)
_EMBED_RE = re.compile(
    r'<[^>]+\bdata-embed=["\'](?P<url>https?://[^"\']+)["\']',
    re.IGNORECASE,
)
_THUM_RE = re.compile(
    r'<[^>]+\bdata-thum=["\'](?P<url>https?://[^"\']+)["\']',
    re.IGNORECASE,
)
_ACTOR_RE = re.compile(
    r'href=["\'][^"\']+/actor/[^"\']+["\'][^>]*>(?P<name>[^<]+)</a>',
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"Date:\s*(?P<value>[A-Za-z]+ \d{1,2},\s*\d{4})", re.IGNORECASE)
_CLEAN_TAG_RE = re.compile(r"<[^>]+>")


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
    return _strip_or_none(_CLEAN_TAG_RE.sub(" ", value))


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
    raw = match.group("value")
    return _strip_or_none(_CLEAN_TAG_RE.sub("", raw))


def _clean_title(value):
    """Remove the site name suffix from the title."""
    value = _clean_html_text(value)
    if not value:
        return None
    return _strip_or_none(re.sub(r"\s*[-–|]\s*HornySimp\s*$", "", value, flags=re.IGNORECASE))


def _parse_timestamp(value):
    value = _strip_or_none(value)
    if not value:
        return None
    # "August 20, 2026" format used in the page body
    try:
        return int(datetime.strptime(value, "%B %d, %Y").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


_SUPPORTED_EMBED_RE = re.compile(
    r"https?://(?:[\w-]+\.)?(?:luluvids\.top|morencius\.com|lulustream\.com|luluvdo\.com|luluvdoo\.com|luluvid\.com|vidhide\.com|streamtape\.com|voe\.sx)/",
    re.IGNORECASE,
)


def _extract_embeds(webpage):
    seen = set()
    embeds = []
    for match in _EMBED_RE.finditer(webpage):
        url = _url_or_none(match.group("url"))
        if url and url not in seen:
            seen.add(url)
            embeds.append(url)

    supported = [u for u in embeds if _SUPPORTED_EMBED_RE.match(u)]
    if supported:
        return supported
    return embeds



def _extract_thumbnail(webpage):
    match = _THUM_RE.search(webpage)
    if match:
        return _url_or_none(match.group("url"))
    return (
        _url_or_none(_search_meta(webpage, "og:image"))
        or _url_or_none(_search_meta(webpage, "twitter:image"))
    )


def _extract_actors(webpage):
    seen = set()
    actors = []
    for match in _ACTOR_RE.finditer(webpage):
        name = _strip_or_none(match.group("name"))
        if name and name not in seen:
            seen.add(name)
            actors.append(name)
    return actors


def _extract_duration(webpage):
    """Extract the first duration span (the current video, not related videos)."""
    match = re.search(
        r'class=["\'][^"\']*\bduration\b[^"\']*["\'][^>]*>'
        r'[^<]*?(?:(?P<h>\d+):)?(?P<m>\d+):(?P<s>\d+)',
        webpage,
        re.IGNORECASE,
    )
    if not match:
        return None
    h = int(match.group("h") or 0)
    m = int(match.group("m"))
    s = int(match.group("s"))
    return h * 3600 + m * 60 + s


def parse_hornysimp_html(webpage, url):
    """Parse a HornySimp video page and return metadata + embed URLs."""
    canonical_url = _search_canonical(webpage) or url
    slug_match = re.search(
        r"hornysimp\.com\.[a-z]{2,}/([^/?#]+)/?",
        canonical_url or url,
        re.IGNORECASE,
    )
    if slug_match:
        video_id = slug_match.group(1)
    else:
        tail = re.search(r"/([^/?#]+)/?$", url)
        video_id = tail.group(1) if tail else url

    title = (
        _clean_title(_search_meta(webpage, "og:title"))
        or _search_title(webpage)
        or _clean_title(_search_meta(webpage, "description"))
    )
    if not title:
        raise ValueError("Could not find video title in HornySimp page")

    embeds = _extract_embeds(webpage)
    if not embeds:
        raise ValueError("Could not find any embed URLs in HornySimp page")

    thumbnail = _extract_thumbnail(webpage)
    actors = _extract_actors(webpage)
    date_match = _DATE_RE.search(webpage)
    timestamp = _parse_timestamp(date_match.group("value")) if date_match else None
    duration = _extract_duration(webpage)
    uploader = actors[0] if len(actors) == 1 else None

    thumbnails = []
    if thumbnail:
        thumbnails.append({
            "url": thumbnail,
            "http_headers": {"Referer": canonical_url},
        })

    info = {
        "id": video_id,
        "title": title,
        "thumbnail": thumbnail,
        "thumbnails": thumbnails or None,
        "cast": actors or None,
        "uploader": uploader,
        "timestamp": timestamp,
        "upload_date": (
            datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d")
            if timestamp else None
        ),
        "duration": duration,
        "age_limit": 18,
        "webpage_url": canonical_url,
        "_embeds": embeds,
    }
    return {k: v for k, v in info.items() if v not in (None, [], "")}


from .luluvids import _extract_media as _lulu_extract_media
from .morencius import (
    _HLS_RE as _MORENCIUS_HLS_RE,
    _THUMB_RE as _MORENCIUS_THUMB_RE,
    _decode_packed as _morencius_decode,
)


class HornySimpIE(InfoExtractor):
    IE_NAME = "hornysimp"
    IE_DESC = "HornySimp"
    _VALID_URL = _VALID_URL

    _TESTS = [{
        "url": "https://w11.hornysimp.com.lv/angela-white-brand-new-sloppy-sloppy-blowbang-swallow/",
        "info_dict": {
            "id": "angela-white-brand-new-sloppy-sloppy-blowbang-swallow",
            "ext": "mp4",
            "title": "Angela White BRAND NEW Sloppy Sloppy Blowbang Swallow",
            "age_limit": 18,
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        try:
            info = parse_hornysimp_html(webpage, url)
        except ValueError as e:
            self.raise_no_formats(str(e), expected=True)

        embeds = info.pop("_embeds", [])
        canonical_url = info.get("webpage_url") or url

        formats = []
        thumbnails = list(info.get("thumbnails") or [])

        for embed_url in embeds:
            try:
                if re.search(r"luluvids\.top", embed_url, re.IGNORECASE):
                    embed_page = self._download_webpage(
                        embed_url, video_id, note="Downloading LuluVids embed",
                        headers={"Referer": canonical_url}, fatal=False,
                    )
                    if embed_page:
                        media = _lulu_extract_media(embed_page)
                        for media_url, ext in media:
                            if ext == "m3u8":
                                fmts = self._extract_m3u8_formats(
                                    media_url, video_id, ext="mp4",
                                    entry_protocol="m3u8_native",
                                    m3u8_id="luluvids", fatal=False,
                                    headers={"Referer": embed_url},
                                )
                                formats.extend(fmts)
                            else:
                                formats.append({
                                    "url": media_url,
                                    "format_id": f"luluvids-{ext}",
                                    "ext": ext,
                                    "http_headers": {"Referer": embed_url},
                                })
                        lulu_thumb = (
                            _strip_or_none(_search_meta(embed_page, "og:image"))
                            or _strip_or_none(_search_meta(embed_page, "twitter:image"))
                        )
                        if lulu_thumb:
                            thumbnails.append({"url": lulu_thumb, "preference": 10})

                elif re.search(r"morencius\.com", embed_url, re.IGNORECASE):
                    embed_page = self._download_webpage(
                        embed_url, video_id, note="Downloading Morencius embed",
                        headers={"Referer": canonical_url}, fatal=False,
                    )
                    if embed_page:
                        unpacked = _morencius_decode(embed_page) or embed_page
                        for m in _MORENCIUS_HLS_RE.finditer(unpacked):
                            hls_url = _strip_or_none(m.group(1))
                            if hls_url:
                                fmts = self._extract_m3u8_formats(
                                    hls_url, video_id, ext="mp4",
                                    entry_protocol="m3u8_native",
                                    m3u8_id="morencius", fatal=False,
                                    headers={"Referer": embed_url},
                                )
                                formats.extend(fmts)
                        thumb_m = _MORENCIUS_THUMB_RE.search(unpacked)
                        if thumb_m:
                            thumbnails.append({
                                "url": _strip_or_none(thumb_m.group(1)),
                                "preference": 10,
                            })
            except Exception as e:
                self.report_warning(f"Failed to extract formats from mirror {embed_url}: {e}")

        if not formats:
            self.raise_no_formats("Could not find playable video formats on any mirror", expected=True)

        info["formats"] = formats
        if thumbnails:
            info["thumbnails"] = thumbnails
            # Pick highest preference thumbnail
            best_thumb = max(thumbnails, key=lambda t: t.get("preference", 0))
            info["thumbnail"] = best_thumb["url"]

        return info

