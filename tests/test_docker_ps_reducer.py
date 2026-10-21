from tameru.agent_formats import detect_test_runner, preprocess_test_output


def _header() -> str:
    return "CONTAINER ID   IMAGE              COMMAND                  CREATED        STATUS                     PORTS     NAMES"


def _rows(count: int) -> list[str]:
    return [
        f"a1b2c3d4e{i:03d}   acme/worker:1.{i}   \"python run.py\"          2 hours ago    Up 2 hours                           worker-{i}"
        for i in range(count)
    ]


def test_docker_ps_reducer_folds_running_rows():
    header = _header()
    rows = _rows(24)
    text = (
        "\n".join(
            [
                header,
                *rows,
                "f9e8d7c6b5a4   acme/api:2.4.1     \"gunicorn app:app\"       2 hours ago    Restarting (137) 5 seconds ago          api-1",
            ]
        )
        + "\n"
    )

    assert detect_test_runner(text) == "docker_ps"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert header in out
    assert "Restarting (137)" in out
    assert "api-1" in out
    assert "worker-7" not in out
    assert "running container rows omitted" in out
    assert len(out) < len(text) * 0.3


def test_docker_ps_reducer_keeps_unhealthy_and_exited_rows():
    header = _header()
    rows = _rows(10)
    text2 = (
        "\n".join(
            [
                header,
                *rows,
                "b0b0b0b0b0b0   acme/db:16         \"postgres\"               3 hours ago    Up 3 hours (unhealthy)               db-1",
                "c0c0c0c0c0c0   acme/job:1         \"run\"                    3 hours ago    Exited (1) 2 hours ago               job-1",
            ]
        )
        + "\n"
    )

    out2 = preprocess_test_output(text2, "")
    assert out2 is not None
    assert "(unhealthy)" in out2
    assert "Exited (1)" in out2


def test_docker_ps_not_detected_for_short_listing():
    header = _header()
    rows = _rows(1)
    assert detect_test_runner(header + "\n" + rows[0] + "\n") is None
