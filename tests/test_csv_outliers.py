from tameru.format_adapters import adapt_format
from tameru.compress_context import compress_context


def test_csv_outliers_keeps_outlier_and_compresses():
    rows = ["account,plan,mrr_usd,overdue_days"]
    rows.extend(f"acct-{i},team,{100 + i},0" for i in range(45))
    rows.append("acct-9081,enterprise,12500,94")
    text = "\n".join(rows)

    result = adapt_format(text, "")
    assert result.applied
    assert result.text.startswith("account,plan,mrr_usd,overdue_days")
    assert "acct-9081" in result.text
    assert "12500" in result.text
    assert "acct-7," not in result.text
    assert "rows omitted" in result.text

    compressed = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    compressed_text = compressed.compressed_text
    assert "acct-9081" in compressed_text
    assert "12500" in compressed_text
    assert len(compressed_text) < len(text) / 2


def test_tsv_outliers_with_weak_query():
    rows = ["job\tqueue\tduration_s\tstatus"]
    rows.extend(f"job-{i}\tdefault\t{5 + i % 9}\tdone" for i in range(40))
    rows.append("job-777\tdefault\t3600\ttimeout")
    text = "\n".join(rows)

    result = adapt_format(text, "which job timed out")
    assert result.applied
    assert "job-777" in result.text


def test_unrelated_query_declines():
    rows = ["account,plan,mrr_usd,overdue_days"]
    rows.extend(f"acct-{i},team,{100 + i},0" for i in range(45))
    rows.append("acct-9081,enterprise,12500,94")
    text = "\n".join(rows)

    result = adapt_format(text, "what is the weather in paris?")
    assert not result.applied


def test_uniform_csv_declines():
    rows = ["id,label"]
    rows.extend(f"v{i},same" for i in range(20))
    text = "\n".join(rows)

    result = adapt_format(text, "")
    assert not result.applied


def test_too_many_outliers_declines():
    rows = ["id,status,value"]
    rows.extend(f"ok-{i},ok,1" for i in range(20))
    rows.extend(f"bad-{i},failed,100" for i in range(10))
    text = "\n".join(rows)

    result = adapt_format(text, "")
    assert not result.applied


def test_distinctive_query_uses_old_path():
    rows = ["account,plan,mrr_usd,overdue_days"]
    rows.extend(f"acct-{i},team,{100 + i},0" for i in range(25))
    text = "\n".join(rows)

    result = adapt_format(text, "acct-12")
    assert result.applied
    assert result.reason == "header plus exact matching records"
    assert "acct-12," in result.text
    assert "acct-13," not in result.text
