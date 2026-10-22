from tameru.agent_formats import detect_test_runner, _classify_rollout_wait
from tameru.compress_context import compress_context


def test_detect_and_compress_rollout_wait():
    text = "".join(
        f'Waiting for deployment "api" rollout to finish: {i} of 10 updated replicas are available...\n'
        for i in range(25)
    ) + 'error: deployment "api" exceeded its progress deadline\n'

    assert detect_test_runner(text) == "rollout_wait"

    for query in ("", "did the rollout succeed"):
        out = compress_context(text, query).compressed_text
        assert "exceeded its progress deadline" in out
        assert "0 of 10 updated" in out
        assert "24 of 10 updated" in out
        assert len(out) < 0.4 * len(text)


def test_classify_keeps_first_last_two_and_outcome():
    text = "".join(
        f'Waiting for deployment "api" rollout to finish: {i} of 10 updated replicas are available...\n'
        for i in range(25)
    ) + 'error: deployment "api" exceeded its progress deadline\n'

    lines = text.splitlines()
    keep, _, _ = _classify_rollout_wait(lines)

    assert sum(keep) == 4
    assert keep[0] is True
    assert keep[23] is True
    assert keep[24] is True
    assert keep[25] is True
    assert all(not flag for index, flag in enumerate(keep) if index not in (0, 23, 24, 25))


def test_success_line_kept():
    text = "".join(
        f'Waiting for deployment "api" rollout to finish: {i} of 10 updated replicas are available...\n'
        for i in range(8)
    ) + 'deployment "api" successfully rolled out\n'

    assert detect_test_runner(text) == "rollout_wait"

    lines = text.splitlines()
    keep, _, _ = _classify_rollout_wait(lines)

    assert keep[-1] is True
    assert sum(keep) == 4


def test_daemon_set_variant_detected():
    text = "".join(
        f'Waiting for daemon set "node-agent" rollout to finish: {i} out of 5 new pods have been updated...\n'
        for i in range(8)
    )

    assert detect_test_runner(text) == "rollout_wait"


def test_five_waiting_lines_not_detected():
    text = "".join(
        f'Waiting for deployment "api" rollout to finish: {i} of 10 updated replicas are available...\n'
        for i in range(5)
    )

    assert detect_test_runner(text) != "rollout_wait"
