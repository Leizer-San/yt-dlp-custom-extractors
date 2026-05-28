import ast
import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse, urlunparse

from yt_dlp.extractor.common import InfoExtractor


_VALID_URL = (
    r"https?://(?:www\.)?x-tg\.tube/"
    r"(?:(?:video/(?P<id>\d+)(?:/(?P<display_id>[^/?#]+))?)|(?:embed/(?P<embed_id>\d+)))/?"
    r"(?:[?#].*)?$"
)
_MODEL_VALID_URL = (
    r"https?://(?:www\.)?x-tg\.tube/models/(?P<id>[^/?#]+)"
    r"(?:/videos(?:/(?P<page>\d+))?)?/?"
    r"(?:[?#].*)?$"
)
_PLAYER_CONFIG_RE = re.compile(r"\bvar\s+[A-Za-z_$][\w$]*\s*=", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>(?P<value>.*?)</title>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"<a\b[^>]+\bhref=[\"'](?P<value>[^\"']+)", re.IGNORECASE | re.DOTALL)
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
    return _strip_or_none(re.sub(r"\s+-\s+XXX .*?$", "", value, flags=re.IGNORECASE))


def _clean_model_title(value):
    value = _clean_html_text(value)
    if not value:
        return None
    value = re.sub(
        r"^X-?tg:\s*XXX\s+tranny\s+videos\s+and\s+sex\s+films\s+starring\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return _strip_or_none(value)


def _url_or_none(url):
    url = _strip_or_none(url)
    if not url:
        return None
    if url.startswith("function/"):
        return None
    if url.startswith("//"):
        url = f"https:{url}"
    if not re.match(r"https?://", url, re.IGNORECASE):
        return None
    return url


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
    return _clean_title(match.group("value"))


def _search_canonical(webpage):
    match = _CANONICAL_RE.search(webpage)
    if not match:
        return None
    return _url_or_none(match.group("value"))


def _iter_href_urls(webpage, base_url):
    for match in _HREF_RE.finditer(webpage):
        url = _url_or_none(urljoin(base_url, unescape(match.group("value"))))
        if url:
            yield url


def _normalize_url(url, keep_query=True):
    parsed = urlparse(url)
    if not keep_query:
        parsed = parsed._replace(query="")
    return urlunparse(parsed._replace(fragment=""))


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
            if isinstance(candidate, dict) and candidate.get("@type") == "VideoObject":
                return candidate
    return {}


def _find_json_ld_person(webpage):
    for match in _JSON_LD_RE.finditer(webpage):
        raw_value = match.group("value").strip()
        if not raw_value:
            continue
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            continue

        candidates = parsed if isinstance(parsed, list) else [parsed]
        if isinstance(parsed, dict) and isinstance(parsed.get("@graph"), list):
            candidates.extend(parsed["@graph"])
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_type = candidate.get("@type")
            if candidate_type == "Person" or (
                isinstance(candidate_type, list) and "Person" in candidate_type
            ):
                return candidate
    return {}


def _parse_int(value):
    try:
        return int(str(value).replace(" ", ""))
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


def _first_url(value):
    if isinstance(value, list):
        for item in value:
            url = _url_or_none(item)
            if url:
                return url
        return None
    return _url_or_none(value)


def _guess_height(label, url):
    label = _strip_or_none(label) or ""
    url = _strip_or_none(url) or ""

    match = re.search(r"(?P<height>\d+)\s*p", label, re.IGNORECASE)
    if match:
        return int(match.group("height"))

    match = re.search(r"_(?P<height>\d+)p\.", url, re.IGNORECASE)
    if match:
        return int(match.group("height"))

    return None


def _kvs_get_license_token(license_code):
    license_code = _strip_or_none(license_code)
    if not license_code:
        return None
    license_code = license_code.replace("$", "")
    if not re.fullmatch(r"\d+", license_code):
        return None

    license_values = [int(char) for char in license_code]
    modlicense = license_code.replace("0", "1")
    center = len(modlicense) // 2
    fronthalf = int(modlicense[:center + 1])
    backhalf = int(modlicense[center:])
    modlicense = str(4 * abs(fronthalf - backhalf))[:center + 1]

    return [
        (license_values[index + offset] + current) % 10
        for index, current in enumerate(map(int, modlicense))
        for offset in range(4)
    ]


def _kvs_get_real_url(video_url, license_code):
    video_url = _strip_or_none(video_url)
    if not video_url:
        return None
    if not video_url.startswith("function/0/"):
        return _url_or_none(video_url)

    license_token = _kvs_get_license_token(license_code)
    if not license_token:
        return None

    parsed = urlparse(video_url[len("function/0/"):])
    urlparts = parsed.path.split("/")
    if len(urlparts) < 4:
        return None

    hash_length = 32
    hash_value = urlparts[3][:hash_length]
    if len(hash_value) < hash_length:
        return None

    indices = list(range(hash_length))
    accum = 0
    for src in reversed(range(hash_length)):
        accum += license_token[src]
        dest = (src + accum) % hash_length
        indices[src], indices[dest] = indices[dest], indices[src]

    urlparts[3] = "".join(hash_value[index] for index in indices) + urlparts[3][hash_length:]
    return _url_or_none(urlunparse(parsed._replace(path="/".join(urlparts))))


def _build_formats(player_config, json_ld, video_src, referer):
    formats = []
    seen_urls = set()
    headers = {"Referer": referer}
    license_code = player_config.get("license_code")

    def add_format(url, label=None):
        cleaned_url = _kvs_get_real_url(url, license_code)
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
            "http_headers": headers,
            "impersonate": True,
        })

    add_format(player_config.get("video_url"), player_config.get("video_url_text"))
    for key in sorted(player_config):
        if not re.fullmatch(r"video_alt_url\d*", key):
            continue
        if player_config.get(f"{key}_redirect"):
            continue
        add_format(player_config.get(key), player_config.get(f"{key}_text"))

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
        if isinstance(interaction, str):
            action_type = interaction.rsplit("/", 1)[-1]
        elif isinstance(interaction, dict):
            action_type = interaction.get("@type")
        else:
            continue
        count = _parse_int(item.get("userInteractionCount"))
        if count is None:
            continue
        if action_type == "WatchAction":
            result["view_count"] = count
        elif action_type == "LikeAction":
            result["like_count"] = count
    return result


