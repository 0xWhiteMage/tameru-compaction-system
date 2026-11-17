"""The shared plugin-interface vocabulary: complete, consistent in both languages, and free of cost wording."""
from __future__ import annotations

import json
import re
from pathlib import Path

VOCABULARY = Path(__file__).resolve().parent.parent / "docs" / "ui-vocabulary.json"
PLACEHOLDER = re.compile(r"\{[a-z]+\}")


def load() -> dict:
    return json.loads(VOCABULARY.read_text(encoding="utf-8"))


def strings(node: dict, path: str = "") -> list[tuple[str, dict]]:
    """Every leaf that is an {en, zh} pair."""
    found: list[tuple[str, dict]] = []
    for key, value in node.items():
        if key in {"version", "about", "forbidden", "avoid"}:
            continue
        where = f"{path}.{key}" if path else key
        if isinstance(value, dict) and set(value) == {"en", "zh"}:
            found.append((where, value))
        elif isinstance(value, dict):
            found.extend(strings(value, where))
    return found


def test_every_string_exists_in_both_languages() -> None:
    pairs = strings(load())
    assert len(pairs) > 60
    for where, pair in pairs:
        assert pair["en"].strip() and pair["zh"].strip(), where


def test_placeholders_match_between_languages() -> None:
    for where, pair in strings(load()):
        assert sorted(PLACEHOLDER.findall(pair["en"])) == sorted(PLACEHOLDER.findall(pair["zh"])), where


def test_no_cost_or_saving_wording_in_either_language() -> None:
    data = load()
    for where, pair in strings(data):
        for language in ("en", "zh"):
            text = pair[language].lower()
            for word in data["forbidden"][language]:
                # English words match from the start of a word ("sav" catches "save" and "saving"; "gain" does not catch "again").
                # Chinese words are plain substrings.
                hit = re.search(r"\b" + re.escape(word), text) if language == "en" else word in text
                assert not hit, f"{where} ({language}) contains '{word}'"


def test_the_ai_is_called_the_ai() -> None:
    data = load()
    for where, pair in strings(data):
        text = pair["en"].lower()
        for word in data["avoid"]["en"]:
            assert word not in text, f"{where} says '{word}'; say 'the AI' or 'context'"


def test_the_four_strengths_and_status_phrases_the_spec_names_are_all_there() -> None:
    data = load()
    assert [data["strength"][key]["name"]["en"] for key in ("off", "less", "normal", "more")] == ["Off", "Less", "Normal", "More"]
    for key in ("notConnected", "notRunning", "notRunningRetrying", "problem", "waitingStep", "off", "shortened", "keptOnly", "idleUntil", "idle"):
        assert key in data["status"], key
    assert data["brand"]["kana"]["en"] == "(ためる)", "ASCII parentheses around the kana"
    assert set(data["emptyReasons"]) == {"belowStart", "noCandidates", "notConfident", "tooSmall", "engineSilent", "off"}
