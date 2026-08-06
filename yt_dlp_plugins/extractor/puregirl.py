import re
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, int_or_none


_VALID_URL = r"https?://(?:www\.)?puregirl\.tv/post/(?P<id>[^/?#]+)"
_API_BASE = "https://puregirl.tv/api"
_HEIGHT_RE = re.compile(r"(?<!\d)(?P<height>\d{3,4})\s*p?\b", re.IGNORECASE)
_QUALITY_HEIGHTS = {
    "sd": 480,
    "hd": 720,
    "fhd": 1080,
    "2k": 1440,
    "4k": 2160,
    "8k": 4320,
}


def _strip_or_none(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _absolute_url(url, base_url="https://puregirl.tv/"):
    url = _strip_or_none(url)
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin(base_url, url)


def _decode_hls_url(url):
    """Apply the filename transformation used by PureGirl's web player."""
    url = _strip_or_none(url)
    if not url:
        return None

    parsed = urlsplit(url)
    if not parsed.path.lower().endswith("master.m3u8"):
        return url

    path_prefix, _, filename = parsed.path.rpartition("/")
    encoded_name = filename.split(".", 1)[0]
    if len(encoded_name) <= 5:
        return url

    decoded_name = encoded_name[:-5][::-1]
    decoded_filename = filename.replace(encoded_name, decoded_name, 1)
    decoded_path = f"{path_prefix}/{decoded_filename}" if path_prefix else decoded_filename
    return urlunsplit(parsed._replace(path=decoded_path))


def _hls_url(source_url):
    source_url = _strip_or_none(source_url)
    if not source_url:
        return None
    if source_url.startswith("//"):
        return _decode_hls_url(f"https:{source_url}")
    if re.match(r"https?://", source_url, re.IGNORECASE):
        return _decode_hls_url(source_url)
    if source_url.startswith("/api/stream/"):
        return urljoin("https://puregirl.tv/", source_url)
    return f"{_API_BASE}/stream/{source_url.lstrip('/')}"


def _guess_height(label, fallback=None):
    label = _strip_or_none(label)
    if label:
        match = _HEIGHT_RE.search(label)
        if match:
            return int(match.group("height"))
        mapped_height = _QUALITY_HEIGHTS.get(label.lower())
        if mapped_height:
            return mapped_height
    return int_or_none(fallback)


def _split_keywords(value):
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = value.split(",")
    else:
        return None

    result = []
    seen = set()
    for item in values:
        item = _strip_or_none(item)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result or None


def _performer_metadata(performers):
    names = []
    ids = []
    for performer in performers or []:
        if not isinstance(performer, dict):
            continue
        name = _strip_or_none(performer.get("full_name"))
        performer_id = _strip_or_none(performer.get("id"))
        if name and name not in names:
            names.append(name)
        if performer_id and performer_id not in ids:
            ids.append(performer_id)

    uploader = ", ".join(names) or None
    return {
        "uploader": uploader,
        "creator": uploader,
        "uploader_id": ids[0] if len(ids) == 1 else None,
        "cast": names or None,
    }


def _upload_date(timestamp):
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d")


def _extract_metadata(data, requested_id, webpage_url):
    video_id = _strip_or_none(data.get("id")) or requested_id
    display_id = video_id.rsplit(".", 1)[0] if "." in video_id else video_id
    timestamp = int_or_none(data.get("create_time"), scale=1000)
    modified_timestamp = int_or_none(data.get("update_time"), scale=1000)

    info = {
        "id": video_id,
        "display_id": display_id,
        "title": _strip_or_none(data.get("title")) or display_id.replace("-", " "),
        "description": _strip_or_none(data.get("content")),
        "thumbnail": _absolute_url(data.get("image_url")),
        "duration": int_or_none(data.get("duration")),
        "timestamp": timestamp,
        "upload_date": _upload_date(timestamp),
        "modified_timestamp": modified_timestamp,
        "view_count": int_or_none(data.get("views")),
        "like_count": int_or_none(data.get("likes")),
        "dislike_count": int_or_none(data.get("dislikes")),
        "tags": _split_keywords(data.get("seo_keywords")),
        "age_limit": 18,
        "webpage_url": webpage_url,
    }
    info.update(_performer_metadata(data.get("performer_responses")))
    return {key: value for key, value in info.items() if value not in (None, [], "")}


def _source_file(source):
    if isinstance(source, str):
        return _strip_or_none(source)
    if isinstance(source, dict):
        return _strip_or_none(source.get("file"))
    return None


def _source_is_hls(source, playback_type):
    source_url = _source_file(source) or ""
    source_type = _strip_or_none(source.get("type")) if isinstance(source, dict) else None
    return (
        (playback_type or "").lower() == "hls"
        or (source_type or "").lower() == "hls"
        or "mpegurl" in (source_type or "").lower()
        or ".m3u8" in source_url.lower()
    )


def _direct_format(source, fallback_height, headers):
    source_url = _absolute_url(_source_file(source))
    if not source_url:
        return None

    source = source if isinstance(source, dict) else {}
    label = _strip_or_none(source.get("label"))
    height = _guess_height(label, source.get("height") or fallback_height)
    source_type = _strip_or_none(source.get("type"))
    ext = "mp4" if (
        ".mp4" in urlsplit(source_url).path.lower()
        or "mp4" in (source_type or "").lower()
    ) else None

    result = {
        "url": source_url,
        "format_id": label or (f"{height}p" if height else "http"),
        "height": height,
        "ext": ext,
        "http_headers": headers,
    }
    if source.get("default") is True:
        result["preference"] = 1
    return {key: value for key, value in result.items() if value is not None}


class PureGirlIE(InfoExtractor):
    IE_NAME = "puregirl"
    _VALID_URL = _VALID_URL

    def _real_extract(self, url):
        requested_id = unquote(self._match_id(url))
        encoded_id = quote(requested_id, safe="")
        webpage_url = f"https://puregirl.tv/post/{encoded_id}"
        response = self._download_json(
            f"{_API_BASE}/post/{encoded_id}",
            requested_id,
            headers={"Referer": webpage_url},
        )
        if not isinstance(response, dict) or response.get("error_code") not in (None, 200):
            message = response.get("message") if isinstance(response, dict) else None
            raise ExtractorError(message or "PureGirl API returned an error", expected=True)

        data = response.get("data")
        if not isinstance(data, dict):
            raise ExtractorError("PureGirl API response did not contain post data", expected=True)

        info = _extract_metadata(data, requested_id, webpage_url)
        playback_type = (_strip_or_none(data.get("playback_format_type")) or "").lower()
        sources = data.get("playback_source") or []
        if isinstance(sources, (str, dict)):
            sources = [sources]

        media_headers = {"Referer": webpage_url, "Origin": "https://puregirl.tv"}
        fallback_height = int_or_none(data.get("resolution"))
        formats = []
        seen_direct_urls = set()
        for source_index, source in enumerate(sources):
            source_url = _source_file(source)
            if not source_url:
                continue

            if _source_is_hls(source, playback_type):
                manifest_url = _hls_url(source_url)
                if not manifest_url:
                    continue
                source_label = (
                    _strip_or_none(source.get("label")) if isinstance(source, dict) else None
                )
                formats.extend(self._extract_m3u8_formats(
                    manifest_url,
                    info["id"],
                    ext="mp4",
                    m3u8_id=source_label or ("hls" if source_index == 0 else f"hls-{source_index + 1}"),
                    fatal=False,
                    headers=media_headers,
                ))
                continue

            direct_format = _direct_format(source, fallback_height, media_headers)
            if not direct_format or direct_format["url"] in seen_direct_urls:
                continue
            seen_direct_urls.add(direct_format["url"])
            formats.append(direct_format)

        if not formats:
            self.raise_no_formats("Could not find downloadable media in PureGirl post", expected=True)

        info.update({
            "formats": formats,
            "http_headers": media_headers,
        })
        return info
