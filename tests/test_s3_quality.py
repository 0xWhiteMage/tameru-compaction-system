"""S3 answer-quality harness (plan 2026-11-22, P4): fixed prompt set, OpenAI-compatible
endpoint, per-result endpoint/model/digest recording."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.engine_bench import s3_quality as s3


# --- the fixed prompt set ----------------------------------------------------

def test_prompt_set_is_registered_and_reproducible():
    spec = s3.build_prompt_set()
    assert spec == s3.build_prompt_set()                       # deterministic build
    text = json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    assert text == s3.PROMPT_SET_FILE.read_text(encoding="utf-8")
    pinned = s3.PROMPT_SET_HASH_FILE.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(s3.PROMPT_SET_FILE.read_bytes()).hexdigest() == pinned


def test_prompt_set_shape():
    spec = s3.load_prompt_set()
    assert spec["needles"] and spec["prompts"]
    for p in spec["prompts"]:
        assert p["needle"] in spec["needles"]
        assert p["window_tokens"] in s3.WINDOWS_TOKENS
        assert p["depth"] in s3.DEPTHS
        assert p["expects"] and p["question"]
    # one prompt per family per window; the needle is a dev case of that family
    assert len(spec["prompts"]) == len(spec["needles"]) * len(s3.WINDOWS_TOKENS)
    for cid, n in spec["needles"].items():
        assert n["text"] and n["gold"]


def test_load_prompt_set_refuses_a_drifted_file(tmp_path, monkeypatch):
    drifted = tmp_path / "s3_prompts.json"
    drifted.write_text('{"prompts": []}', encoding="utf-8")
    monkeypatch.setattr(s3, "PROMPT_SET_HASH_FILE", s3.PROMPT_SET_HASH_FILE)  # real pin
    with pytest.raises(SystemExit):
        s3.load_prompt_set(drifted)


# --- context rendering -------------------------------------------------------

def test_render_context_places_the_needle_at_the_registered_depth():
    spec = s3.load_prompt_set()
    p = spec["prompts"][0]
    ctx = s3.render_context(p, spec["needles"], spec)
    needle = spec["needles"][p["needle"]]["text"]
    target = int(p["window_tokens"] * spec["chars_per_token"])
    assert len(ctx) == pytest.approx(target, rel=0.01)
    at = ctx.find(needle)
    assert at >= 0 and at / (len(ctx) - len(needle)) == pytest.approx(p["depth"], abs=0.05)
    # deterministic
    assert ctx == s3.render_context(p, spec["needles"], spec)


def test_messages_are_endpoint_independent():
    spec = s3.load_prompt_set()
    p = spec["prompts"][0]
    msgs = s3.messages(spec, p, "CTX")
    assert msgs[0]["role"] == "system" and "CTX" in msgs[1]["content"]
    assert p["question"] in msgs[1]["content"]


# --- the endpoint ------------------------------------------------------------

def _transport(models=None, tags=None, answer="ok"):
    def t(method, url, payload, timeout):
        if url.endswith("/chat/completions"):
            assert payload["model"] and payload["temperature"] == 0.0
            return 200, {"choices": [{"message": {"content": answer}}]}
        if url.endswith("/models"):
            return 200, {"data": models or []}
        if url.endswith("/api/tags"):
            return 200, {"models": tags or []}
        return 404, {}
    return t


def test_chat_posts_openai_shape_and_returns_content():
    ep = s3.Endpoint("http://host:1/v1", "m", transport=_transport(answer="the answer"))
    assert ep.chat([{"role": "user", "content": "hi"}]) == "the answer"


def test_identity_reads_v1_models_and_ollama_digest():
    ep = s3.Endpoint("http://host:1/v1", "qwen:7b",
                     transport=_transport(models=[{"id": "qwen:7b"}],
                                          tags=[{"name": "qwen:7b", "digest": "sha256:abc"}]))
    ident = ep.identity()
    assert ident == {"served_model_id": "qwen:7b", "model_digest": "sha256:abc"}
    assert ep.identity() is ident                                   # cached


def test_identity_survives_endpoints_without_a_digest():
    ep = s3.Endpoint("http://host:1/v1", "m", transport=_transport(models=[{"id": "m"}]))
    ident = ep.identity()
    assert ident["served_model_id"] == "m" and ident["model_digest"] is None


def test_endpoint_error_names_the_url():
    def down(method, url, payload, timeout):
        raise OSError("refused")
    ep = s3.Endpoint("http://down:9/v1", "m", transport=down)
    with pytest.raises(s3.EndpointError, match="down:9"):
        ep.chat([])


# --- scoring and the runner --------------------------------------------------

def test_score_answer_counts_normalized_needles():
    hit, score = s3.score_answer("The ACME-SYNC-90-X pod went OutOfSync; sync failed: 70 pods.",
                                 ["acme-sync-90-x", "sync failed: 70", "no-such"])
    assert (hit, score) == (2, pytest.approx(2 / 3))
    assert s3.score_answer("anything", []) == (0, 1.0)


def _tiny_spec():
    return {
        "system": "s", "user_template": "{context}\n{question}", "chars_per_token": 1.0,
        "needles": {
            "n1": {"family": "f", "text": "needle text with gold-9"},
            "n2": {"family": "g", "text": "filler text"},
        },
        "prompts": [{"id": "s3-f-w1", "family": "f", "needle": "n1",
                     "window_tokens": 30, "depth": 0.5,
                     "question": "q?", "expects": ["gold-9", "missing-needle"]}],
    }


def test_run_s3_records_endpoint_model_and_digest_on_every_row():
    ep = s3.Endpoint("http://local:3/v1", "mod-x",
                     transport=_transport(models=[{"id": "mod-x"}],
                                          tags=[{"name": "mod-x", "digest": "sha256:zz"}],
                                          answer="it is gold-9"))
    rows = s3.run_s3(ep, _tiny_spec(), ["stock"], quiet=True)
    assert len(rows) == 1
    r = rows[0]
    assert r["bench"] == "s3" and r["arm"] == "stock"
    assert (r["endpoint_url"], r["model"]) == ("http://local:3/v1", "mod-x")
    assert r["model_digest"] == "sha256:zz" and r["served_model_id"] == "mod-x"
    assert r["expect_hit"] == 1 and r["expect_total"] == 2 and r["score"] == 0.5
    assert r["error"] is None


def test_run_s3_records_transport_errors_not_raises():
    def down(method, url, payload, timeout):
        raise OSError("refused")
    ep = s3.Endpoint("http://down:9/v1", "m", transport=down)
    rows = s3.run_s3(ep, _tiny_spec(), ["stock"], quiet=True)
    assert rows[0]["score"] is None and "refused" in rows[0]["error"]
    assert rows[0]["endpoint_url"] == "http://down:9/v1"


def test_apply_arm_stock_is_verbatim_and_engine_arms_compress(monkeypatch):
    ctx = "line one\n" * 40
    assert s3.apply_arm("stock", ctx, "q") == ctx
    seen = {}

    def fake_call(profile, text, query):
        seen["profile"] = profile
        from types import SimpleNamespace
        return SimpleNamespace(compressed_text="SHORT", fail_open=False,
                               compression_risk="low", confidence=0.9,
                               tokens_saved=len(ctx) - 5)
    monkeypatch.setattr(s3, "_call", fake_call)
    assert s3.apply_arm("deepseek", ctx, "q") == "SHORT"
    assert seen["profile"] == "deepseek"
    # fail-open returns the original context (the host's honest fallback)
    monkeypatch.setattr(s3, "_call", lambda *a: SimpleNamespace(
        compressed_text="SHORT", fail_open=True, compression_risk="low",
        confidence=0.9, tokens_saved=100))
    assert s3.apply_arm("deepseek", ctx, "q") == ctx


def test_summarise_pooled_and_worst_family():
    rows = [
        {"arm": "stock", "family": "a", "score": 1.0},
        {"arm": "stock", "family": "b", "score": 0.5},
        {"arm": "deepseek", "family": "a", "score": 0.5},
        {"arm": "stock", "family": "c", "score": None},   # errors are excluded
    ]
    s = s3.summarise(rows)
    assert s["stock"]["mean_score"] == pytest.approx(0.75)
    assert s["stock"]["worst_family"] == "b" and s["stock"]["worst_family_score"] == 0.5
    assert s["deepseek"]["mean_score"] == 0.5
