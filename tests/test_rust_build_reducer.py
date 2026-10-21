from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_rust_build_reducer():
    text = "".join(
        f"warning: unused variable: `tmp{i}`\n  --> src/lib.rs:{10 + i}:9\n   |\n   = note: `#[warn(unused_variables)]` on by default\n\n"
        for i in range(12)
    ) + (
        "error[E0382]: borrow of moved value: `cfg`\n"
        "  --> src/main.rs:41:20\n"
        "   |\n"
        '41 |     println!("{:?}", cfg);\n'
        "   |                    ^^^ value borrowed here after move\n"
        "\n"
        'error: could not compile `svc` (bin "svc") due to 1 previous error; 12 warnings emitted\n'
    )

    assert detect_test_runner(text) == "rust_build"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "error[E0382]: borrow of moved value: `cfg`" in out
    assert "src/main.rs:41:20" in out
    assert "value borrowed here after move" in out
    assert "could not compile `svc`" in out
    assert "tmp3" not in out
    assert "rustc warning lines omitted" in out
    assert len(out) < len(text) * 0.5

    text2 = "".join(
        f"warning: unused import: `std::fmt{i}`\n --> src/a.rs:{i + 1}:5\n  |\n\n"
        for i in range(5)
    ) + (
        "warning: `svc` (lib) generated 5 warnings\n"
        "error: could not compile `svc` due to previous error\n"
    )
    out2 = preprocess_test_output(text2, "")
    assert out2 is not None
    assert "generated 5 warnings" in out2
    assert "could not compile" in out2

    assert detect_test_runner("warning: disk almost full\nall good\n") is None
