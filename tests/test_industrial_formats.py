"""Industrial format adapter contracts."""
from __future__ import annotations

import csv
import io
import json
import unittest

from tameru.compress_context import compress_context
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


class SarifRecordTests(unittest.TestCase):
    @staticmethod
    def report():
        def note(i):
            return json.dumps({"ruleId": f"style.rule{i}", "level": "note",
                               "message": {"text": f"ordinary style issue {i}"}})
        finding = ('{"ruleId":"security.query", "level":"error",'
                   '"message":{"text":"SQL injection in checkout"},'
                   '"locations":[{"physicalLocation":{"artifactLocation":{"uri":"src/cart.py"},'
                   '"region":{"startLine":77}}}],"properties":{"score":1.10,"literal":"a  b"}}')
        source = ('{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"scanner"}},'
                  '"results":[' + ",".join([*(note(i) for i in range(60)), finding]) + ']}]}')
        return source, finding

    def test_retains_complete_raw_finding_and_metadata(self):
        source, finding = self.report()
        adapted = adapt_format(source, "what security finding")
        self.assertTrue(adapted.applied)
        self.assertIn(finding, adapted.text)
        self.assertEqual((adapted.total_records, adapted.kept_records), (61, 2))
        body = json.loads(adapted.text.split("\n", 1)[1])
        self.assertEqual(body["runs"][0]["tool"]["driver"]["name"], "scanner")
        self.assertEqual(len(body["runs"][0]["results"]), 2)

    def test_engine_does_not_detach_file_location_or_reorder_records(self):
        source, finding = self.report()
        result = compress_context(source, "what security finding", ccr=False, citations=False,
                                  reorder_best=True)
        self.assertFalse(result.fail_open)
        self.assertIn(finding, result.compressed_text)
        self.assertEqual(result.receipt["adapter"]["name"], "sarif")
        self.assertNotIn('"style.rule42"', result.compressed_text)
        again = compress_context(result.compressed_text, "what security finding",
                                 ccr=False, citations=False)
        self.assertEqual(again.compressed_text, result.compressed_text)

    def test_query_matching_note_is_kept(self):
        source, finding = self.report()
        result = adapt_format(source, "style.rule42")
        self.assertIn('"style.rule42"', result.text)
        self.assertIn(finding, result.text)
        self.assertEqual(result.kept_records, 3)

    def test_unknown_severity_and_missing_level_are_preserved(self):
        source, finding = self.report()
        for replacement in ('"level":"custom"', '"severity":"error"'):
            changed = source.replace('"level":"error"', replacement)
            result = adapt_format(changed, "security finding")
            self.assertIn(finding.replace('"level":"error"', replacement), result.text)

    def test_duplicate_keys_and_limits_fail_open(self):
        source, _ = self.report()
        duplicate = source.replace('"startLine":77', '"startLine":77,"startLine":88')
        for text, limits in ((duplicate, None), (source, FormatLimits(max_records=10))):
            result = adapt_format(text, "security finding", limits)
            self.assertFalse(result.applied)
            self.assertFalse(result.structurally_valid)
            self.assertEqual(result.text, text)
        result = compress_context(duplicate, "security finding", ccr=False, citations=False)
        self.assertTrue(result.fail_open)
        self.assertEqual(result.compressed_text, duplicate)

    def test_explicit_disable_leaves_report_unadapted(self):
        source, _ = self.report()
        result = adapt_format(source, "security finding", allow_reports=False)
        self.assertFalse(result.applied)
        self.assertEqual(result.text, source)

    def test_each_run_keeps_its_diagnostic_and_shared_metadata(self):
        source, _ = self.report()
        root = json.loads(source)
        second = json.loads(source)["runs"][0]
        second["results"][-1]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = "src/other.py"
        root["runs"].append(second)
        result = adapt_format(json.dumps(root), "security finding")
        parsed = json.loads(result.text.split("\n", 1)[1])
        self.assertEqual([len(run["results"]) for run in parsed["runs"]], [2, 2])
        self.assertIn("src/cart.py", result.text)
        self.assertIn("src/other.py", result.text)
        self.assertEqual((result.total_records, result.kept_records), (122, 4))

    def test_nested_result_field_limit_is_enforced(self):
        source, _ = self.report()
        result = adapt_format(source, "security finding", FormatLimits(max_fields=3))
        self.assertFalse(result.structurally_valid)
        self.assertFalse(result.applied)
        self.assertEqual(result.text, source)

    def test_truncated_report_fails_open_instead_of_becoming_prose(self):
        source, _ = self.report()
        truncated = source[:-1]
        result = compress_context(truncated, "security finding", ccr=False, citations=False)
        self.assertTrue(result.fail_open)
        self.assertEqual(result.compressed_text, truncated)

    def test_custom_gap_marker_is_outside_the_json_document(self):
        source, finding = self.report()
        calls = []
        def marker(omitted, total):
            calls.append((omitted, total))
            return "<original available>"
        result = adapt_format(source, "security finding", gap_marker=marker)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], len(source))
        self.assertGreater(calls[0][0], 0)
        self.assertIn(finding, result.text)
        json.loads(result.text.split("\n", 2)[2])


