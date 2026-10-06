"""E4: code is not CSV, TSV or YAML."""
from tameru.compress_context import _looks_like_csv, compress_context, preprocess_csv
from tameru.format_adapters import detect_format

JS = """import { alpha, beta, gamma } from './lib';
const config = { host: 'localhost', port: 8080 };

function handleRequest(req, res) {
  const { id, name } = req.params;
  if (!id) {
    return res.status(400).send('missing id');
  }
  const record = lookup(id, name, config);
  return res.json({ id, name, record });
}

function special_handler(a, b, c) {
  return [a, b, c].map((x) => x * 2);
}

export default handleRequest;
""" + "\n".join(f"const v{i} = compute({i}, {i + 1}, {i + 2});" for i in range(30))

TS = """export interface Row { id: number; a: string; b: string; c: string }
export const rows: Row[] = [
  { id: 1, a: 'x', b: 'y', c: 'z' },
  { id: 2, a: 'x', b: 'y', c: 'z' },
  { id: 3, a: 'x', b: 'y', c: 'z' },
  { id: 4, a: 'x', b: 'y', c: 'z' },
  { id: 5, a: 'x', b: 'y', c: 'z' },
];
export function pick(id: number, a: string, b: string): Row | undefined {
  return rows.find((r) => r.id === id && r.a === a && r.b === b);
}
"""

PY = '''import os
from typing import Optional


class Service:
    """A service."""

    def __init__(self, name: str, retries: int = 3):
        self.name = name
        self.retries = retries

    def run(self, job):
        try:
            for attempt in range(self.retries):
                if job.ready():
                    return job.execute()
        except TimeoutError as exc:
            raise RuntimeError(str(exc))
        else:
            return None
        finally:
            cleanup(job)


def main(argv=None):
    with open(os.devnull) as sink:
        svc = Service("x")
        return svc.run(sink)
'''

CSV = "id,name,status,owner\n" + "\n".join(
    f"{i},svc-{i},{'ok' if i % 5 else 'failed'},team-{i % 4}" for i in range(1, 40)
)

QUOTED_CSV = 'id,name,note\n' + "\n".join(
    f'{i},"Smith, John {i}","said ""hi"", twice"' for i in range(1, 20)
)


def test_js_with_commas_in_its_first_line_is_not_csv():
    assert not _looks_like_csv(JS)
    assert preprocess_csv(JS, "what does special_handler do?") == JS
    assert detect_format(JS) not in {"csv", "tsv", "yaml"}
    result = compress_context(
        JS, "what does special_handler do?", ccr=False, citations=False
    )
    assert result.content_type not in {"csv", "tsv"}
    assert "return [a, b, c].map((x) => x * 2);" in result.compressed_text


def test_ts_object_literals_are_not_csv():
    assert not _looks_like_csv(TS)
    assert detect_format(TS) not in {"csv", "tsv", "yaml"}


def test_python_is_not_yaml():
    assert detect_format(PY) not in {"yaml", "csv", "tsv", "markdown", "sql"}
    result = compress_context(PY, "what does Service.run do on timeout?", ccr=False, citations=False)
    assert result.content_type not in {"yaml", "csv", "tsv"}
    assert not result.receipt["industrial"]["applied"]


def test_python_with_comment_headings_is_not_markdown_or_sql():
    py = "\n".join(
        ["# Section one", "import os", ""]
        + [
            "with open(p) as f:",
            "    data = f.read()",
            "with lock:",
            "    update(data)",
            "# Section two",
            "def f(x):",
            "    return x",
        ]
        * 3
    )
    assert detect_format(py) not in {"markdown", "sql", "yaml"}


def test_real_yaml_is_still_yaml():
    yaml = "services:\n  api:\n    host: prod-77\n    port: 8080\n  db:\n    host: db-1\n"
    assert detect_format(yaml) == "yaml"
    gh = (
        "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: Checkout\n        uses: actions/checkout@v4\n"
        "      - name: Test\n        if: always()\n        with:\n          path: x\n"
    )
    assert detect_format(gh) == "yaml"


def test_a_real_csv_is_still_detected_and_selected():
    assert detect_format(CSV) == "csv"
    assert _looks_like_csv(CSV)
    kept = preprocess_csv(CSV, "which row is svc-7?")
    assert "svc-7" in kept and len(kept.split("\n")) < len(CSV.split("\n"))
    result = compress_context(CSV, "which row is svc-7?", ccr=False, citations=False)
    assert result.content_type == "csv"


def test_a_csv_with_quoted_commas_is_still_a_csv():
    assert _looks_like_csv(QUOTED_CSV)
    assert detect_format(QUOTED_CSV) == "csv"


def test_sql_scripts_are_still_sql():
    sql = "CREATE TABLE alpha (id int);\nCREATE TABLE beta (id int);\nINSERT INTO alpha VALUES (1);"
    assert detect_format(sql) == "sql"
