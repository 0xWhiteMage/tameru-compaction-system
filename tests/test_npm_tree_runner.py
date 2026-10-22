from tameru.agent_formats import detect_test_runner, _classify_npm_tree
from tameru.compress_context import compress_context


def test_npm_tree_detect_and_compress():
    text = (
        "app@1.0.0 /srv/app\n"
        + "".join(f"├── pkg-{i}@1.{i}.0\n" for i in range(40))
        + "├── UNMET PEER DEPENDENCY react@18.2.0\n"
        + "└─┬ legacy-widget@0.3.1\n"
        + '  └── lodash@3.10.1 invalid: "^4.17.0" from legacy-widget\n'
        + "\n"
        + "npm ERR! code ELSPROBLEMS\n"
    )

    assert detect_test_runner(text) == "npm_tree"

    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text
    assert "UNMET PEER DEPENDENCY react@18.2.0" in compressed
    assert "lodash@3.10.1 invalid" in compressed
    assert "legacy-widget@0.3.1" in compressed
    assert "app@1.0.0" in compressed
    assert "npm ERR! code ELSPROBLEMS" in compressed
    assert len(compressed) < len(text) / 2


def test_npm_tree_nested_ancestors():
    lines = [
        "app@1.0.0 /srv/app",
        "├── a@1.0.0",
        "├─┬ b@1.0.0",
        "│ ├── c@1.0.0",
        "│ └─┬ d@1.0.0",
        "│   └── e@1.0.0 extraneous",
        "└── f@1.0.0",
    ]

    keep = _classify_npm_tree(lines)[0]
    assert keep == [True, True, True, False, True, True, False]


def test_npm_tree_ascii_detect():
    text = (
        "app@1.0.0 C:\\app\n"
        + "".join(f"+-- pkg-{i}@1.0.0\n" for i in range(12))
        + "`-- missing-dep@2.0.0 missing\n"
    )

    assert detect_test_runner(text) == "npm_tree"


def test_npm_tree_negatives():
    plain_log = "\n".join(f"INFO step {i}" for i in range(20))
    assert detect_test_runner(plain_log) != "npm_tree"

    small_tree = "app@1.0.0 /srv/app\n" + "".join(
        f"├── pkg-{i}@1.0.0\n" for i in range(5)
    )
    assert detect_test_runner(small_tree) != "npm_tree"