def _notebook():
    cell = '{"cell_type":"code","source":["import library_x9\\n"],"outputs":[]}'
    executed = '{"cell_type":"code","source":["counter += 1\\n"],"execution_count":7,"outputs":[]}'
    failing = ('{"cell_type":"code","source":["cart.total()\\n"],"id":"failed-cell","execution_count":9,'
               '"metadata":{"measurement":1.234567890123456789},'
               '"outputs":[{"output_type":"error","ename":"AttributeError",'
               '"evalue":"checkout.cart has no total","traceback":'
               '["Traceback (most recent call last)","AttributeError: checkout.cart has no total"]}]}')
    cells = ",".join([cell] * 60 + [executed, executed, failing])
    return ('{"nbformat":4,"nbformat_minor":2,"metadata":{"language_info":{"name":"python"}},'
            '"cells":[' + cells + ']}'), failing


def _graphql():
    errors = ",".join(
        '{"message":"warning %d","path":["field",%d],"extensions":{"severity":"WARN"}}' % (i, i)
        for i in range(40))
    internal = ('{"message":"INTERNAL_ERROR: cannot resolve cart.total",'
                '"path":["checkout","total"],"locations":[{"line":3,"column":5}],'
                '"extensions":{"code":"INTERNAL_ERROR"}}')
    return ('{"data":null,"errors":[' + errors + ',' + internal +
            '],"extensions":{"requestId":"req-9001","meta":1.234567890123456789}}')


class NotebookRecordTests(unittest.TestCase):
    def test_identical_unexecuted_cells_fold_once_with_positions(self):
        source, failing = _notebook()
        adapted = adapt_format(source, "why did the cell fail")
        self.assertTrue(adapted.applied)
        self.assertEqual(adapted.format, "notebook")
        self.assertEqual((adapted.total_records, adapted.kept_records), (63, 4))
        self.assertIn("original positions (1-based): 1,61,62,63", adapted.text)
        self.assertIn(failing, adapted.text)
        body = json.loads(adapted.text.split("\n", 1)[1])
        self.assertEqual([c for c in body["cells"] if c.get("execution_count") == 7],
                         [{"cell_type": "code", "source": ["counter += 1\n"],
                           "execution_count": 7, "outputs": []}] * 2)
        self.assertEqual(body["metadata"]["language_info"]["name"], "python")

    def test_engine_uses_notebook_adapter_and_stays_byte_stable(self):
        source, failing = _notebook()
        result = compress_context(source, "why did the cell fail", ccr=False, citations=False)
        self.assertFalse(result.fail_open)
        self.assertEqual(result.receipt["adapter"]["name"], "notebook")
        self.assertIn(failing, result.compressed_text)
        again = compress_context(result.compressed_text, "why did the cell fail",
                                 ccr=False, citations=False)
        self.assertEqual(again.compressed_text, result.compressed_text)
        spaced = failing.replace(',"metadata":', ',\n\n"metadata":')
        spaced_source = source.replace(failing, spaced)
        spaced_result = compress_context(spaced_source, "why did the cell fail",
                                         ccr=False, citations=False)
        self.assertIn(spaced, spaced_result.compressed_text)
        json.loads(spaced_result.compressed_text.split("\n", 1)[1])

    def test_query_matching_unexecuted_cells_keep_everything(self):
        source, _ = _notebook()
        adapted = adapt_format(source, "import library_x9")
        self.assertFalse(adapted.applied)
        self.assertEqual(adapted.text, source)
        self.assertEqual((adapted.total_records, adapted.kept_records), (63, 63))

    def test_malformed_notebook_structures_preserve_the_original(self):
        source, _ = _notebook()
        variants = (
            source.replace('"execution_count":7', '"execution_count":7,"execution_count":8', 1),
            source.replace('"execution_count":7', r'"execution_count":7,"execution_co\u0075nt":8', 1),
            source.replace('"cell_type":"code"', '"cell_type":"unknown"', 1),
            source[:len(source) - 50],
            source + '\nnot-json',
        )
        for text in variants:
            result = adapt_format(text, "why did the cell fail")
            self.assertEqual(result.text, text)
            self.assertFalse(result.structurally_valid)
        result = adapt_format(source, "why did the cell fail", FormatLimits(max_records=10))
        self.assertEqual(result.text, source)
        self.assertFalse(result.structurally_valid)
        for text in variants:
            engine = compress_context(text, "why did the cell fail", ccr=False, citations=False)
            self.assertEqual(engine.compressed_text, text)


