from tameru import compress_context as cc


def test_bare_ratio_fact_lines_are_not_progress():
    assert not cc._is_progress_bar(
        "2026-10-18 09:21:00 INFO health: summary 20/40 degraded"
    )
    assert not cc._is_progress_bar("3/5 pods ready")
    assert not cc._is_progress_bar("replicas 2/3 unavailable")


def test_progress_lines_are_progress():
    assert cc._is_progress_bar("Downloading foo 12/100")
    assert cc._is_progress_bar("Receiving objects: 45% (9/20)")
    assert cc._is_progress_bar("[=====>   ] 50%")
    assert cc._is_progress_bar("  12/100  ")
    assert cc._is_progress_bar("Step 3/7 : RUN make")


def test_preprocess_logs_keeps_summary_after_alternating_lines():
    lines = [
        f"svc-{i} state={'degraded' if i % 2 else 'healthy'}"
        for i in range(40)
    ]
    summary = "2026-10-18 09:21:00 INFO health: summary 20/40 degraded"
    lines.append(summary)
    out = cc.preprocess_logs(lines, "")
    assert summary in out
