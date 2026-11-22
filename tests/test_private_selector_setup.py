import importlib

from tameru import format_adapters
from tameru.structured_reports import ReportSelection

transcript = importlib.import_module("tameru.transcript")


def test_plain_text_skips_report_selector_setup(monkeypatch):
    calls = []
    real = format_adapters._query_selectors

    def spy(query):
        calls.append(query)
        return real(query)

    monkeypatch.setattr(format_adapters, "_query_selectors", spy)
    assert format_adapters.adapt_report("ordinary text", "needle") is None
    assert calls == []
    assert not format_adapters.adapt_format("ordinary text", "needle", format_name="text").applied
    assert calls == ["needle"]


def test_accepted_report_constructs_selectors_once(monkeypatch):
    calls = []

    def selectors(query):
        calls.append(query)
        return ("needle",)

    monkeypatch.setattr(format_adapters, "_query_selectors", selectors)
    monkeypatch.setattr(format_adapters, "select_report", lambda *args, **kwargs: ReportSelection("json", "{}", 2, 1, "selected"))
    result = format_adapters.adapt_format('{"records":[]}', "needle", format_name="json")
    assert result.applied
    assert calls == ["needle"]


def test_json_answer_query_is_casefolded_once_and_keeps_substring_exclusion(monkeypatch):
    calls = []

    class Query(str):
        def casefold(self):
            calls.append(self)
            return super().casefold()

    monkeypatch.setattr(transcript, "preprocess_json", lambda content, query: content)
    monkeypatch.setattr(transcript, "_json_query_needles", lambda query: ["target"])
    text = '[{"target":"one"},{"target":"two"},{"target":"tar"},{"target":true}]'
    answers, booleans = transcript._json_query_answer_requirements(text, Query("TARGET"))
    assert answers == {"one", "two"}
    assert booleans == {("target", True)}
    assert len(calls) == 1


def test_empty_and_malformed_json_answers_remain_empty():
    for content in ("", "{broken", "[]"):
        assert transcript._json_query_answer_requirements(content, "target") == (set(), set())
