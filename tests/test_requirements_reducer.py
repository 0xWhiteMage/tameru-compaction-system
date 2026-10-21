from tameru.agent_formats import detect_test_runner, preprocess_test_output

TEXT = (
    "\n".join(f"pkg{i}=={i % 9 + 1}.{i}.0" for i in range(40))
    + "\nurllib3==1.26.5\nrequests==2.32.3\n"
)


def test_detect_requirements():
    assert detect_test_runner(TEXT) == "requirements"


def test_preprocess_requirements_with_query():
    out = preprocess_test_output(TEXT, "which urllib3 version is installed")
    assert out is not None
    assert "urllib3==1.26.5" in out
    assert "pkg7==" not in out
    assert "requirement lines omitted" in out
    assert len(out) < len(TEXT) * 0.3


def test_preprocess_requirements_without_query():
    assert preprocess_test_output(TEXT, "") is None
    assert preprocess_test_output(TEXT, "which numpy version is installed") is None


def test_short_list_not_detected():
    assert detect_test_runner("a==1.0\nb==2.0\n") is None
