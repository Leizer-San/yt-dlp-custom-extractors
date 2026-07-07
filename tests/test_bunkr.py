import unittest

from yt_dlp_plugins.extractor.bunkr import (
    BAlbumsIndexIE,
    BunkrAlbumIE,
    BunkrIE,
    _extract_balbums_targets,
    _extract_bunkr_album_entries,
    _signed_media_url,
)


class BunkrParserTests(unittest.TestCase):
    def test_url_matching(self):
        self.assertTrue(BunkrIE.suitable("https://bunkr.cr/v/example-id"))
        self.assertTrue(BunkrIE.suitable("https://bunkr.cr/f/example-id"))
        self.assertTrue(BunkrAlbumIE.suitable("https://bunkr.cr/a/album-id"))
        self.assertTrue(BAlbumsIndexIE.suitable("https://balbums.st/topvideos?lapse=7d"))
        self.assertFalse(BunkrIE.suitable("https://bunkr.cr/a/album-id"))

    def test_album_entries_only_include_videos(self):
        webpage = """
            <div class="relative group/item theItem" title="clip.mp4">
              <span class="type-Video">Video</span>
              <p class="truncate theName text-center">clip.mp4</p>
              <p class="text-xs theSize mb-1">12.5 MB</p>
              <a href="/f/video-slug"></a>
            </div>
            <div class="relative group/item theItem" title="photo.jpg">
              <span class="type-Image">Image</span>
              <p class="truncate theName text-center">photo.jpg</p>
              <a href="/f/image-slug"></a>
            </div>
        """
        entries = _extract_bunkr_album_entries(webpage, "https://bunkr.cr/a/album-id")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], "https://bunkr.cr/f/video-slug")
        self.assertEqual(entries[0]["title"], "clip.mp4")
        self.assertGreater(entries[0]["filesize_approx"], 12_000_000)

    def test_balbums_targets(self):
        webpage = """
            <a href="https://bunkr.cr/v/video-id">Video</a>
            <a href="https://bunkr.cr/a/album-id">Album</a>
            <a href="https://example.com/ignored">Ignored</a>
        """
        targets = _extract_balbums_targets(webpage)
        self.assertEqual([item["ie_key"] for item in targets], [
            BunkrIE.ie_key(), BunkrAlbumIE.ie_key(),
        ])

    def test_signed_media_url(self):
        signed_url = _signed_media_url(
            "https://cdn.example/video.mp4",
            {"token": "abc", "ex": 123},
        )
        self.assertEqual(signed_url, "https://cdn.example/video.mp4?token=abc&ex=123")


if __name__ == "__main__":
    unittest.main()
