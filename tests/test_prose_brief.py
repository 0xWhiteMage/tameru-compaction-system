from tameru.compress_context import compress_context

def _doc(filler, key, tail):
    return "\n\n".join(filler) + "\n\n" + key + "\n\n" + "\n\n".join(tail)

def test_prose_brief_cjk_keeps_unique_fact_and_drops_repeats():
    text = _doc(["本季度销售情况总体平稳,各区域按计划推进,没有需要特别说明的事项。" for _ in range(30)],
                "重要:华东区合同 HT-2291 因客户破产被取消,损失约 120 万元。",
                ["其他事项均为例行汇报。" for _ in range(8)])
    r = compress_context(text, [], ccr=False, citations=False, prose_brief=True)
    assert "HT-2291" in r.compressed_text and "120 万元" in r.compressed_text
    assert not r.fail_open and len(r.compressed_text) < 0.4 * len(text)
    assert r.receipt["query_source"] == "prose-brief" and r.compression_risk in ("medium", "high")

def test_prose_brief_keeps_data_bearing_repeats():
    rows = [f"In quarter {q} the revenue was {v} million dollars, as reported." for q, v in zip(range(1, 13), [1.5 + i for i in range(12)])]
    text = _doc(["The team met and reviewed routine items without any decisions." for _ in range(12)], "Summary follows.", rows)
    r = compress_context(text, [], ccr=False, citations=False, prose_brief=True)
    for row in rows:
        assert row in r.compressed_text

def test_prose_brief_off_by_default_fails_open():
    text = _doc(["Routine paragraph about nothing in particular, repeated." for _ in range(30)], "Key: contract K-5521 cancelled.", ["Done." for _ in range(5)])
    r = compress_context(text, [], ccr=False, citations=False)
    assert r.fail_open and r.compressed_text == text

def test_prose_brief_ignores_non_empty_query():
    text = _doc(["Routine paragraph about nothing in particular, repeated." for _ in range(30)], "Key: contract K-5521 cancelled.", ["Done." for _ in range(5)])
    r = compress_context(text, ["which contract was cancelled"], ccr=False, citations=False, prose_brief=True)
    assert r.receipt["query_source"] == "caller" and "K-5521" in r.compressed_text
