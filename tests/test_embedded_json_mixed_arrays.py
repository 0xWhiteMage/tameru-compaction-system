import json

from tameru.compress_context import _crush_embedded_json


def test_embedded_json_keeps_mixed_arrays_with_object_first():
    payload = json.dumps(
        {"items": [{"name": "artifact-release"}] + ["unclassified data " * 8] * 50}
    )
    text = f"Build result: {payload}\nComplete."

    assert _crush_embedded_json(text, "artifact-release") == text
