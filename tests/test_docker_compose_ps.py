from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def _compressed(text: str, query: str) -> str:
    return compress_context(text, query, ccr=False, citations=False).compressed_text


def test_docker_compose_ps_is_detected_and_compressed():
    text = (
        "NAME                IMAGE                 COMMAND                  SERVICE    CREATED        STATUS                     PORTS\n"
        + "".join(
            f"app-worker-{i}        example/worker:2.3    \"python worker.py\"       worker     2 hours ago    Up 2 hours                 \n"
            for i in range(1, 25)
        )
        + "app-db-1            postgres:16           \"docker-entrypoint.s…\"   db         2 hours ago    Restarting (1) 8 seconds ago   \n"
        + "app-web-1           example/web:2.3       \"gunicorn app:app\"       web        2 hours ago    Up 2 hours (unhealthy)     0.0.0.0:8000->8000/tcp\n"
    )

    assert detect_test_runner(text) == "docker_ps"

    for query in ("", "why is the database container down"):
        out = _compressed(text, query)
        assert "SERVICE" in out
        assert "app-db-1" in out
        assert "Restarting (1) 8 seconds ago" in out
        assert "(unhealthy)" in out
        assert len(out) < 0.4 * len(text)


def test_classic_docker_ps_header_is_still_detected():
    text = (
        "CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES\n"
        + "".join(
            f"abc{i:024}   example/worker:2.3   \"python worker.py\"   2 hours ago   Up 2 hours   0.0.0.0:{8000 + i}->8000/tcp   app-worker-{i}\n"
            for i in range(1, 11)
        )
    )

    assert detect_test_runner(text) == "docker_ps"


def test_unrelated_name_status_restarts_table_is_not_docker_ps():
    text = (
        "NAME   STATUS   RESTARTS\n"
        "app-db-1   Restarting (1) 8 seconds ago   1\n"
    )

    assert detect_test_runner(text) != "docker_ps"
