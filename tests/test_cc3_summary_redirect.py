import importlib
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("allow_remote", [False, True])
def test_summary_opener_disables_redirects(allow_remote):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "A sufficiently long local summary."}}]}
    ).encode()
    opener = MagicMock()
    opener.open.return_value = response
    with patch("urllib.request.build_opener", return_value=opener) as build, \
            patch("urllib.request.urlopen", return_value=response):
        assert c._summarise_with_llm("hello", "query", model_candidates=["model"],
                                     allow_remote=allow_remote) is not None
    assert build.call_count == 1
    handler = build.call_args.args[0]
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(urllib.request.Request("http://localhost/start"), None,
                                 302, "redirect", {}, "https://example.invalid/remote")
