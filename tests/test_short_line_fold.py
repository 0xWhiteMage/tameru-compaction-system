from tameru.compress_context import preprocess_logs


def _lines(result):
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, str):
        return result.splitlines()
    return result


def _preprocess(lines, query=None):
    if query is None:
        return _lines(preprocess_logs(lines))
    try:
        return _lines(preprocess_logs(lines, query=query))
    except TypeError:
        return _lines(preprocess_logs(lines, query))


def test_short_frequent_lines_fold():
    lines = (
        ["TASK [Gathering Facts] ****"]
        + [f"ok: [web{i:02d}]" for i in range(30)]
        + ['fatal: [web13]: FAILED! => {"msg": "not writable"}']
    )
    out = _preprocess(lines)
    assert any(line.startswith("[×") and "ok: [web00]" in line for line in out)
    assert any(line.startswith("[last]") and "ok: [web29]" in line for line in out)
    assert any("fatal: [web13]" in line for line in out)
    assert len(out) < 8


def test_short_not_frequent_stay_unfolded():
    short = [f"ok: [a{i}]" for i in range(1, 5)]
    letters = "abcdefghij"
    long = [f"long distinct {i} {letters[i]}" for i in range(10)]
    out = _preprocess(short + long)
    for line in short:
        assert line in out


def test_short_without_letters_unchanged():
    lines = [f"--- {i}" for i in range(10)]
    out = _preprocess(lines)
    assert len(out) == len(lines)


def test_query_line_kept_verbatim():
    lines = [f"ok: [web{i:02d}]" for i in range(30)]
    out = _preprocess(lines, "web13")
    assert "ok: [web13]" in out


def test_config_lines_not_folded():
    lines = [f"config_{i} = {i * 111}" for i in range(20)]
    assert preprocess_logs(lines) == lines
