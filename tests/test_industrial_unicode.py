"""Industrial Unicode profiling and segmentation contracts."""
from __future__ import annotations

import unittest

from tameru.compress_context import _extract_terms, compress_context
from tameru.contract_gates import distinctive_query_terms
from tameru.unicode_profile import (
    graphemes,
    matching_shadow,
    profile_text,
    search_units,
    token_units,
)


class GraphemeTests(unittest.TestCase):
    def test_combining_marks_and_indic_virama_stay_atomic(self):
        self.assertEqual(graphemes("A\u0301"), ["A\u0301"])
        self.assertEqual(graphemes("क्\u200dषि"), ["क्\u200dषि"])

    def test_emoji_join_sequence_and_flag_stay_atomic(self):
        self.assertEqual(graphemes("👩\u200d💻"), ["👩\u200d💻"])
        self.assertEqual(graphemes("🇸🇬"), ["🇸🇬"])


class UnicodeProfileTests(unittest.TestCase):
    def test_mixed_arabic_hebrew_latin_is_profiled_in_logical_order(self):
        text = "خطأ DB-77-Z בשירות"
        profile = profile_text(text)
        self.assertEqual(profile.direction, "mixed")
        self.assertTrue({"arabic", "hebrew", "latin"}.issubset(profile.scripts))
        self.assertEqual(profile.bidi_controls, 0)

    def test_bidi_controls_are_counted_and_removed_only_from_matching_shadow(self):
        text = "\u2067שלום\u2069 ID-77 \u202eabc\u202c"
        profile = profile_text(text)
        self.assertEqual(profile.bidi_controls, 4)
        self.assertEqual(profile.bidi_overrides, 1)
        self.assertIn("שלום", matching_shadow(text))
        self.assertNotIn("\u202e", matching_shadow(text))
        self.assertIn("\u202e", text)

    def test_canonical_equivalents_share_matching_shadow(self):
        self.assertEqual(matching_shadow("Café"), matching_shadow("Cafe\u0301"))

    def test_vertical_css_and_ocr_columns_are_hints_not_reordering(self):
        css = '<div style="writing-mode: vertical-rl">東京</div>'
        self.assertTrue(profile_text(css).vertical_hint)
        column = "東\n京\n都\n庁\n舎\n案\n内"
        profile = profile_text(column)
        self.assertTrue(profile.vertical_hint)
        self.assertEqual(graphemes(column.replace("\n", "")), list("東京都庁舎案内"))

    def test_unpaired_surrogate_is_flagged(self):
        self.assertTrue(profile_text("safe\ud800tail").malformed_surrogates)


class SearchUnitTests(unittest.TestCase):
    def test_space_free_southeast_asian_scripts_emit_bounded_ngrams(self):
        thai = search_units("ฐานข้อมูลหลัก")
        lao = search_units("ຖານຂໍ້ມູນຫຼັກ")
        khmer = search_units("មូលដ្ឋានទិន្នន័យ")
        myanmar = search_units("ဒေတာဘေ့စ်")
        self.assertIn("ฐาน", thai)
        self.assertTrue(any(unit.startswith("ຖານ") for unit in lao))
        self.assertTrue(any(len(unit) >= 2 for unit in khmer))
        self.assertTrue(any(len(unit) >= 2 for unit in myanmar))

    def test_identifiers_and_rtl_words_are_searchable_together(self):
        units = search_units("الخادم DB-77-Z فشل")
        self.assertIn("الخادم", units)
        self.assertIn("db-77-z", units)

    def test_non_overlapping_token_units_cover_global_scripts(self):
        self.assertEqual(token_units("שלום עולם"), ["שלום", "עולם"])
        self.assertEqual(token_units("उत्पादन सर्वर"), ["उत्पादन", "सर्वर"])
        self.assertEqual(token_units("数据库"), ["数", "据", "库"])
        self.assertEqual(token_units("👩‍💻"), ["👩‍💻"])


class EngineUnicodeIntegrationTests(unittest.TestCase):
    def test_hebrew_query_terms_drive_lossy_compaction(self):
        query = "מהו שרת הייצור?"
        terms = _extract_terms(query)
        self.assertIn("שרת", terms)
        self.assertTrue(any("שרת" in term for term in distinctive_query_terms(query)))
        filler = "\n\n".join(
            f"רשומת ארכיון {index}: מידע שגרתי על מערכת הבדיקות."
            for index in range(40)
        )
        context = filler + "\n\nשרת הייצור הוא il-prod-77 והיציאה היא 5432.\n\n" + filler
        result = compress_context(context, query, ccr=False, citations=False)
        self.assertFalse(result.fail_open)
        self.assertIn("il-prod-77", result.compressed_text)
        self.assertGreater(result.tokens_saved_pct, 20.0)

    def test_khmer_query_uses_grapheme_ngrams(self):
        query = "តើម៉ាស៊ីនមេផលិតកម្មជាអ្វី?"
        terms = _extract_terms(query)
        self.assertTrue(any("ម៉ាស៊ីន" in term for term in terms))
        filler = "\n\n".join(
            f"កំណត់ត្រា {index}: ព័ត៌មានទូទៅអំពីប្រព័ន្ធសាកល្បង។"
            for index in range(30)
        )
        context = filler + "\n\nម៉ាស៊ីនមេផលិតកម្មគឺ kh-prod-9។\n\n" + filler
        result = compress_context(context, query, ccr=False, citations=False)
        self.assertFalse(result.fail_open)
        self.assertIn("kh-prod-9", result.compressed_text)


if __name__ == "__main__":
    unittest.main()