def _extract_model_video_urls(webpage, base_url):
    seen_urls = set()
    for href in _iter_href_urls(webpage, base_url):
        if not re.match(_VALID_URL, href, re.IGNORECASE):
            continue
        video_url = _normalize_url(href, keep_query=False)
        if video_url in seen_urls:
            continue
        seen_urls.add(video_url)
        yield video_url


def _extract_model_page_urls(webpage, base_url, model_id):
    seen_urls = set()
    for href in _iter_href_urls(webpage, base_url):
        match = re.match(_MODEL_VALID_URL, href, re.IGNORECASE)
        if not match or match.group("id") != model_id:
            continue

        parsed = urlparse(href)
        if f"/models/{model_id}/videos" not in parsed.path:
            continue
        if parsed.query and "by=post_date" not in parsed.query:
            continue

        page_url = _normalize_url(href)
        if page_url in seen_urls:
            continue
        seen_urls.add(page_url)
        yield page_url


def parse_x_tg_html(webpage, url):
    player_config = _find_player_config(webpage)
    json_ld = _find_json_ld_videoobject(webpage)
    canonical_url = _search_canonical(webpage) or url

    url_match = re.match(_VALID_URL, canonical_url, re.IGNORECASE) or re.match(_VALID_URL, url, re.IGNORECASE)
    video_id = (
        _strip_or_none(player_config.get("video_id"))
        or (url_match.group("id") or url_match.group("embed_id") if url_match else None)
    )
    if not video_id:
        raise ValueError("Could not find video id in X-TG page")

    title = (
        _strip_or_none(player_config.get("video_title"))
        or _strip_or_none(json_ld.get("name"))
        or _search_meta(webpage, "og:title")
        or _search_meta(webpage, "twitter:title")
        or _search_title(webpage)
    )
    if not title:
        raise ValueError("Could not find video title in X-TG page")

    video_src_match = re.search(r"<video[^>]+src=[\"'](?P<value>[^\"']+)", webpage, re.IGNORECASE)
    video_src = video_src_match.group("value") if video_src_match else None
    formats = _build_formats(player_config, json_ld, video_src, canonical_url)
    if not formats:
        raise ValueError("Could not find downloadable formats in X-TG page")

    timestamp = (
        _parse_timestamp(json_ld.get("uploadDate"))
        or _parse_timestamp(_search_meta(webpage, "video:release_date"))
    )
    cast = _split_csv(player_config.get("video_models"))
    uploader = cast[0] if len(cast) == 1 else ", ".join(cast) if cast else None
    thumbnail = (
        _first_url(player_config.get("preview_url"))
        or _first_url(json_ld.get("thumbnailUrl"))
        or _first_url(_search_meta(webpage, "og:image"))
        or _first_url(_search_meta(webpage, "twitter:image"))
    )

    info = {
        "id": video_id,
        "display_id": url_match.group("display_id") if url_match else None,
        "title": title,
        "uploader": uploader,
        "creator": uploader,
        "cast": cast or None,
        "thumbnail": thumbnail,
        "description": (
            _strip_or_none(json_ld.get("description"))
            or _search_meta(webpage, "description")
            or _search_meta(webpage, "og:description")
            or _search_meta(webpage, "twitter:description")
        ),
        "duration": (
            _parse_iso8601_duration(json_ld.get("duration"))
            or _parse_int(_search_meta(webpage, "video:duration"))
        ),
        "timestamp": timestamp,
        "upload_date": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d") if timestamp else None,
        "tags": _split_csv(player_config.get("video_tags")),
        "categories": _split_csv(player_config.get("video_categories")),
        "formats": formats,
        "age_limit": 18,
        "webpage_url": canonical_url,
        "http_headers": {"Referer": canonical_url},
    }
    info.update(_extract_counts(json_ld))
    return {key: value for key, value in info.items() if value not in (None, [], "")}


