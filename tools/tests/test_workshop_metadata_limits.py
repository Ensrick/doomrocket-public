"""Steamworks byte boundaries on parsed, canonical VMB Workshop metadata.

Primary limits: https://partner.steamgames.com/doc/api/ISteamRemoteStorage#Constants
and https://partner.steamgames.com/doc/api/ISteamUGC#SetItemDescription .
These are buffers of 8000 and 128+1 bytes; reserve one byte for the C terminator.
"""

from pathlib import Path
import sys
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import check_repository as repository


class WorkshopMetadataLimits(unittest.TestCase):
    def failures(self, description, title="Warlock Engineer TEST"):
        failures = []
        repository.check_workshop_metadata_limits(failures, title, description)
        return failures

    def test_description_reserves_terminator_at_8000_byte_buffer_boundary(self):
        self.assertEqual(self.failures("a" * 7999), [])
        for size in (8000, 8001, 8050):
            with self.subTest(size=size):
                failures = self.failures("a" * size)
                self.assertEqual(len(failures), 1)
                self.assertIn(f"description is {size} UTF-8 bytes", failures[0])
                self.assertIn("maximum is 7999", failures[0])

    def test_non_ascii_character_count_cannot_hide_byte_overflow(self):
        self.assertEqual(self.failures("é" * 3999 + "a"), [])
        self.assertIn("8000 UTF-8 bytes", self.failures("é" * 4000)[0])
        self.assertEqual(self.failures("🔥" * 1999 + "abc"), [])
        self.assertIn("8000 UTF-8 bytes", self.failures("🔥" * 1999 + "abcd")[0])

    def test_title_129_byte_buffer_accepts_128_bytes_only(self):
        self.assertEqual(self.failures("description", "t" * 128), [])
        self.assertIn("title is 129 UTF-8 bytes", self.failures("description", "t" * 129)[0])
        self.assertEqual(self.failures("description", "é" * 64), [])
        self.assertIn("title is 130 UTF-8 bytes", self.failures("description", "é" * 65)[0])

    def test_embedded_nul_rejected_in_both_fields_before_c_string_truncation(self):
        for description, title in (("short\0hidden", "title"), ("description", "title\0hidden")):
            with self.subTest(title=title):
                failures = self.failures(description, title)
                self.assertEqual(len(failures), 1)
                self.assertIn("embedded NUL", failures[0])

    def test_multiline_quoted_description_is_unescaped_before_byte_measurement(self):
        text = 'description = "' + "a" * 7997 + r'\"\n' + '";\npublished_id = 3794172730L;'
        value = repository.cfg_value(text, "description")
        self.assertTrue(value.endswith('"\n'))
        self.assertEqual(len(value.encode("utf-8")), 7999)
        self.assertEqual(self.failures(value), [])
        self.assertEqual(repository.cfg_value(text, "published_id"), "3794172730")
        self.assertIn("8000 UTF-8 bytes", self.failures(value + "a")[0])

    def test_literal_multiline_and_canonical_backslash_tab_unescape(self):
        text = 'description = "Line one.\nLine two with \\"quotes\\" and \\\\ slash\\t.";'
        value = repository.cfg_value(text, "description")
        self.assertEqual(value, 'Line one.\nLine two with "quotes" and \\ slash\t.')
        self.assertEqual(self.failures(value), [])

    def test_upload_staging_cr_removal_matches_canonical_wire_value(self):
        self.assertEqual(self.failures("a" * 7999 + "\r" * 20), [])
        self.assertIn("8000 UTF-8 bytes", self.failures("a" * 7999 + "\r\n")[0])

    def test_guard_counts_description_not_total_cfg_file_bytes(self):
        text = 'title = "TEST";\ndescription = "small";\n# ' + "unrelated" * 1000
        self.assertGreater(len(text.encode("utf-8")), 8000)
        self.assertEqual(self.failures(repository.cfg_value(text, "description"),
                                       repository.cfg_value(text, "title")), [])

    def test_actual_repository_metadata_fits_steamworks_limits(self):
        cfg = repository.read("itemV2.cfg")
        failures = self.failures(repository.cfg_value(cfg, "description"),
                                 repository.cfg_value(cfg, "title"))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