class GraphqlRecordTests(unittest.TestCase):
    def test_errors_response_is_preserved_whole(self):
        source = _graphql()
        result = compress_context(source, "what failed", ccr=False, citations=False)
        self.assertEqual(result.compressed_text, source)
        adapted = adapt_format(source, "what failed")
        self.assertEqual(adapted.format, "graphql")
        self.assertEqual((adapted.total_records, adapted.kept_records), (41, 41))
        self.assertFalse(adapted.applied)

    def test_graphql_refusals_and_empty_errors(self):
        source = _graphql()
        duplicate = source.replace('"message":"warning 0"',
                                 '"message":"warning 0","message":"dup"', 1)
        result = adapt_format(duplicate, "what failed")
        self.assertEqual(result.text, duplicate)
        self.assertFalse(result.structurally_valid)
        result = adapt_format(source, "what failed", FormatLimits(max_records=10))
        self.assertEqual(result.text, source)
        self.assertFalse(result.structurally_valid)
        suffix = source + '\nnot-json'
        result = adapt_format(suffix, "what failed")
        self.assertEqual(result.text, suffix)
        self.assertFalse(result.structurally_valid)
        control = "\n".join(json.dumps({"id": i, "msg": "line"}) for i in range(5))
        self.assertTrue(adapt_format(control, "what failed").structurally_valid)
        glued = source + '{"also":"object"}'
        result = adapt_format(glued, "what failed")
        self.assertEqual(result.text, glued)
        self.assertFalse(result.structurally_valid)
        empty = '{"data":{"items":[]},"errors":[]}'
        self.assertNotEqual(adapt_format(empty, "what failed").format, "graphql")




class LcovRecordTests(unittest.TestCase):
    @staticmethod
    def _quiet(index=0):
        return ("SF:src/quiet%d.py\nDA:1,1\nDA:2,1\nLF:2\nLH:2\nend_of_record\n" % index)

    @staticmethod
    def _target():
        lines = ["TN:", "SF:src/checkout.py"]
        lines += ["DA:%d,%d" % (i, 0 if i in (77, 78) else 1) for i in range(1, 101)]
        lines += ["LF:100", "LH:98", "end_of_record"]
        return "\n".join(lines) + "\n"

    def test_uncovered_line_rows_survive_whole_file_selection(self):
        result = compress_context(self._target(), "uncovered checkout lines",
                                  ccr=False, citations=False)
        self.assertIn("DA:77,0", result.compressed_text)
        self.assertIn("DA:78,0", result.compressed_text)
        self.assertIn(self._target().rstrip("\n"), result.compressed_text)
        again = compress_context(result.compressed_text, "uncovered checkout lines",
                                 ccr=False, citations=False)
        self.assertEqual(again.compressed_text, result.compressed_text)
        source = "".join(self._quiet(i) for i in range(20)) + self._target()
        adapted = adapt_format(source, "uncovered checkout lines")
        self.assertEqual(adapted.format, "lcov")
        self.assertEqual((adapted.total_records, adapted.kept_records), (21, 2))
        self.assertIn("DA:77,0", adapted.text)
        self.assertIn("DA:78,0", adapted.text)
        quiet = ''.join(self._quiet(i) for i in range(20))
        broad = adapt_format(quiet, 'list all covered files')
        self.assertEqual(broad.text, quiet)
        self.assertFalse(broad.applied)

    def test_tn_inheritance_and_refusals(self):
        def covered(path):
            return "SF:%s\nDA:1,1\nLF:1\nLH:1\nend_of_record\n" % path
        fat = ("SF:src/skip.py\n" + "".join("DA:%d,1\n" % i for i in range(1, 81))
               + "LF:80\nLH:80\nend_of_record\n")
        source = ("TN:alpha\n" + covered("src/a.py") + "TN:beta\n" + covered("src/b.py")
                  + "TN:alpha\n" + fat + "SF:src/checkout.py\nDA:1,0\nDA:2,1\nLF:2\nLH:1\nend_of_record\n")
        adapted = adapt_format(source, "checkout")
        self.assertEqual((adapted.total_records, adapted.kept_records), (4, 3))
        self.assertIn("TN:alpha\nSF:src/checkout.py\n", adapted.text)
        unknown = covered("src/weird.py").replace("DA:1,1\n", "DA:1,1\nVER:9\n")
        variant = source + unknown
        adapted2 = adapt_format(variant, "checkout")
        self.assertEqual((adapted2.total_records, adapted2.kept_records), (5, 4))
        self.assertIn("SF:src/weird.py", adapted2.text)
        for text, limits in ((source, FormatLimits(max_records=3)),
                             (source, FormatLimits(max_record_chars=50)),
                             (source[: -len("end_of_record\n")], None)):
            result = adapt_format(text, "checkout", limits)
            self.assertEqual(result.text, text)
            self.assertFalse(result.structurally_valid)
