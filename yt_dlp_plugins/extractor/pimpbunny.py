import ast
import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from yt_dlp.extractor.common import InfoExtractor


_VALID_URL = (
    r"https?://(?:www\.)?pimpbunny\.com/"
    r"(?:(?P<lang>[a-z]{2})/)?"
    r"videos/(?P<id>[^/?#&]+)/?"
    r"(?:[?#].*)?$"
)
_PLAYER_CONFIG_RE = re.compile(r"\bvar\s+(?P<name>t[0-9a-f]{8,})\s*=", re.IGNORECASE)
_PAGE_CONTEXT_RE = re.compile(r"var\s+pageContext\s*=", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>(?P<value>.*?)</title>", re.IGNORECASE | re.DOTALL)
_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](?P<value>[^"\']+)',
    re.IGNORECASE,
)
_META_RE_TEMPLATE = (
    r'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]+content=["\'](?P<value>[^"\']+)'
    r'|<meta[^>]+content=["\'](?P<value2>[^"\']+)["\'][^>]+(?:property|name)=["\']{name}["\']'
)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<value>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_MODELS_HTML_RE = re.compile(
    r'pages-view-video-model-title[^>]*>\s*<a[^>]*>(?P<value>[^<]+)</a>',
    re.IGNORECASE,
)
_VIDEO_SRC_RE = re.compile(r"<video[^>]+src=[\"'](?P<value>[^\"']+)", re.IGNORECASE)


def _strip_or_none(value):
    if not isinstance(value, str):
        return None
    value = unescape(value).strip()
    return value or None


def _url_or_none(url):
    url = _strip_or_none(url)
    if not url:
        return None
    url = re.sub(r"^function/\d+/(https?://)", r"\1", url)
    if url.startswith("//"):
        url = f"https:{url}"
    if not re.match(r"^https?://", url):
        return None
    return url


def _append_query(url, params):
    url = _url_or_none(url)
    if not url or not params:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None and key not in query:
            query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _has_function_urls(player_config):
    for key, value in (player_config or {}).items():
        if not re.fullmatch(r"video(?:_alt_url\d*|_url)", key):
            continue
        if isinstance(value, str) and value.startswith("function/"):
            return True
    return False


def _canonical_video_url(url):
    url = _url_or_none(url)
    if not url:
        return None
    return re.sub(
        r"^(https?://(?:www\.)?pimpbunny\.com)/(?:[a-z]{2}/)?videos/([^/?#&]+)/?",
        r"\1/videos/\2/",
        url,
        count=1,
        flags=re.IGNORECASE,
    )


def _canonical_file_url(url):
    url = _url_or_none(url)
    if not url:
        return None
    return re.sub(
        r"^(https?://(?:www\.)?pimpbunny\.com)/(?:[a-z]{2}/)?(get_file/)",
        r"\1/\2",
        url,
        count=1,
        flags=re.IGNORECASE,
    )


def _with_locale_url(url, locale="ru"):
    url = _strip_or_none(url)
    if not url:
        return None
    return re.sub(
        r"^(https?://(?:www\.)?pimpbunny\.com)/(?:[a-z]{2}/)?(videos/)",
        rf"\1/{locale}/\2",
        url,
        count=1,
        flags=re.IGNORECASE,
    )


def _search_meta(webpage, name):
    pattern = re.compile(_META_RE_TEMPLATE.format(name=re.escape(name)), re.IGNORECASE)
    match = pattern.search(webpage)
    if not match:
        return None
    return _strip_or_none(match.group("value") or match.group("value2"))


def _search_title(webpage):
    match = _TITLE_RE.search(webpage)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group("value"))
    return _strip_or_none(title)


def _search_canonical(webpage):
    match = _CANONICAL_RE.search(webpage)
    if not match:
        return None
    return _url_or_none(match.group("value"))


