"""The S3 answer-quality harness (analysis plan 2026-11-22, P4).

A fixed, registered prompt set is sent to a local model over an OpenAI-compatible
endpoint. The same prompts run unchanged against LM Studio, llama.cpp, vLLM, Ollama
or the GX10 endpoint:

    python -m benchmarks.engine_bench.s3_quality --base-url http://127.0.0.1:1234/v1 \
        --model qwen2.5-7b-instruct --arm stock --arm deepseek --out results/s3.jsonl

The endpoint URL, the model name and the model's digest (where the server exposes
one — Ollama's ``/api/tags``, else the served ``/v1/models`` id) are recorded next to
every result row. The endpoint is a reporting parameter, never a tunable.

The prompt set
--------------
``s3_prompts.json`` is committed and pinned by ``S3-PROMPTS.sha256`` (same convention
as the sealed corpus hashes). It is built once by ``build_prompt_set()`` from the dev
splits of rounds 2-4 — sealed and validation cases are never read — and then frozen:
the file, not the corpus, is what the harness sends. Each prompt is a needle case
(the full text of one dev case) spliced at a registered depth into filler formed by
tiling the *other* needle texts, sized to a gated window. The question is the case's
``task_specific`` query; the expected answers are salient needles derived from its
gold lines. Regenerating the file is a spec change and must be re-registered.

Arms
----
``stock`` sends the rendered context verbatim. ``deepseek``/``hermes`` send the
engine's output under that profile's call settings (run.py ``_call``); when the host
would decline the extract (fail-open, risk, fingerprint loss) the original context
goes instead — the honest host fallback.

Rows: one per (arm, prompt): bench ``s3``, prompt id/family/window/depth, the arm,
endpoint_url/model/model_digest/served_model_id, the answer, per-needle hits and the
score (share of expected needles present), plus ``error`` for transport failures —
a failed call is recorded, never retried into a different result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from tameru.decide import DSH_POLICY, HERMES_POLICY, decide  # noqa: E402

from . import corpus  # noqa: E402
from .run import _call  # noqa: E402

PROMPT_SET_FILE = HERE / "s3_prompts.json"
PROMPT_SET_HASH_FILE = HERE / "S3-PROMPTS.sha256"

# Registered geometry: the gated windows (plan section 3) in tokens, the chars-per-token
# conversion the builder uses, and the needle-depth ladder rotated across families.
WINDOWS_TOKENS = (128_000, 252_000, 500_000, 1_000_000)
CHARS_PER_TOKEN = 4.0
DEPTHS = (0.2, 0.5, 0.8)
ROUNDS = (4, 3, 2)                       # newest material wins when a family spans rounds

SYSTEM = ("You are reading one long terminal transcript. Answer the question at the end "
          "using only facts visible in the transcript. Be brief.")
USER_TEMPLATE = "{context}\n\n---\nQuestion: {question}\nAnswer with the specific names, values and error text shown."

ARMS = ("stock", "deepseek", "hermes")


# ---------------------------------------------------------------- prompt set (registered)

def _dev_cases() -> dict[str, dict]:
    """family -> first dev case, from the newest round that carries the family."""
    out: dict[str, dict] = {}
    loaders = {4: corpus.load_cases_r4, 3: corpus.load_cases_r3, 2: corpus.load_cases_r2}
    for r in ROUNDS:
        for case in loaders[r](("dev",)):
            out.setdefault(case["family"], case)
    return out


def _needles_from_gold(gold: list[str]) -> list[str]:
    """Salient answer needles from a gold line set: entity names, codes and message text.

    A free-form model answer cites the entity and the error string, not the padded table
    row — so a needle is a distinctive token (digits/hyphens, len >= 4) or a ``#``-comment
    tail, at most two per gold line, six per prompt."""
    picks: list[str] = []
    for line in gold:
        per_line: list[str] = []
        tail = line.split("#", 1)[1].strip() if "#" in line else ""
        if len(tail) >= 6:
            per_line.append(tail)
        for tok in line.split():
            if len(per_line) >= 2:
                break
            t = tok.strip("|`:;,()[]{}")
            if len(t) >= 4 and any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t):
                if t not in per_line:
                    per_line.append(t)
        if not per_line:  # nothing salient: the longest token still identifies the fact
            cands = sorted((t.strip("|`:;,()[]{}") for t in line.split()), key=len, reverse=True)
            if cands and cands[0]:
                per_line.append(cands[0])
        picks.extend(per_line)
    return picks[:6]


def build_prompt_set() -> dict:
    """The registered spec: needles keyed by case id, one prompt per (family, window).

    Deterministic over the dev corpora; the committed JSON + its sha256 pin the set."""
    dev = _dev_cases()
    needles = {
        c["id"]: {"family": c["family"], "text": c["text"], "gold": c["gold"]}
        for c in sorted(dev.values(), key=lambda c: c["id"])
    }
    prompts = []
    for i, (family, case) in enumerate(sorted(dev.items())):
        for w in WINDOWS_TOKENS:
            prompts.append({
                "id": f"s3-{family}-w{w // 1000}k",
                "family": family,
                "needle": case["id"],
                "window_tokens": w,
                "depth": DEPTHS[i % len(DEPTHS)],
                "question": case["queries"]["task_specific"],
                "expects": _needles_from_gold(case["gold"]),
            })
    return {
        "version": 1,
        "registered": "analysis plan 2026-11-22, P4",
        "system": SYSTEM,
        "user_template": USER_TEMPLATE,
        "chars_per_token": CHARS_PER_TOKEN,
        "needles": needles,
        "prompts": prompts,
    }


def write_prompt_set(path: Path = PROMPT_SET_FILE) -> None:
    spec = build_prompt_set()
    path.write_text(json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                    encoding="utf-8")


def load_prompt_set(path: Path = PROMPT_SET_FILE) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if PROMPT_SET_HASH_FILE.exists():
        pinned = PROMPT_SET_HASH_FILE.read_text(encoding="utf-8").split()[0]
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != pinned:
            raise SystemExit(
                f"refusing: {path.name} no longer matches {PROMPT_SET_HASH_FILE.name} "
                "(the fixed prompt set is registered; a spec change needs a new pin)")
    return spec


# ---------------------------------------------------------------- context rendering

def render_context(prompt: dict, needles: dict, spec: dict) -> str:
    """The full context string for ``prompt``: filler tiled from the other needles with the
    needle case's text spliced at the registered depth. Deterministic per prompt id."""
    target = int(prompt["window_tokens"] * spec["chars_per_token"])
    needle = needles[prompt["needle"]]["text"]
    if len(needle) >= target:
        return needle[:target]
    fill_budget = target - len(needle)
    split_at = int(fill_budget * prompt["depth"])
    pool = [n["text"] for cid, n in needles.items() if cid != prompt["needle"]]
    rng = random.Random(int(hashlib.sha256(prompt["id"].encode()).hexdigest()[:8], 16))
    order = pool[:]
    rng.shuffle(order)
    buf, total, i = [], 0, 0
    while total < fill_budget:
        buf.append(order[i % len(order)])
        total += len(order[i % len(order)]) + 1
        i += 1
    filler = "\n".join(buf)
    return filler[:split_at] + needle + filler[split_at:split_at + fill_budget]


