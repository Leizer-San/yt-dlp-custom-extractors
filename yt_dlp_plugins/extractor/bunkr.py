import json
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    determine_ext,
    int_or_none,
    mimetype2ext,
    parse_filesize,
    update_url_query,
    url_or_none,
)


_BUNKR_HOST_RE = r"(?:www\.)?bunkr\.cr"
_BUNKR_FILE_VALID_URL = rf"https?://{_BUNKR_HOST_RE}/(?:v|f)/(?P<id>[^/?#]+)"
_BUNKR_ALBUM_VALID_URL = rf"https?://{_BUNKR_HOST_RE}/a/(?P<id>[^/?#]+)"
_BALBUMS_VALID_URL = (
    r"https?://(?:www\.)?balbums\.st/"
    r"(?P<section>topvideos|topalbums)?/?(?:[?#].*)?$"
)
_ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_THE_ITEM_RE = re.compile(
    r"(?=<div\b[^>]*\bclass=[\"'][^\"']*\btheItem\b[^\"']*[\"'])",
    re.IGNORECASE,
)


def _strip_html(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", unescape(value)).strip()
    return value or None


def _decode_js_string(value):
    if not isinstance(value, str):
        return None
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace(r"\/", "/")


def _extract_attrs(attrs_text):
    return {
        match.group("name").lower(): unescape(match.group("value"))
        for match in _ATTR_RE.finditer(attrs_text or "")
    }


def _search_class_text(webpage, class_name):
    match = re.search(
        rf"<(?P<tag>[a-z0-9]+)\b[^>]*\bclass=[\"'][^\"']*\b{re.escape(class_name)}\b[^\"']*[\"'][^>]*>"
        rf"(?P<value>.*?)</(?P=tag)>",
        webpage,
        re.IGNORECASE | re.DOTALL,
    )
    return _strip_html(match.group("value")) if match else None


def _extract_bunkr_album_entries(webpage, page_url):
    entries = []
    seen_urls = set()

    for block in _THE_ITEM_RE.split(webpage):
        if not re.search(r"\btype-Video\b", block, re.IGNORECASE):
            continue
        link_match = re.search(
            r"<a\b(?P<attrs>[^>]*\bhref=[\"'][^\"']*/(?:v|f)/[^\"']+[\"'][^>]*)>",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not link_match:
            continue
        href = _extract_attrs(link_match.group("attrs")).get("href")
        entry_url = urljoin(page_url, href or "")
        entry_match = re.match(_BUNKR_FILE_VALID_URL, entry_url, re.IGNORECASE)
        if not entry_match or entry_url in seen_urls:
            continue
        seen_urls.add(entry_url)

        title = _search_class_text(block, "theName")
        filesize = parse_filesize(_search_class_text(block, "theSize"))
        entry = {
            "_type": "url",
            "url": entry_url,
            "ie_key": BunkrIE.ie_key(),
            "id": entry_match.group("id"),
        }
        if title:
            entry["title"] = title
        if filesize:
            entry["filesize_approx"] = filesize
        entries.append(entry)

    return entries


def _extract_balbums_targets(webpage):
    targets = []
    seen_urls = set()
    for match in re.finditer(r"<a\b(?P<attrs>[^>]+)>", webpage, re.IGNORECASE | re.DOTALL):
        target_url = _extract_attrs(match.group("attrs")).get("href")
        if not target_url or target_url in seen_urls:
            continue
        if re.match(_BUNKR_FILE_VALID_URL, target_url, re.IGNORECASE):
            ie_key = BunkrIE.ie_key()
        elif re.match(_BUNKR_ALBUM_VALID_URL, target_url, re.IGNORECASE):
            ie_key = BunkrAlbumIE.ie_key()
        else:
            continue
        seen_urls.add(target_url)
        targets.append({"_type": "url", "url": target_url, "ie_key": ie_key})
    return targets


def _signed_media_url(media_url, sign_data):
    if not isinstance(sign_data, dict):
        return None
    token = sign_data.get("token")
    expires = sign_data.get("ex")
    if not token or expires is None:
        return None
    return update_url_query(media_url, {"token": token, "ex": expires})


class BunkrIE(InfoExtractor):
    IE_NAME = "bunkr"
    _VALID_URL = _BUNKR_FILE_VALID_URL

    def _search_js_var(self, webpage, name):
        value = self._search_regex(
            rf"\bvar\s+{re.escape(name)}\s*=\s*[\"'](?P<value>.*?)[\"']\s*;",
            webpage,
            name,
            default=None,
            group="value",
        )
        return _decode_js_string(value)

    def _real_extract(self, url):
        url_id = self._match_id(url)
        webpage = self._download_webpage(url, url_id)

        media_url = url_or_none(self._search_js_var(webpage, "jsCDN"))
        media_type = self._search_js_var(webpage, "jsType")
        if not media_url or not (media_type or "").lower().startswith("video/"):
            raise ExtractorError("This Bunkr file is not a video", expected=True)

        sign_url = url_or_none(self._search_js_var(webpage, "signUrl"))
        if not sign_url:
            raise ExtractorError("Unable to find Bunkr CDN signing endpoint")
        sign_data = self._download_json(
            sign_url,
            url_id,
            note="Signing Bunkr media URL",
            query={"path": unquote(urlparse(media_url).path)},
        )
        signed_url = _signed_media_url(media_url, sign_data)
        if not signed_url:
            raise ExtractorError("Bunkr CDN signing response is missing a token")

        title = self._html_search_meta("og:title", webpage, fatal=False)
        if not title:
            title = re.sub(r"\s*\|\s*Bunkr\s*$", "", self._html_extract_title(webpage) or "")
        title = _strip_html(title)
        if not title:
            raise ExtractorError("Unable to find Bunkr video title")

        video_id = self._search_js_var(webpage, "jsSlug") or url_id
        filesize = int_or_none(self._search_regex(
            r"\bDebug:\s*Original=.*?,\s*Size=(\d+)",
            webpage,
            "file size",
            default=None,
        ))
        headers = {"Referer": url}
        return {
            "id": video_id,
            "display_id": url_id,
            "title": title,
            "thumbnail": url_or_none(self._html_search_meta("og:image", webpage, fatal=False)),
            "formats": [{
                "url": signed_url,
                "format_id": "http",
                "ext": mimetype2ext(media_type) or determine_ext(title),
                "filesize": filesize,
                "http_headers": headers,
            }],
            "http_headers": headers,
            "webpage_url": url,
        }


class BunkrAlbumIE(InfoExtractor):
    IE_NAME = "bunkr:album"
    _VALID_URL = _BUNKR_ALBUM_VALID_URL

    def _entries(self, url, playlist_id, first_webpage, page_count):
        for page_number in range(1, page_count + 1):
            if page_number == 1:
                webpage = first_webpage
                page_url = url
            else:
                page_url = update_url_query(url, {"page": page_number})
                webpage = self._download_webpage(
                    page_url,
                    playlist_id,
                    note=f"Downloading album page {page_number} of {page_count}",
                )
            yield from _extract_bunkr_album_entries(webpage, page_url)

    def _real_extract(self, url):
        playlist_id = self._match_id(url)
        webpage = self._download_webpage(url, playlist_id)
        title = self._html_search_regex(
            r"<h1\b[^>]*>(?P<title>.*?)</h1>",
            webpage,
            "album title",
            default=None,
            group="title",
        )
        page_numbers = [int(value) for value in re.findall(r"[?&]page=(\d+)", webpage)]
        return self.playlist_result(
            self._entries(url, playlist_id, webpage, max(page_numbers, default=1)),
            playlist_id,
            _strip_html(title),
        )


class BAlbumsIndexIE(InfoExtractor):
    IE_NAME = "balbums:index"
    _VALID_URL = _BALBUMS_VALID_URL

    def _real_extract(self, url):
        section = self._match_valid_url(url).group("section") or "albums"
        page_number = (parse_qs(urlparse(url).query).get("page") or ["1"])[0]
        playlist_id = f"{section}-page-{page_number}"
        webpage = self._download_webpage(url, playlist_id)
        title = self._html_search_regex(
            r"<h1\b[^>]*>(?P<title>.*?)</h1>",
            webpage,
            "page title",
            default=None,
            group="title",
        )
        return self.playlist_result(
            _extract_balbums_targets(webpage),
            playlist_id,
            _strip_html(title),
        )
