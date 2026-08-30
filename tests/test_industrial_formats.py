"""Industrial format adapter contracts."""
from __future__ import annotations

import csv
import io
import json
import unittest

from tameru.format_adapters import FormatLimits, adapt_format, detect_format


class FormatDetectionTests(unittest.TestCase):
    def test_detects_supported_industrial_formats(self):
        cases = {
            "ndjson": "{\"id\":1}\n{\"id\":2}\n{\"id\":3}",
            "csv": "id,name,status\n1,alpha,ok\n2,beta,fail",
            "tsv": "id\tname\tstatus\n1\talpha\tok\n2\tbeta\tfail",
            "markdown": "# Runbook\n\n## Deploy\nUse release-77.",
            "yaml": "services:\n  api:\n    host: prod-77\n",
            "xml": "<catalog>\n<item id=\"1\">alpha</item>\n</catalog>",
            "html": "<!doctype html><html><body>alpha</body></html>",
            "sql": "CREATE TABLE alpha (id int);\nCREATE TABLE beta (id int);",
            "ini": "[alpha]\nhost=alpha-1\n\n[beta]\nhost=beta-2",
            "vertical": "東\n京\n都\n庁\n舎\n案\n内",
        }
        for expected, text in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_format(text), expected)


class NdjsonAdapterTests(unittest.TestCase):
    def test_cjk_selector_does_not_match_shared_single_grapheme(self):
        records = [
            {"id": 1, "city": "東京", "value": "wanted"},
            {"id": 2, "city": "東北", "value": "distractor"},
            {"id": 3, "city": "大阪", "value": "other"},
        ]
        source = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        result = adapt_format(source, "東京")
        self.assertTrue(result.applied)
        self.assertEqual(result.kept_records, 1)
        self.assertIn('"city": "東京"', result.text)
        self.assertNotIn('"city": "東北"', result.text)

    def test_keeps_exact_matching_records_and_valid_ndjson(self):
        lines = [
            json.dumps({"id": index, "device": f"device-{index}", "status": "ok"})
            for index in range(100)
        ]
        source = "\n".join(lines)
        result = adapt_format(source, "status for device-77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "ndjson")
        self.assertEqual(result.total_records, 100)
        self.assertEqual(result.kept_records, 1)
        self.assertEqual(result.text, lines[77])
        for line in result.text.splitlines():
            json.loads(line)

    def test_malformed_record_declines_without_rewrite(self):
        source = '{"id":1}\nnot-json\n{"id":2}'
        result = adapt_format(source, "id 2")
        self.assertFalse(result.applied)
        self.assertEqual(result.text, source)
        self.assertFalse(result.structurally_valid)

    def test_record_limit_declines(self):
        source = "\n".join(json.dumps({"id": index}) for index in range(5))
        result = adapt_format(source, "id 4", FormatLimits(max_records=4))
        self.assertFalse(result.applied)
        self.assertIn("record limit", result.reason)


class DelimitedAdapterTests(unittest.TestCase):
    def test_csv_preserves_quoted_commas_and_embedded_newlines(self):
        source = (
            'id,name,notes\r\n'
            '1,alpha,"ordinary, record"\r\n'
            '77,target,"first line\r\nsecond line device-77"\r\n'
            '120,other,"device-120"\r\n'
        )
        result = adapt_format(source, "device-77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "csv")
        self.assertIn('77,target,"first line\r\nsecond line device-77"', result.text)
        self.assertNotIn("device-120", result.text)
        parsed = list(csv.reader(io.StringIO(result.text)))
        self.assertEqual(parsed[0], ["id", "name", "notes"])
        self.assertEqual(parsed[1][0], "77")

    def test_tsv_keeps_header_and_exact_identifier(self):
        source = "id\tname\tstatus\n12\twidget-12\tready\n120\twidget-120\tfailed"
        result = adapt_format(source, "widget-12")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "tsv")
        self.assertIn("widget-12", result.text)
        self.assertNotIn("widget-120", result.text)


class MarkdownAdapterTests(unittest.TestCase):
    def test_retains_heading_chain_and_atomic_fence(self):
        source = """# Operations

## Archive
Old material.

## Deployment
### Production
```yaml
host: prod-77
retry: 4
```
Explanation for prod-77.

## Appendix
Unrelated.
"""
        result = adapt_format(source, "prod-77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "markdown")
        self.assertIn("# Operations", result.text)
        self.assertIn("## Deployment", result.text)
        self.assertIn("### Production", result.text)
        self.assertIn("```yaml\nhost: prod-77\nretry: 4\n```", result.text)
        self.assertNotIn("## Appendix", result.text)


class YamlAdapterTests(unittest.TestCase):
    def test_retains_only_matching_list_item_with_parent_key(self):
        source = """services:
  - host: prod-77
    role: api
  - host: worker-9
    role: worker
logging:
  level: info
"""
        result = adapt_format(source, "prod-77")
        self.assertTrue(result.applied)
        self.assertIn("services:", result.text)
        self.assertIn("  - host: prod-77", result.text)
        self.assertIn("    role: api", result.text)
        self.assertNotIn("worker-9", result.text)
        self.assertNotIn("logging:", result.text)

    def test_retains_parent_keys_and_matching_subtree(self):
        source = """services:
  api:
    host: prod-77
    port: 5432
  worker:
    host: worker-9
logging:
  level: info
"""
        result = adapt_format(source, "prod-77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "yaml")
        self.assertIn("services:", result.text)
        self.assertIn("  api:", result.text)
        self.assertIn("    host: prod-77", result.text)
        self.assertIn("    port: 5432", result.text)
        self.assertNotIn("worker-9", result.text)
        self.assertNotIn("logging:", result.text)


class XmlAdapterTests(unittest.TestCase):
    def test_line_oriented_xml_keeps_balanced_root_and_exact_child(self):
        source = """<catalog>
<item id="12">widget-12</item>
<item id="120">widget-120</item>
</catalog>"""
        result = adapt_format(source, "widget-12")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "xml")
        self.assertEqual(
            result.text,
            '<catalog>\n<item id="12">widget-12</item>\n</catalog>',
        )
        self.assertNotIn("widget-120", result.text)

    def test_multiline_xml_declines_conservatively(self):
        source = "<catalog>\n<item>\nwidget-12\n</item>\n</catalog>"
        result = adapt_format(source, "widget-12")
        self.assertFalse(result.applied)
        self.assertEqual(result.text, source)


class SqlAdapterTests(unittest.TestCase):
    def test_keeps_exact_statements_and_ignores_semicolon_in_string(self):
        source = """CREATE TABLE users (id int, note text);
INSERT INTO users VALUES (1, 'ordinary; note');
CREATE TABLE orders_77 (id int, status text);
INSERT INTO orders_77 VALUES (77, 'ready; verified');
CREATE TABLE archive (id int);
"""
        result = adapt_format(source, "orders_77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "sql")
        self.assertIn("CREATE TABLE orders_77", result.text)
        self.assertIn("'ready; verified'", result.text)
        self.assertNotIn("CREATE TABLE users", result.text)
        self.assertNotIn("CREATE TABLE archive", result.text)


class IniAdapterTests(unittest.TestCase):
    def test_keeps_matching_section_exactly(self):
        source = """[alpha]
host=alpha-1
port=1001

[production]
host=prod-77
port=5432

[archive]
host=archive-9
"""
        result = adapt_format(source, "prod-77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "ini")
        self.assertIn("[production]", result.text)
        self.assertIn("port=5432", result.text)
        self.assertNotIn("[archive]", result.text)


class HtmlAdapterTests(unittest.TestCase):
    def test_line_oriented_html_keeps_wrappers_and_matching_section(self):
        source = """<!doctype html>
<html>
<body>
<section id="alpha">ordinary</section>
<section id="prod-77">critical</section>
<section id="archive">old</section>
</body>
</html>"""
        result = adapt_format(source, "prod-77")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "html")
        self.assertIn("<!doctype html>", result.text)
        self.assertIn('<section id="prod-77">critical</section>', result.text)
        self.assertNotIn("ordinary", result.text)
        self.assertNotIn("archive", result.text)


class VerticalAdapterTests(unittest.TestCase):
    def test_vertical_ocr_columns_match_in_logical_source_order(self):
        source = "東\n京\n都\n庁\n舎\n\n大\n阪\n支\n店\n案\n内"
        result = adapt_format(source, "東京都庁舎")
        self.assertTrue(result.applied)
        self.assertEqual(result.format, "vertical")
        self.assertEqual(result.text, "東\n京\n都\n庁\n舎")


if __name__ == "__main__":
    unittest.main()