def messages(spec: dict, prompt: dict, context: str) -> list[dict]:
    return [
        {"role": "system", "content": spec["system"]},
        {"role": "user", "content": spec["user_template"].format(
            context=context, question=prompt["question"])},
    ]


# ---------------------------------------------------------------- arms

def apply_arm(arm: str, context: str, question: str) -> str:
    """The context the arm's host would actually hand the model.

    The candidate arms reuse the run.py profile call and the named acceptance policies
    (``DSH_POLICY``/``HERMES_POLICY`` — the hosts' own rules); a declined extract means
    the original context goes to the model, exactly as the host falls back."""
    if arm == "stock":
        return context
    policy = {"deepseek": DSH_POLICY, "hermes": HERMES_POLICY}[arm]
    try:
        res = _call(arm, context, question)
    except Exception:
        return context                          # a raise is a fail-open: the original stays
    if res is None or not decide(res, policy, original=context).accept:
        return context
    return res.compressed_text


# ---------------------------------------------------------------- endpoint

class EndpointError(Exception):
    pass


def _origin(base_url: str) -> str:
    """Strip a trailing /v1-style API path so native endpoints (Ollama /api/*) resolve."""
    base = base_url.rstrip("/")
    for suffix in ("/v1", "/openai/v1"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


class Endpoint:
    """An OpenAI-compatible chat endpoint: POST {base}/chat/completions.

    ``transport`` is injectable for tests: ``transport(method, url, payload, timeout) ->
    (status, body)``; the default is urllib."""

    def __init__(self, base_url: str, model: str, timeout: float = 300.0, transport=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._transport = transport or self._urllib
        self._identity: dict | None = None

    @staticmethod
    def _urllib(method: str, url: str, payload, timeout: float):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _request(self, method: str, url: str, payload=None):
        try:
            status, body = self._transport(method, url, payload, self.timeout)
        except urllib.error.HTTPError as e:
            raise EndpointError(f"{method} {url}: HTTP {e.code}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise EndpointError(f"{method} {url}: {e}") from e
        if status != 200:
            raise EndpointError(f"{method} {url}: HTTP {status}")
        return body

    def chat(self, msgs: list[dict]) -> str:
        body = self._request("POST", f"{self.base_url}/chat/completions",
                             {"model": self.model, "messages": msgs,
                              "temperature": 0.0, "stream": False})
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise EndpointError(
                f"{self.base_url}/chat/completions: unparseable reply {str(body)[:200]}") from e

    def identity(self) -> dict:
        """{served_model_id, model_digest} — best effort; both may be None.

        The served id comes from /v1/models; a true digest exists only on servers that
        expose one (Ollama's /api/tags). Neither is invented."""
        if self._identity is not None:
            return self._identity
        ident = {"served_model_id": None, "model_digest": None}
        try:
            body = self._request("GET", f"{self.base_url}/models")
            for m in body.get("data", []):
                if m.get("id") == self.model:
                    ident["served_model_id"] = m.get("id")
                    ident["model_digest"] = m.get("digest")
                    break
        except EndpointError:
            pass
        if ident["model_digest"] is None:  # Ollama exposes the real digest natively
            try:
                body = self._request("GET", f"{_origin(self.base_url)}/api/tags")
                for m in body.get("models", []):
                    if m.get("name") == self.model or m.get("model") == self.model:
                        ident["model_digest"] = m.get("digest")
                        if ident["served_model_id"] is None:
                            ident["served_model_id"] = m.get("name")
                        break
            except EndpointError:
                pass
        self._identity = ident
        return ident


# ---------------------------------------------------------------- scoring + runner

def _norm(s: str) -> str:
    return " ".join(s.casefold().split())


def score_answer(answer: str, expects: list[str]) -> tuple[int, float]:
    """Needle coverage: share of expected needles present in the answer."""
    if not expects:
        return 0, 1.0
    hay = _norm(answer)
    hit = sum(1 for e in expects if _norm(e) in hay)
    return hit, round(hit / len(expects), 6)


def run_s3(endpoint: Endpoint, spec: dict, arms: list[str], *,
           prompt_filter=None, quiet: bool = False) -> list[dict]:
    """One row per (arm, prompt); transport failures are recorded, never raised."""
    ident = endpoint.identity()
    rows = []
    prompts = [p for p in spec["prompts"] if prompt_filter is None or prompt_filter(p)]
    for prompt in prompts:
        context = render_context(prompt, spec["needles"], spec)
        for arm in arms:
            row = {
                "bench": "s3", "prompt_id": prompt["id"], "family": prompt["family"],
                "window_tokens": prompt["window_tokens"], "depth": prompt["depth"],
                "source_case": prompt["needle"], "arm": arm,
                "endpoint_url": endpoint.base_url, "model": endpoint.model,
                "served_model_id": ident["served_model_id"],
                "model_digest": ident["model_digest"],
                "question": prompt["question"], "expects": prompt["expects"],
            }
            t0 = time.perf_counter()
            try:
                rendered = apply_arm(arm, context, prompt["question"])
                answer = endpoint.chat(messages(spec, prompt, rendered))
                hit, score = score_answer(answer, prompt["expects"])
                row.update({"context_chars": len(rendered), "answer": answer,
                            "expect_hit": hit, "expect_total": len(prompt["expects"]),
                            "score": score, "error": None})
            except Exception as e:
                row.update({"context_chars": None, "answer": None, "expect_hit": None,
                            "expect_total": len(prompt["expects"]), "score": None,
                            "error": f"{type(e).__name__}: {e}"})
            row["wall_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            rows.append(row)
            if not quiet:
                tag = f'{row["score"]:.2f}' if row["score"] is not None else "ERR"
                print(f'  {row["prompt_id"]} {arm}: score={tag}', file=sys.stderr)
    return rows


def summarise(rows: list[dict]) -> dict:
    """Pooled mean score and worst family per arm — the S3 gate reads deltas off this."""
    out: dict[str, dict] = {}
    for row in rows:
        if row["score"] is None:
            continue
        arm = out.setdefault(row["arm"], {"n": 0, "sum": 0.0, "families": {}})
        arm["n"] += 1
        arm["sum"] += row["score"]
        fam = arm["families"].setdefault(row["family"], [0, 0.0])
        fam[0] += 1
        fam[1] += row["score"]
    return {
        arm: {
            "n": a["n"], "mean_score": round(a["sum"] / a["n"], 6) if a["n"] else None,
            "worst_family": min(((f, v[1] / v[0]) for f, v in a["families"].items()),
                                key=lambda kv: kv[1], default=(None, None))[0],
            "worst_family_score": round(min((v[1] / v[0] for v in a["families"].values()),
                                            default=0.0), 6) if a["families"] else None,
        }
        for arm, a in out.items()
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True, help="OpenAI-compatible base URL, e.g. http://127.0.0.1:1234/v1")
    ap.add_argument("--model", required=True, help="model name as the endpoint serves it")
    ap.add_argument("--arm", action="append", choices=ARMS, default=None,
                    help="repeatable; default: stock")
    ap.add_argument("--windows", help="comma list of window sizes to run (default: all registered)")
    ap.add_argument("--families", help="comma list of families to run (default: all)")
    ap.add_argument("--limit", type=int, help="run at most this many prompts (smoke runs)")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--out", type=Path, help="write rows to this jsonl file")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--write-prompt-set", action="store_true",
                    help="regenerate s3_prompts.json (a spec change; re-pin S3-PROMPTS.sha256)")
    args = ap.parse_args(argv)
    if args.write_prompt_set:
        write_prompt_set()
        print(f"wrote {PROMPT_SET_FILE.name}; re-pin {PROMPT_SET_HASH_FILE.name} to register it")
        return 0
    try:
        spec = load_prompt_set()
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot load {PROMPT_SET_FILE.name}: {e}", file=sys.stderr)
        return 2
    windows = {int(w) for w in args.windows.split(",")} if args.windows else None
    families = set(args.families.split(",")) if args.families else None
    seen = [0]

    def prompt_filter(p):
        if windows is not None and p["window_tokens"] not in windows:
            return False
        if families is not None and p["family"] not in families:
            return False
        seen[0] += 1
        return args.limit is None or seen[0] <= args.limit

    endpoint = Endpoint(args.base_url, args.model, timeout=args.timeout)
    rows = run_s3(endpoint, spec, args.arm or ["stock"], prompt_filter=prompt_filter,
                  quiet=args.quiet)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")) + "\n"
                                    for r in rows), encoding="utf-8", newline="\n")
    if not args.quiet:
        print(json.dumps(summarise(rows), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
