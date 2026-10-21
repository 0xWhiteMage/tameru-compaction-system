from tameru.agent_formats import _shorten_pytest_banner, preprocess_test_output


def test_shorten_pytest_banner():
    assert (
        _shorten_pytest_banner("=" * 35 + " FAILURES " + "=" * 35)
        == "=== FAILURES ==="
    )
    assert (
        _shorten_pytest_banner("_" * 27 + " test_x " + "_" * 28)
        == "___ test_x ___"
    )
    assert (
        _shorten_pytest_banner("=" * 10 + " 1 failed, 670 passed in 12.31s " + "=" * 10)
        == "=== 1 failed, 670 passed in 12.31s ==="
    )
    assert _shorten_pytest_banner("a == b") == "a == b"
    assert _shorten_pytest_banner("E       assert 42 == 41") == "E       assert 42 == 41"


def test_preprocess_test_output_shortens_pytest_banners():
    text = (
        "tests/test_api.py "
        + "." * 400
        + " [ 60%]\n"
        "tests/test_db.py "
        + "." * 250
        + "F"
        + "." * 20
        + " [100%]\n\n"
        + "=" * 35
        + " FAILURES "
        + "=" * 35
        + "\n"
        + "_" * 27
        + " test_migration_rollback "
        + "_" * 28
        + "\n\n"
        "    def test_migration_rollback(db):\n"
        ">       assert db.version == 41\n"
        "E       assert 42 == 41\n\n"
        "tests/test_db.py:77: AssertionError\n"
        + "=" * 27
        + " short test summary info "
        + "=" * 28
        + "\n"
        "FAILED tests/test_db.py::test_migration_rollback - assert 42 == 41\n"
        "1 failed, 670 passed in 12.31s\n"
    )

    out = preprocess_test_output(text, "")

    assert out is not None
    assert "test_migration_rollback" in out
    assert "assert 42 == 41" in out
    assert "tests/test_db.py:77" in out
    assert "1 failed, 670 passed" in out
    assert not any("=" * 10 in line for line in out.splitlines())
def test_shorten_pytest_banner_preserves_error_fingerprint():
    assert _shorten_pytest_banner("_" * 21 + " ERROR at setup of test_token_refresh " + "_" * 21) == "_" * 21 + " ERROR at setup of test_token_refresh " + "_" * 21
    assert _shorten_pytest_banner("=" * 30 + " ERRORS " + "=" * 30) == "=== ERRORS ==="
