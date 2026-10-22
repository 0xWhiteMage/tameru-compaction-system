from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


def test_cmake_reducer() -> None:
    probes = "".join(f"-- Looking for header_{i}.h - found\n" for i in range(30))
    text = (
        "-- The C compiler identification is GNU 13.2.0\n"
        "-- The CXX compiler identification is GNU 13.2.0\n"
        "-- Detecting C compiler ABI info - done\n"
        + probes
        + "-- Looking for pthread_create in pthreads - not found\n"
        "-- Found Threads: TRUE\n"
        "CMake Error at CMakeLists.txt:42 (find_package):\n"
        "  Could not find a package configuration file provided by \"Protobuf\"\n"
        "-- Configuring incomplete, errors occurred!\n"
    )

    assert detect_test_runner(text) == "cmake"

    out = preprocess_test_output(text, "")
    assert "CMakeLists.txt:42" in out
    assert "Protobuf" in out
    assert "Configuring incomplete" in out
    assert "pthreads - not found" in out
    assert "GNU 13.2.0" in out
    assert "header_17.h" not in out
    assert "configure check lines omitted" in out
    assert len(out) < 0.4 * len(text)

    r = compress_context(text, "", ccr=False, citations=False)
    assert "CMakeLists.txt:42" in r.compressed_text
    assert len(r.compressed_text) < 0.5 * len(text)

    assert detect_test_runner(probes) is None