if __name__ == "__main__":
    unittest.main()


def _junit(ns=""):
    t = ns
    xmlns = " xmlns:junit='urn:junit'" if ns else ""
    props = "".join(
        "<{p}property name='p{i}' value='v{i}'/>\n".format(p=t, i=i) for i in range(80))
    props = props.replace("value='v3'", "value='a>b'")
    failing = (
        "<{p}testcase name='checkout_fails' classname='cart.Cart' file='cart.py'\n"
        "time='1.234567890123456789'>\n"
        "<{p}properties>\n" + props + "</{p}properties>\n"
        "<{p}failure message='boom'><![CDATA[trace </{p}testcase> 日本語]]></{p}failure>\n"
        "</{p}testcase>").format(p=t)
    quiet = "".join(
        "<{p}testcase name='check{i}' classname='cart.Cart' time='0.00{i:02d}' file='cart.py' line='{i}'/>\n".format(p=t, i=i)
        for i in range(40))
    source = ("<?xml version='1.0' encoding='UTF-8'?>\n"
              "<{t}testsuites{xmlns}><{t}testsuite name='checkout' tests='41' failures='1'>\n"
              "<{t}properties><{t}property name='locale' value='日本語'/></{t}properties>\n"
              + quiet + failing +
              "\n<{t}system-out><![CDATA[boot log]]></{t}system-out>\n"
              "</{t}testsuite></{t}testsuites>").format(t=t, xmlns=xmlns)
    return source, failing


class JunitRecordTests(unittest.TestCase):
    def _check(self, source, failing, tag=""):
        import xml.etree.ElementTree as ET
        adapted = adapt_format(source, "which test failed")
        self.assertTrue(adapted.applied)
        self.assertTrue(adapted.structurally_valid)
        self.assertEqual(adapted.format, "junit")
        self.assertEqual((adapted.total_records, adapted.kept_records), (41, 2))
        self.assertIn(failing, adapted.text)
        body = adapted.text.split("\n", 1)[1]
        root = ET.fromstring(body.lstrip("\ufeff"))
        suite = root.find(tag + "testsuite")
        self.assertEqual(suite.get("tests"), "41")
        self.assertEqual(suite.get("failures"), "1")
        self.assertIsNotNone(suite.find(tag + "properties"))
        self.assertIsNotNone(suite.find(tag + "system-out"))
        self.assertLess(len(adapted.text), len(source))
        result = compress_context(source, "which test failed", ccr=False, citations=False)
        self.assertIn(failing, result.compressed_text)
        again = compress_context(result.compressed_text, "which test failed", ccr=False, citations=False)
        self.assertEqual(again.compressed_text, result.compressed_text)
        wrapped = json.dumps({"output": source, "exit_code": 1})
        wresult = compress_context(wrapped, "which test failed", ccr=False, citations=False)
        self.assertIn(failing, wresult.compressed_text)
        self.assertEqual(json.loads(wresult.compressed_text.split("\n", 1)[0])["exit_code"], 1)

    def test_complete_failure_record_and_suite_metadata(self):
        source, failing = _junit()
        self._check(source, failing)
        ns_source, ns_failing = _junit(ns="junit:")
        self._check(ns_source, ns_failing, tag="{urn:junit}")
        bom = "\ufeff" + source
        self._check(bom, failing)

    def test_conservative_boundaries(self):
        source, _ = _junit()
        unchanged = adapt_format(source, "slowest duration")
        self.assertEqual(unchanged.text, source)
        unknown = source.replace("line='39'/>", "line='39' odd='x'/>", 1)
        kept_unknown = adapt_format(unknown, "which test failed")
        self.assertEqual(kept_unknown.kept_records, 3)
        self.assertIn("odd='x'", kept_unknown.text)
        variants = [
            (source, FormatLimits(max_records=40)),
            (source, FormatLimits(max_record_chars=50)),
            (source, FormatLimits(max_fields=2)),
            (source[:len(source) - 100], None),
            (source.replace("file='cart.py'", "file='cart.py' file='dup.py'", 1), None),
            (source.replace("<testsuites>", "<!DOCTYPE testsuites [<!ENTITY e 'x'>]><testsuites>", 1), None),
            (source.replace("<testsuite name=", "<!-- note --><testsuite name=", 1), None),
        ]
        for text, limits in variants:
            result = adapt_format(text, "which test failed", limits)
            self.assertEqual(result.text, text)
            self.assertFalse(result.structurally_valid)
        plain = "<catalog><item id='1'>alpha</item></catalog>"
        self.assertNotEqual(adapt_format(plain, "alpha").format, "junit")


if __name__ == "__main__":
    unittest.main()
