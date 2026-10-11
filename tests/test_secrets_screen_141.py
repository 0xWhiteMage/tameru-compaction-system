from tameru.compress_context import contains_secret


def test_google_api_key_matches():
    assert contains_secret("key=AIza" + "0" * 35)


def test_stripe_live_keys_match():
    assert contains_secret("sk_live_" + "0" * 16)
    assert contains_secret("rk_live_" + "0" * 16)


def test_bearer_tokens_match():
    assert contains_secret("Authorization: Bearer " + "a" * 20)
    assert contains_secret("Bearer " + "a" * 20)


def test_unquoted_assignments_match():
    assert contains_secret("API_KEY=" + "a" * 16)
    assert contains_secret("OPENAI_API_KEY=" + "a" * 16)
    assert contains_secret("password=" + "a" * 16)


def test_old_patterns_still_match():
    assert contains_secret("AKIA" + "A" * 16)
    assert contains_secret("ghp_" + "a" * 20)
    assert contains_secret("sk-ant-" + "a" * 20)
    assert contains_secret('password="abcdefghijklmnop"')


def test_negative_prose_does_not_match():
    for text in (
        "the secret is out",
        "password: see docs",
        "api_key = None",
        "token=abc",
    ):
        assert not contains_secret(text)
