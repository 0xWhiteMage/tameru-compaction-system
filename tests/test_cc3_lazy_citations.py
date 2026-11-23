import importlib

c = importlib.import_module("tameru.compress_context")


def test_no_citation_index_without_citation_gap():
    class Dropped(dict):
        def __getitem__(self, key):
            assert key != "start", "unneeded citation index"
            return super().__getitem__(key)

    blocks = [{"id": 0, "start": 0, "end": 0}, Dropped(id=1)]
    assert c._render(["keep"], blocks, {0}, citations=False) == "keep"
    assert c._render(["keep"], blocks, {0}, citations=True) == "keep"
