from tameru.agent_formats import _detect_env_dump, detect_test_runner


def test_detect_env_dump_fast_25_line_dump():
    text = "\n".join(f"APP_WORKER_{i}_ENABLED=true" for i in range(25))
    assert detect_test_runner(text) == "env_dump"


def test_detect_env_dump_fast_prose_with_one_env_line():
    lines = ["lorem ipsum dolor sit amet"] * 2999
    lines.append("a=b")
    text = "\n".join(lines)
    assert _detect_env_dump(text) is False


def test_detect_env_dump_fast_exact_ninety_percent():
    env_lines = [f"APP_WORKER_{i}_ENABLED=true" for i in range(5)]
    env_lines += [f"OTHER_ENV_{i}=true" for i in range(13)]
    non_env_lines = ["=== separator ===", "=== separator ==="]
    text = "\n".join(env_lines + non_env_lines)
    assert _detect_env_dump(text) is True
    assert detect_test_runner(text) == "env_dump"

    env_lines = [f"APP_WORKER_{i}_ENABLED=true" for i in range(5)]
    env_lines += [f"OTHER_ENV_{i}=true" for i in range(12)]
    non_env_lines = ["=== separator ===", "=== separator ===", "=== separator ==="]
    text = "\n".join(env_lines + non_env_lines)
    assert _detect_env_dump(text) is False
    assert detect_test_runner(text) != "env_dump"
