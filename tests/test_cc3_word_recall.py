import importlib

c = importlib.import_module("tameru.compress_context")


def test_plain_terms_require_word_boundaries():
    assert c.verify_compression("cat", "concatenate", "cat")["entity_recall"] == 0
    assert c.verify_compression("concatenate", "", "cat")["keys_total"] == 0
    assert c.verify_compression("cat", "A CAT!", "cat")["entity_recall"] == 1
    assert c._key_in_blob("src/a.py:12", "see src/a.py:12: error")
    assert c._key_in_blob("db_prod-01", "[db_prod-01]")
    assert c.verify_compression("", "", "")["keys_total"] == 0