def _extract_balanced_block(text, start_idx, open_char="{", close_char="}"):
    depth = 0
    in_string = False
    string_char = ""
    escape = False

    for idx in range(start_idx, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == string_char:
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_char = char
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[start_idx:idx + 1]

    return None


def _extract_js_object(webpage, marker_re):
    match = marker_re.search(webpage)
    if not match:
        return None
    object_start = webpage.find("{", match.end())
    if object_start == -1:
        return None
    object_text = _extract_balanced_block(webpage, object_start)
    if not object_text:
        return None
    return object_text


def _extract_js_objects(webpage, marker_re):
    objects = []
    for match in marker_re.finditer(webpage):
        object_start = webpage.find("{", match.end())
        if object_start == -1:
            continue
        object_text = _extract_balanced_block(webpage, object_start)
        if object_text:
            objects.append(object_text)
    return objects


def _js_scalar_to_value(value):
    value = value.strip()
    if not value:
        return None
    if value in ("true", "false"):
        return value == "true"
    if value in ("null", "undefined"):
        return None
    if value[:1] in ("'", '"'):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _js_object_to_dict(js_text):
    if not js_text:
        return {}

    result = {}
    for match in re.finditer(
        r"(?P<key>[A-Za-z_]\w*)\s*:\s*(?P<value>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|true|false|null|undefined|-?\d+(?:\.\d+)?)",
        js_text,
        re.DOTALL,
    ):
        result[match.group("key")] = _js_scalar_to_value(match.group("value"))
    return result


def _find_player_config(webpage):
    for js_text in _extract_js_objects(webpage, _PLAYER_CONFIG_RE):
        data = _js_object_to_dict(js_text)
        if data.get("video_id") or data.get("video_url") or any(
            key.startswith("video_alt_url") for key in data
        ):
            return data
    return {}


def _find_page_context(webpage):
    js_text = _extract_js_object(webpage, _PAGE_CONTEXT_RE)
    if not js_text:
        return {}
    return _js_object_to_dict(js_text)


def _find_json_ld_videoobject(webpage):
    for match in _JSON_LD_RE.finditer(webpage):
        raw_value = match.group("value").strip()
        if not raw_value:
            continue
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            continue

        candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("@type") == "VideoObject":
                return candidate
    return {}


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _parse_iso8601_duration(value):
    value = _strip_or_none(value)
    if not value:
        return None

    match = re.fullmatch(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None

    hours = _parse_int(match.group("hours")) or 0
    minutes = _parse_int(match.group("minutes")) or 0
    seconds = _parse_int(match.group("seconds")) or 0
    return hours * 3600 + minutes * 60 + seconds


def _split_csv(value):
    value = _strip_or_none(value)
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _extract_models_from_html(webpage):
    models = [_strip_or_none(match.group("value")) for match in _MODELS_HTML_RE.finditer(webpage)]
    return [model for model in _dedupe_preserve_order(models) if model]


def _guess_display_id(url):
    canonical_url = _canonical_video_url(url)
    if not canonical_url:
        return None
    match = re.search(r"/videos/(?P<display_id>[^/?#&]+)/?", canonical_url)
    if not match:
        return None
    return match.group("display_id")


def _guess_height(label, url):
    label = _strip_or_none(label) or ""
    url = _strip_or_none(url) or ""

    match = re.search(r"(?P<height>\d+)\s*p", label, re.IGNORECASE)
    if match:
        return int(match.group("height"))

    match = re.search(r"(?P<k>\d+)\s*k", label, re.IGNORECASE)
    if match:
        k = int(match.group("k"))
        return {2: 1440, 4: 2160, 8: 4320}.get(k)

    match = re.search(r"_(?P<height>\d+)p\.", url, re.IGNORECASE)
    if match:
        return int(match.group("height"))

    return None


def _build_formats(player_config, json_ld, video_src):
    formats = []
    seen_urls = set()
    rnd = _strip_or_none(player_config.get("rnd"))

    def add_format(url, label=None):
        base_url = _canonical_file_url(url) or _url_or_none(url)
        cleaned_url = _append_query(base_url, {"rnd": rnd}) if rnd else base_url
        if not cleaned_url or cleaned_url in seen_urls:
            return
        seen_urls.add(cleaned_url)
        height = _guess_height(label, cleaned_url)
        format_id = _strip_or_none(label) or (f"{height}p" if height else None) or "http"
        formats.append({
            "url": cleaned_url,
            "format_id": format_id,
            "height": height,
            "ext": "mp4",
        })

    add_format(player_config.get("video_url"), player_config.get("video_url_text"))
    for key in sorted(player_config):
        if not re.fullmatch(r"video_alt_url\d*", key):
            continue
        if player_config.get(f"{key}_redirect"):
            continue
        label_key = f"{key}_text"
        add_format(player_config.get(key), player_config.get(label_key))

    add_format(json_ld.get("contentUrl"), "jsonld")
    add_format(video_src, "embedded")

    formats.sort(key=lambda item: (item.get("height") or 0, item.get("format_id") or ""), reverse=True)
    return formats


def _extract_counts(json_ld):
    result = {}
    for item in json_ld.get("interactionStatistic") or []:
        if not isinstance(item, dict):
            continue
        interaction = item.get("interactionType") or {}
        if not isinstance(interaction, dict):
            continue
        count = _parse_int(item.get("userInteractionCount"))
        if count is None:
            continue
        action_type = interaction.get("@type")
        if action_type == "WatchAction":
            result["view_count"] = count
        elif action_type == "LikeAction":
            result["like_count"] = count
    return result


def parse_pimpbunny_html(webpage, url):
    player_config = _find_player_config(webpage)
    page_context = _find_page_context(webpage)
    json_ld = _find_json_ld_videoobject(webpage)
    canonical_url = _canonical_video_url(_search_canonical(webpage) or url) or _canonical_video_url(url) or url
    video_src_match = _VIDEO_SRC_RE.search(webpage)
    video_src = video_src_match.group("value") if video_src_match else None

    video_id = (
        _strip_or_none(player_config.get("video_id"))
        or _strip_or_none(page_context.get("videoId"))
        or _strip_or_none(re.search(r"/embed/(\d+)", canonical_url or "") and re.search(r"/embed/(\d+)", canonical_url or "").group(1))
    )
    if not video_id:
        raise ValueError("Could not find video id in PimpBunny page")

    title = (
        _strip_or_none(player_config.get("video_title"))
        or _strip_or_none(json_ld.get("name"))
        or _search_meta(webpage, "og:title")
        or _search_meta(webpage, "twitter:title")
        or _search_title(webpage)
    )
    if not title:
        raise ValueError("Could not find video title in PimpBunny page")

    cast = _split_csv(player_config.get("video_models")) or _extract_models_from_html(webpage)
    uploader = cast[0] if len(cast) == 1 else ", ".join(cast) if cast else None

    timestamp = (
        _parse_timestamp(_search_meta(webpage, "video:release_date"))
        or _parse_timestamp(json_ld.get("uploadDate"))
    )
    duration = (
        _parse_int(_search_meta(webpage, "video:duration"))
        or _parse_iso8601_duration(json_ld.get("duration"))
    )
    thumbnail = (
        _url_or_none(player_config.get("preview_url"))
        or _url_or_none(json_ld.get("thumbnailUrl"))
        or _url_or_none(_search_meta(webpage, "og:image"))
        or _url_or_none(_search_meta(webpage, "twitter:image"))
    )
    description = (
        _strip_or_none(json_ld.get("description"))
        or _search_meta(webpage, "description")
        or _search_meta(webpage, "og:description")
        or _search_meta(webpage, "twitter:description")
    )
    formats = _build_formats(player_config, json_ld, video_src)
    if not formats:
        raise ValueError("Could not find downloadable formats in PimpBunny page")

    info = {
        "id": video_id,
        "display_id": _guess_display_id(canonical_url) or _guess_display_id(url),
        "title": title,
        "uploader": uploader,
        "creator": uploader,
        "cast": cast or None,
        "thumbnail": thumbnail,
        "description": description,
        "duration": duration,
        "timestamp": timestamp,
        "upload_date": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d") if timestamp else None,
        "tags": _split_csv(player_config.get("video_tags")),
        "categories": _split_csv(player_config.get("video_categories")),
        "formats": formats,
        "age_limit": 18,
        "webpage_url": canonical_url or url,
        "http_headers": {"Referer": canonical_url or url},
    }
    info.update(_extract_counts(json_ld))
    return {key: value for key, value in info.items() if value not in (None, [], "")}


class PimpBunnyIE(InfoExtractor):
    IE_NAME = "pimpbunny"
    _VALID_URL = _VALID_URL
    def _real_extract(self, url):
        video_id = self._match_id(url)
        canonical_url = _canonical_video_url(url) or url

        webpage = self._download_webpage(canonical_url, video_id)
        info = parse_pimpbunny_html(webpage, canonical_url)
        source_url = canonical_url
        info["webpage_url"] = canonical_url
        if canonical_url != url:
            info["original_url"] = url

        english_url = _with_locale_url(canonical_url, "en")
        if english_url and english_url != canonical_url:
            try:
                english_webpage = self._download_webpage(
                    english_url,
                    video_id,
                    note="Downloading English metadata webpage",
                    errnote=False,
                    fatal=False,
                )
            except Exception:
                english_webpage = None
            if english_webpage:
                try:
                    english_info = parse_pimpbunny_html(english_webpage, english_url)
                except ValueError:
                    english_info = None
                if english_info:
                    info = english_info
                    webpage = english_webpage
                    source_url = english_url
                    info["webpage_url"] = canonical_url
                    if canonical_url != url:
                        info["original_url"] = url

        player_config = _find_player_config(webpage)
        if _has_function_urls(player_config):
            fallback_url = _with_locale_url(source_url, "ru")
            if fallback_url and fallback_url != source_url:
                try:
                    fallback_webpage = self._download_webpage(
                        fallback_url,
                        video_id,
                        note="Downloading localized fallback webpage",
                        errnote=False,
                        fatal=False,
                    )
                except Exception:
                    fallback_webpage = None
                if fallback_webpage:
                    fallback_player_config = _find_player_config(fallback_webpage)
                    if fallback_player_config and not _has_function_urls(fallback_player_config):
                        fallback_info = parse_pimpbunny_html(fallback_webpage, fallback_url)
                        info["formats"] = fallback_info.get("formats") or info.get("formats")
                        info["http_headers"] = {"Referer": canonical_url}
                        if fallback_info.get("thumbnail") and not info.get("thumbnail"):
                            info["thumbnail"] = fallback_info["thumbnail"]
                        if canonical_url != url:
                            info["original_url"] = url
                        return info

        return info