class XTgTubeIE(InfoExtractor):
    IE_NAME = "x-tg"
    _VALID_URL = _VALID_URL

    def _real_extract(self, url):
        match = self._match_valid_url(url)
        video_id = match.group("id") or match.group("embed_id")
        webpage = self._download_webpage(
            url,
            video_id,
            impersonate=True,
            require_impersonation=True,
        )
        return parse_x_tg_html(webpage, url)


class XTgTubeModelIE(InfoExtractor):
    IE_NAME = "x-tg:model"
    _VALID_URL = _MODEL_VALID_URL

    def _download_model_webpage(self, url, playlist_id, page_number=None):
        note = None if page_number is None else f"Downloading model page {page_number}"
        return self._download_webpage(
            url,
            playlist_id,
            note=note,
            impersonate=True,
            require_impersonation=True,
        )

    def _entries(self, first_url, playlist_id, first_webpage):
        page_queue = [(first_url, first_webpage)]
        seen_pages = set()
        seen_video_urls = set()

        while page_queue:
            page_url, webpage = page_queue.pop(0)
            normalized_page_url = _normalize_url(page_url)
            if normalized_page_url in seen_pages:
                continue
            page_number = len(seen_pages) + 1
            seen_pages.add(normalized_page_url)

            if webpage is None:
                webpage = self._download_model_webpage(page_url, playlist_id, page_number)

            for video_url in _extract_model_video_urls(webpage, page_url):
                if video_url in seen_video_urls:
                    continue
                seen_video_urls.add(video_url)
                yield self.url_result(video_url, ie=XTgTubeIE.ie_key())

            queued_page_urls = {_normalize_url(item[0]) for item in page_queue}
            for next_page_url in _extract_model_page_urls(webpage, page_url, playlist_id):
                normalized_next_page_url = _normalize_url(next_page_url)
                if normalized_next_page_url in seen_pages or normalized_next_page_url in queued_page_urls:
                    continue
                queued_page_urls.add(normalized_next_page_url)
                page_queue.append((next_page_url, None))

    def _real_extract(self, url):
        playlist_id = self._match_id(url)
        webpage = self._download_model_webpage(url, playlist_id)
        person = _find_json_ld_person(webpage)
        canonical_url = _search_canonical(webpage) or url
        title = (
            _strip_or_none(person.get("name"))
            or _clean_model_title(_search_meta(webpage, "og:title"))
            or _clean_model_title(_search_meta(webpage, "twitter:title"))
            or _clean_model_title(_search_title(webpage))
            or playlist_id.replace("-", " ").title()
        )
        description = (
            _search_meta(webpage, "description")
            or _search_meta(webpage, "og:description")
            or _search_meta(webpage, "twitter:description")
            or _strip_or_none(person.get("description"))
        )

        return self.playlist_result(
            self._entries(url, playlist_id, webpage),
            playlist_id,
            title,
            description,
        )
