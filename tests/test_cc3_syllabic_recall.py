import importlib

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("term,blob", [("障害", "接続障害発生"), ("错误", "发生错误了"),
                                      ("오류", "연결오류발생")])
def test_unsegmented_script_keys_keep_substring_matching(term, blob):
    assert c._key_in_blob(term, blob)
