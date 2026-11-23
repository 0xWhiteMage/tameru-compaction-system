import importlib

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("field", ["stored_at", "ttl"])
def test_huge_metadata_integer_is_rejected(field):
    data = {"stored_at": 1, "ttl": 1, field: 10**400}
    assert c._ccr_metadata(data) is None
    assert c._ccr_metadata({"stored_at": 1, "ttl": 2}) == (1, 2)
    assert c._ccr_metadata({}) is None
