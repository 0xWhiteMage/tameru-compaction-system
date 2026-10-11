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


def test_code_expressions_are_not_unquoted_secrets():
    """Red-team (1.4.1): the unquoted-assignment pattern flagged ordinary code, so ``contains_secret`` was true for
    141 of 2,372 non-test Python files of a Hermes checkout (9 before 1.4.1), and the plugin's recovery store
    refused to keep those originals. A value that is a call, an index, an attribute chain or an interpolation
    names no credential."""
    for text in (
        "password = get_password_from_vault()",
        "api_key = os.getenv(self.config.api_key_env)",
        "api_key = agent._anthropic_api_key",
        "explicit_api_key=binding.explicit_api_key,",
        "otp_secret = normalize_otp_secret(str(secret.get('x')))",
        "db_password: ${DB_PASSWORD_FROM_ENV}",
        "auth_token=<redacted-by-server>",
        "access_token = token_response['access_token']",
        "explicit_api_key=_fb_explicit_key,",
        "stale_access_token=stale_access_token)",
    ):
        assert not contains_secret(text), text


def test_unquoted_credentials_with_punctuation_still_match():
    assert contains_secret("password=p@ss!word#2024xyz")
    assert contains_secret("DB_PASSWORD=Xk9-2mQ_vL8+pR4/zT6=")
    assert contains_secret("api_key: abcdef0123456789abcdef")


def test_the_code_exclusions_stay_linear():
    import time

    for text in ("api_key=a" + "_a" * 200_000 + "!", "api_key=" + "ab." * 200_000 + "a!", "api_key=x_y " * 50_000):
        started = time.perf_counter()
        contains_secret(text)
        assert time.perf_counter() - started < 2.0


# ---- 1.4.1 fix-all (R3): whole-line env / YAML assignments -------------------------------------------------
def test_env_and_yaml_lines_with_identifier_like_values_match():
    assert contains_secret("DB_PASSWORD=correct_horse_battery_staple")
    assert contains_secret("export API_KEY=prod_key_for_billing_v2\n")
    assert contains_secret("HOST=db\npassword=hunter2.example.org.pass\nPORT=5432")
    assert contains_secret("AUTH_TOKEN=team.alpha.deploy.token.x")
    assert contains_secret("db:\n  secret: correct_horse_battery_staple\n")


def test_code_lines_with_identifier_values_still_do_not_match():
    for text in (
        "password = settings_default_password",
        "conn = connect(password=db_password_setting)",
        "    user_password=args.user_password,",
        "            app_secret=self._app_secret,",
        "api_key: pydantic.types.SecretStr",
        "PASSWORD=${DB_PASSWORD_FROM_VAULT}",
        "secret = self.config.secret_value_x",
        "  access_token: Optional[str] = None",
        "x = 1; password=fallback_password_value",   # not a whole line
    ):
        assert not contains_secret(text), text


def test_the_line_anchored_assignments_stay_linear():
    import time

    for text in ("db_" * 200_000 + "password=" + "a_" * 1000 + ",", ("secret_" * 2000 + "x\n") * 50, "API_KEY=" + "a_" * 300_000 + ")"):
        started = time.perf_counter()
        contains_secret(text)
        assert time.perf_counter() - started < 2.0
