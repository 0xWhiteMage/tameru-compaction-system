"""Deterministic generator of host-neutral multi-step agent sessions (see SCHEMA.md).

Two passes per scenario:
  * ``plan(family, index, pool)``: step kinds and sizes, window boundaries, fact placement, keys and values, task and
    questions.  It needs no output text, so it runs without the Squeez file (real sizes come from manifest.json).
  * ``step_text(plan, i, real)``: the output text of step i and its facts' line indices.  Synthetic steps draw only
    from ``rng(f"{id}:step:{i}")``, so a step's text never depends on the window or on any other step.

Randomness comes only from ``random.Random`` seeded with sha256 of a tag (no clock, no PYTHONHASHSEED, no env).
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field

from .families import FAMILY_BY_ID, KG, VG, Family, render

GENERATOR_VERSION = "session-corpus-2"  # 2: size-matched real outputs <= 40K (equivalence attempt 1 failed on size bins)
SCENARIOS_PER_FAMILY = 11
CHARS_PER_TOKEN = 4
WINDOWS = (128_000, 200_000, 252_000, 500_000, 1_000_000)
SEGMENT_WINDOWS = (128_000, 252_000, 500_000, 1_000_000)  # facts are placed so each of these windows holds its own
LENGTH_FACTOR = (1.6, 2.1)          # unpruned total >= factor x planning trigger, factor uniform in this range
REAL_SHARE_TARGET = 0.34            # greedy interleave: a real step is next whenever real chars < this share
REAL_MAX_CHARS = 40000              # largest real output used: the dev/validation repository pool has none in 40K-60K, so no pool uses them
REUSE_PENALTY = 0.25                # log-size units added per earlier use of the same real output in a session
STEP_MIN, STEP_MAX, STEP_SIGMA = 2000, 60000, 0.8
LANG_CYCLE = ("en", "zh", "en", "mixed", "zh", "en", "en", "zh", "mixed", "en")


def ds_trigger(window: int) -> int:
    """DeepSeek Harness stock trigger in tokens: floor(min(0.8W, W - 8000 - 65536))."""
    return int(math.floor(min(0.8 * window, window - 8000 - 65536)))


def hermes_trigger(window: int) -> int:
    """Hermes stock trigger in tokens (planning value): 0.75W."""
    return int(0.75 * window)


def plan_trigger(window: int) -> int:
    return max(ds_trigger(window), hermes_trigger(window))


def rng(tag: str) -> random.Random:
    return random.Random(int(hashlib.sha256(tag.encode("utf-8")).hexdigest()[:16], 16))


def scenario_ids(family_id: str) -> list[str]:
    return [f"{family_id}-{i:02d}" for i in range(SCENARIOS_PER_FAMILY)]


@dataclass
class FactPlan:
    id: str
    step: int
    kind: str            # natural | error | buried | stale | real
    key: str
    value: str
    shape: int = -1      # index into family.shapes (natural/error); -1 for buried/stale/real
    real_index: int = -1  # which gold fact of the real output


@dataclass
class Plan:
    id: str
    family: Family
    index: int
    seed: int
    language: str
    style: str
    factor: float
    pool: str
    kinds: list = field(default_factory=list)    # "synthetic" | "real"
    chars: list = field(default_factory=list)    # planned chars (synthetic: target; real: exact)
    real_ids: list = field(default_factory=list)  # manifest id per step or None
    windows: dict = field(default_factory=dict)  # window -> steps
    facts: list = field(default_factory=list)
    buried_steps: set = field(default_factory=set)
    absent_key: str = ""
    absent_shape: int = 0

    def steps_for_window(self, window: int) -> int:
        need = self.factor * CHARS_PER_TOKEN * plan_trigger(window)
        total = 0
        for i, c in enumerate(self.chars):
            total += c
            if total >= need:
                return i + 1
        raise ValueError(f"{self.id} is too short for window {window}")


def _lang(family: Family, index: int) -> str:
    off = int(hashlib.sha256(f"lang:{family.id}".encode()).hexdigest()[:4], 16) % len(LANG_CYCLE)
    return LANG_CYCLE[(index + off) % len(LANG_CYCLE)]


def _style(family: Family, index: int) -> str:
    off = int(hashlib.sha256(f"style:{family.id}".encode()).hexdigest()[:4], 16) % 2
    return "specific" if (index + off) % 2 == 0 else "vague"


def _synthetic_size(r: random.Random, median: int) -> int:
    return int(min(STEP_MAX, max(STEP_MIN, r.lognormvariate(math.log(median), STEP_SIGMA))))


def plan(family_id: str, index: int, pool: list[dict], pool_name: str) -> Plan:
    fam = FAMILY_BY_ID[family_id]
    sid = f"{family_id}-{index:02d}"
    seed = int(hashlib.sha256(f"session-corpus:{sid}".encode()).hexdigest()[:12], 16)
    r = rng(f"{sid}:plan")
    p = Plan(sid, fam, index, seed, _lang(fam, index), _style(fam, index), round(LENGTH_FACTOR[0] + (LENGTH_FACTOR[1] - LENGTH_FACTOR[0]) * r.random(), 4), pool_name)
    # real outputs are size-matched: a target size is drawn from the family's step-size distribution and the closest pool
    # output is taken (log-size distance + REUSE_PENALTY per earlier use in this session; ties by a per-scenario hash
    # order), so real steps have the same size distribution whichever repository pool a split draws from
    order = sorted((o for o in pool if o["chars"] <= REAL_MAX_CHARS), key=lambda o: hashlib.sha256(f"{sid}:real:{o['id']}".encode()).hexdigest())
    logc = {o["id"]: math.log(o["chars"]) for o in order}
    uses: dict[str, int] = {}
    need = p.factor * CHARS_PER_TOKEN * plan_trigger(max(WINDOWS))
    total = real_total = 0
    while total < need:
        i = len(p.chars)
        if i >= 1 and order and real_total < REAL_SHARE_TARGET * total:
            t = math.log(min(REAL_MAX_CHARS, _synthetic_size(rng(f"{sid}:rsize:{i}"), fam.median_chars)))
            o = min(order, key=lambda o: abs(logc[o["id"]] - t) + REUSE_PENALTY * uses.get(o["id"], 0))
            uses[o["id"]] = uses.get(o["id"], 0) + 1
            p.kinds.append("real"), p.chars.append(o["chars"]), p.real_ids.append(o["id"])
            real_total += o["chars"]
        else:
            c = _synthetic_size(rng(f"{sid}:size:{i}"), fam.median_chars)
            p.kinds.append("synthetic"), p.chars.append(c), p.real_ids.append(None)
        total += p.chars[-1]
    p.windows = {w: p.steps_for_window(w) for w in WINDOWS}
    _place_facts(p, r, {o["id"]: o for o in pool})
    return p


def _place_facts(p: Plan, r: random.Random, pool_by_id: dict) -> None:
    fam = p.family
    used_keys: set[str] = set()

    def new_key(kind: str) -> str:
        for _ in range(200):
            k = KG[kind](r)
            if k not in used_keys:
                used_keys.add(k)
                return k
        raise RuntimeError("key space exhausted")

    error_shapes = [i for i, s in enumerate(fam.shapes) if s.kind == "error"]
    natural_shapes = [i for i, s in enumerate(fam.shapes) if s.kind == "natural"] or error_shapes
    error_shapes = error_shapes or natural_shapes
    bounds = [0] + [p.windows[w] for w in SEGMENT_WINDOWS]
    n = 0
    for seg in range(len(SEGMENT_WINDOWS)):
        lo, hi = bounds[seg], bounds[seg + 1]
        synth = [i for i in range(lo, hi) if p.kinds[i] == "synthetic"]
        if len(synth) < 3:
            raise RuntimeError(f"{p.id}: segment {seg} has too few synthetic steps")
        # S5 buried assignment: a dedicated step (one repetitive filler template), never shared with another fact
        b_step = synth[int(r.random() * len(synth))]
        others = [i for i in synth if i != b_step]
        for shapes in (natural_shapes, error_shapes):
            sh = shapes[int(r.random() * len(shapes))]
            shape = fam.shapes[sh]
            p.facts.append(FactPlan(f"f{n:02d}", others[int(r.random() * len(others))], shape.kind, new_key(shape.key), VG[shape.value](r), sh))
            n += 1
        key = new_key("cfgkey")
        p.facts.append(FactPlan(f"f{n:02d}", b_step, "buried", key, VG["cfgval"](r)))
        p.buried_steps.add(b_step)
        n += 1
        earlier = [i for i in range(0, b_step) if p.kinds[i] == "synthetic" and i not in p.buried_steps]
        if earlier and r.random() < 0.5:   # a superseded value of the same key, earlier in the session
            stale = VG["cfgval"](r)
            p.facts.append(FactPlan(f"f{n:02d}", earlier[int(r.random() * len(earlier))], "stale", key, stale))
            n += 1
    # real gold facts: every real step's gold spans (ids are step-scoped so repeats of one output stay distinct)
    for i, oid in enumerate(p.real_ids):
        if oid is not None:
            for j in range(pool_by_id[oid]["gold_facts"]):
                p.facts.append(FactPlan(f"r{i:03d}.{j}", i, "real", "", "", real_index=j))
    sh = natural_shapes[int(r.random() * len(natural_shapes))]
    p.absent_key, p.absent_shape = new_key(fam.shapes[sh].key), sh


# ------------------------------------------------------------------------------------------------ text
def _lines_for(fam: Family, lang: str) -> tuple:
    if lang == "zh":
        return fam.fill_zh + fam.fill_en[:1]
    return fam.fill_en


def _render_fact(fam: Family, lang: str, f: FactPlan, r: random.Random) -> tuple[list[str], int]:
    """Physical lines of a fact block and the index of the line that holds key and value."""
    zh = lang == "zh"
    if f.kind in ("buried", "stale"):
        tpls = (fam.buried_zh if zh else fam.buried_en,)
    else:
        shape = fam.shapes[f.shape]
        tpls = shape.zh if zh else shape.en
    lines: list[str] = []
    for t in tpls:
        lines.extend(render(fam.tpl(t), r, {"key": f.key, "value": f.value}).split("\n"))
    for j, ln in enumerate(lines):
        if f.key in ln and f.value in ln:
            return lines, j
    raise AssertionError(f"fact line without key and value: {fam.id} {f}")


def step_call(p: Plan, i: int, real=None) -> tuple[str, dict]:
    oid = p.real_ids[i]
    if oid is not None:
        cmd = real.command(oid) if real is not None else ""
        tool_type = real.rows[oid]["tool_type"] if real is not None else ""
        return ("read_file", {"path": cmd}) if tool_type == "read_file" else ("bash", {"command": cmd})
    r = rng(f"{p.id}:args:{i}")
    return p.family.tool, {k: render(p.family.tpl(v), r) for k, v in p.family.args.items()}


def step_text(p: Plan, i: int, real=None) -> tuple[str, list[dict]]:
    """-> (output_text, facts as dicts with line_index).  Real steps need ``real`` (a RealTexts)."""
    oid = p.real_ids[i]
    if oid is not None:
        if real is None:
            raise ValueError("real steps need the Squeez file (RealTexts)")
        text = real.text(oid)
        gold = real.facts(oid)
        facts = [{"id": f.id, "kind": "real", "key": real.query(oid), "value": gold[f.real_index][1],
                  "line_index": gold[f.real_index][0]} for f in p.facts if f.step == i and f.kind == "real"]
        return text, facts
    fam = p.family
    r = rng(f"{p.id}:step:{i}")
    pool = _lines_for(fam, p.language)
    if i in p.buried_steps:
        tpls = [pool[0]]
    else:
        k = 1 + int(r.random() * min(3, len(pool)))
        tpls = r.sample(list(pool), k)
    tpls = [fam.tpl(t) for t in tpls]
    blocks = []
    budget = p.chars[i]
    here = [f for f in p.facts if f.step == i and f.kind != "real"]
    for f in here:
        lines, j = _render_fact(fam, p.language, f, r)
        blocks.append((f, lines, j))
        budget -= sum(len(x) + 1 for x in lines)
    body: list[str] = []
    size = 0
    nt = len(tpls)
    while size < budget:
        t = tpls[0] if nt == 1 else tpls[int(r.random() * nt)]
        for ln in render(t, r).split("\n"):
            body.append(ln)
            size += len(ln) + 1
    # insert each block at a random line boundary; record the fact line's final index
    positions = sorted((int(r.random() * (len(body) + 1)), bi) for bi in range(len(blocks)))
    out: list[str] = []
    facts = []
    prev = 0
    for pos, bi in positions:
        out.extend(body[prev:pos])
        prev = pos
        f, lines, j = blocks[bi]
        facts.append({"id": f.id, "kind": f.kind, "key": f.key, "value": f.value, "line_index": len(out) + j})
        out.extend(lines)
    out.extend(body[prev:])
    facts.sort(key=lambda d: d["id"])
    return "\n".join(out), facts


# ------------------------------------------------------------------------------------------------ task and questions
def _zh(lang: str) -> bool:
    return lang in ("zh", "mixed")


def task_text(p: Plan) -> str:
    fam = p.family
    zh = _zh(p.language)
    if p.style == "vague":
        return fam.vague_zh if zh else fam.vague_en
    keys = []
    for f in p.facts:
        if f.kind in ("natural", "error", "buried") and f.key not in keys:
            keys.append(f.key)
    sep = "、" if zh else ", "
    t = fam.task_zh if zh else fam.task_en
    return t.replace("{family}", fam.id).replace("{keys}", sep.join(keys))


def _question(fam: Family, f: FactPlan, zh: bool) -> str:
    if f.kind == "buried":
        return ("{key} 最终的取值是多少？" if zh else "What value does {key} end up with?").replace("{key}", f.key)
    shape = fam.shapes[f.shape]
    return (shape.q_zh if zh else shape.q_en).replace("{key}", f.key)


def questions(p: Plan, real=None) -> list[dict]:
    """Questions with the facts that answer them.  ``first_window``: the smallest window whose step slice holds every
    fact of the question (``absent`` questions: 128K).  Real-fact questions need ``real`` for their text."""
    fam = p.family
    zh = _zh(p.language)
    stale_keys = {f.key for f in p.facts if f.kind == "stale"}

    def first_window(steps: list[int]) -> int:
        last = max(steps) if steps else 0
        return next(w for w in WINDOWS if last < p.windows[w])

    out = []
    seg_facts: dict[int, list[FactPlan]] = {}
    bounds = [p.windows[w] for w in SEGMENT_WINDOWS]
    for f in p.facts:
        if f.kind in ("natural", "error", "buried"):
            seg = next(s for s, b in enumerate(bounds) if f.step < b)
            seg_facts.setdefault(seg, []).append(f)
            stratum = "superseded" if f.kind == "buried" and f.key in stale_keys else "buried" if f.kind == "buried" else "single"
            out.append({"id": f"q-{f.id}", "text": _question(fam, f, zh), "fact_ids": [f.id], "stratum": stratum,
                        "fact_kind": f.kind, "first_window": first_window([f.step])})
    for seg, fs in sorted(seg_facts.items()):
        pair = [f for f in fs if f.kind in ("natural", "error")][:2]
        if len(pair) == 2:
            a, b = (_question(fam, f, zh) for f in pair)
            text = (f"请同时回答：{a} {b}" if zh else f"Answer both: {a} {b}")
            out.append({"id": f"q-agg{seg}", "text": text, "fact_ids": [f.id for f in pair], "stratum": "aggregate",
                        "fact_kind": "pair", "first_window": first_window([f.step for f in pair])})
    shape = fam.shapes[p.absent_shape]
    out.append({"id": "q-absent", "text": (shape.q_zh if zh else shape.q_en).replace("{key}", p.absent_key), "fact_ids": [],
                "stratum": "absent", "fact_kind": "none", "first_window": WINDOWS[0], "expected": "not present"})
    # one real-fact question per segment: the first real step in the segment that has a gold fact
    lo = 0
    for seg, hi in enumerate(bounds):
        cand = [f for f in p.facts if f.kind == "real" and f.real_index == 0 and lo <= f.step < hi]
        if cand:
            f = min(cand, key=lambda x: x.step)
            q = real.query(p.real_ids[f.step]) if real is not None else None
            out.append({"id": f"q-{f.id}", "text": q, "fact_ids": [f.id], "stratum": "real", "fact_kind": "real",
                        "first_window": first_window([f.step])})
        lo = hi
    return out
