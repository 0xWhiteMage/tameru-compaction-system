import json
from types import SimpleNamespace

import pytest

import tameru.compress_context as cc


@pytest.mark.parametrize("fail_on_output", [False, True])
def test_embedded_json_keeps_envelope_when_serializer_hits_depth_limit(
    monkeypatch, fail_on_output
):
    relevant = {"name": "artifact-release"}
    text = "Build result: " + json.dumps(
        {"items": [relevant] + [{"name": "ordinary-record"}] * 50}
    )

    def dumps(value, **kwargs):
        if ("indent" in kwargs) == fail_on_output:
            raise RecursionError("encoder recursion limit")
        return json.dumps(value, **kwargs)

    monkeypatch.setattr(cc, "json", SimpleNamespace(dumps=dumps))
    assert cc._crush_embedded_json(text, "artifact-release") == text
