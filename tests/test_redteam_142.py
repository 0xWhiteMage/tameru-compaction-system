"""v1.5.0 red-team: serving untrusted tool output from many users.

Each test pins a confirmed defect: super-linear time on hostile input, a crash
on a lone surrogate, the receipt copying the whole input, and credential shapes
the secrets screen missed. Timing tests assert SCALING (4x input < 6x time, see
test_perf_regressions), never milliseconds.
"""
from __future__ import annotations

import json
import random
import re

import pytest

from tameru import compress_context as cc
from tameru import format_adapters as fa
from tameru.compress_context import compress_context, contains_secret
from tameru.contract_gates import LATIN_IDENT_RE, distinctive_query_terms

from test_perf_regressions import assert_scales_linearly

KW = dict(ccr=False, citations=False)


# --- quadratic regexes -------------------------------------------------------


@pytest.mark.perf
@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda n: "\n" * n, id="blank-lines"),
        pytest.param(lambda n: " \n" * (n // 2), id="space-newline"),
        pytest.param(lambda n: "[a]\n[b]\n" + "\n" * n, id="ini-then-blanks"),
        pytest.param(lambda n: "a" + "\n" * n + "=1", id="key-then-blanks"),
        pytest.param(lambda n: "SELECT 1\n" + "\n" * n + "SELECT 2", id="sql-then-blanks"),
    ],
)
def test_detect_format_is_linear_on_blank_lines(make):
    # ``(?m)^\s*KEYWORD`` also eats newlines: a run of blank lines was rescanned
    # from every line start (20,000 blank lines took > 20 s).
    assert_scales_linearly(
        lambda: fa.detect_format(make(8000)),
        lambda: fa.detect_format(make(32000)),
        "detect_format",
    )


@pytest.mark.perf
def test_compress_context_blank_line_input_is_linear():
    assert_scales_linearly(
        lambda: compress_context("\n" * 8000, "why did it fail?", **KW),
        lambda: compress_context("\n" * 32000, "why did it fail?", **KW),
        "compress_context on blank lines",
    )


def test_sql_ini_markdown_detection_unchanged_by_the_linear_patterns():
    sql = "SELECT 1;\n\n  INSERT INTO t VALUES (1);\n"
    assert fa.detect_format(sql) == "sql"
    assert fa.detect_format("\n\n  select 1\n\n\n  Update t set a=1\n") == "sql"
    assert fa.detect_format("select 1\nplain words only\n") == "text"
    ini = "\n[main]\n  key = 1\n\n[extra]\nother=2\n"
    assert fa.detect_format(ini) == "ini"


OLD_IDENT = re.compile(
    r"[A-Za-z]*\d[A-Za-z0-9_-]*"
    r"|[A-Za-z0-9]+(?:[_./-][A-Za-z0-9]+)+"
    r"|[A-Z]{2,24}"
    r"|[A-Z][a-z]+[A-Z][A-Za-z0-9]*"
)


def test_identifier_pattern_finds_what_it_found_before():
    rng = random.Random(7)
    for alphabet in ("aA1_.-/ ", "aAb1", "AB_ .", "abcXYZ019_-./! \u00e9", "aA"):
        for _ in range(4000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            assert LATIN_IDENT_RE.findall(text) == OLD_IDENT.findall(text), repr(text)
    for text in ("A" * 60 + "1", "A" * 60, "A" * 30 + ".x", "a" * 30 + "-b", "AB" * 40 + "c1"):
        assert LATIN_IDENT_RE.findall(text) == OLD_IDENT.findall(text)


@pytest.mark.perf
@pytest.mark.parametrize("word", ["x", "ab", "a1b"], ids=["letters", "pairs", "mixed"])
def test_single_word_query_is_linear(word):
    # A 20 KB query made of one word was rescanned from every position (~30 s).
    assert_scales_linearly(
        lambda: distinctive_query_terms(word * 2000 + " end"),
        lambda: distinctive_query_terms(word * 8000 + " end"),
        "distinctive_query_terms",
    )


def test_long_query_compiles_each_term_pattern_once(monkeypatch):
    # ``re`` keeps 512 patterns; a query of thousands of short terms recompiled
    # one per term per block (a 30 KB query: ~80k compiles, 8 s).
    terms = [f"t{i:03d}" for i in range(900)]
    blocks = [{"id": i, "start": i, "end": i, "type": "text", "tokens": 5,
               "text": f"row {i} mentions {terms[i % 900]} and nothing else"} for i in range(60)]
    compiled = []
    real = re.compile

    def counting(*args, **kwargs):
        compiled.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(re, "compile", counting)
    cc.score_blocks(blocks, " ".join(terms), content_type="text")
    monkeypatch.undo()
    assert len(compiled) < 3 * len(terms) + 100


# --- crashes -----------------------------------------------------------------


@pytest.mark.parametrize("ccr", [False, True])
@pytest.mark.parametrize("context_has_surrogate", [False, True])
def test_lone_surrogate_in_query_does_not_crash(tmp_path, ccr, context_has_surrogate):
    body = "\n\n".join(f"record {i} value-{i} ordinary status" for i in range(120))
    if context_has_surrogate:
        body = "bad \ud800 line\n\n" + body
    result = compress_context(
        body, "value-77 \udc00 query", ccr=ccr, ccr_dir=tmp_path / "ccr", log_dir=tmp_path / "log"
    )
    assert isinstance(result.compressed_text, str)
    assert isinstance(result.fail_open, bool)


def test_lone_surrogate_in_gap_prefix_and_pins_do_not_crash():
    body = "\n\n".join(f"record {i} value-{i} ordinary status" for i in range(120))
    r = compress_context(body, "value-5", pin_patterns=["value-9"], cache_prefix=True, ccr=False)
    assert isinstance(r.compressed_text, str)
    r = compress_context("\ud800" + body, "value-5", cache_prefix=True, ccr=False)
    assert isinstance(r.compressed_text, str)


# --- receipt -----------------------------------------------------------------


def test_receipt_does_not_copy_the_input():
    # The receipt is audit metadata hosts log. It carried the adapter's text:
    # the whole input, including credentials on lines the output dropped.
    secret = "AKIAZZZZZZZZZZZZZZZZ"
    filler = [f"Routine section {i}: ordinary status record with nothing relevant." for i in range(80)]
    body = "\n\n".join(filler[:40] + [f"config note: key {secret} stored in vault."]
                       + ["needle fact: the answer is 42."] + filler[40:])
    result = compress_context(body, "what is the needle fact answer", ccr=False)
    assert not result.fail_open
    assert secret not in result.compressed_text
    payload = json.dumps(result.receipt, default=str)
    assert secret not in payload
    assert "Routine section 3:" not in payload
    assert len(payload) < len(body) // 2
    fmt = result.receipt["industrial"]["format_result"]
    assert "text" not in fmt
    assert fmt["text_chars"] == len(body)
    assert re.fullmatch(r"[0-9a-f]{64}", fmt["text_sha256"])


def test_format_result_to_dict_is_unchanged_for_direct_callers():
    result = fa.adapt_format("a,b\n1,2\n3,4\n", "1")
    assert "text" in result.to_dict()


# --- secrets screen ----------------------------------------------------------

LIVE = {
    "aws temporary key": "ASIAIOSFODNN7EXAMPLE",
    "aws secret env": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "aws secret ini": "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "aws secret json": '{"SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}',
    "aws session token": "AWS_SESSION_TOKEN=IQoJb3JpZ2luX2VjEJr//////////wEaCXVzLWVhc3QtMSJHMEUCIQD",
    "google oauth": "Authorization: ya29.a0AfH6SMBx0123456789abcdefghijklmnopqrstuv",
    "google refresh": "1//0gAbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefghij",
    "slack app token": "xa" + "pp-1-A0123456789-1234567890123-" + "abcdef0123456789" * 2,
    "slack webhook": "https://hooks.slack.com/services/" + "T00000000/B00000000/" + "X" * 24,
    "stripe test key": "sk_test_" + "a1B2" * 8,
    "stripe webhook": "whsec_" + "a1B2c3" * 6,
    "hugging face": "hf_" + "aBcDeFgHiJ" * 4,
    "npm": "npm_" + "aBcDeFgHiJ" * 4,
    "pypi": "pypi-AgEIcHlwaS5vcmc" + "A" * 60,
    "twilio": "SK" + "0123456789abcdef" * 2,
    "sendgrid": "SG." + "a" * 22 + "." + "b" * 43,
    "mailgun": "key-" + "0123456789abcdef" * 2,
    "gitlab": "glpat-" + "aB1" * 7,
    "postgres url": "DATABASE_URL=postgres://admin:S3cr3tP4ssw0rd@db.example.com:5432/app",
    "mongodb url": "mongodb+srv://user:p4ssw0rdXYZ@cluster0.mongodb.net/test",
    "redis url": "redis://:longredispassword123@cache:6379/0",
    "amqp url": "amqps://guest:guestguestguest@rabbit/vhost",
    "basic auth url": "https://deploy:ghx_notatoken_secretvalue12345@github.com/org/repo.git",
    "azure account key": "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=" + "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ01" + "==;",
    "azure sas": "?sv=2020-08-04&ss=b&sig=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG%3D",
    "basic header": "Authorization: Basic dXNlcjpwYXNzd29yZHBhc3N3b3Jk",
    "sshpass": "sshpass -p 'MyS3cretPassw0rd!' ssh host",
    "curl user": "curl -u admin:SuperSecretPassw0rd https://x",
    "json password": '{"password": "correct-horse-battery-staple-1"}',
    "json api key": '{"apiKey": "abcdef0123456789abcdef0123456789"}',
    "json client secret": '{"client_secret": "abcdef0123456789abcdef0123456789"}',
    "django secret key": "SECRET_KEY = 'django-insecure-abcdefghijklmnopqrstuvwxyz0123456789'",
    "private key assignment": "private_key = 'abcdef0123456789abcdef0123456789'",
    "env token": "GITHUB_TOKEN=abcdefghijklmnopqrstuvwxyz0123456789",
    "env access key": "ACCESS_KEY=abcdefghijklmnopqrstuvwxyz012345",
    "npmrc": "//registry.npmjs.org/:_auth" + "Token=" + "abcdef01" + "-2345-6789-abcd-" + "ef0123456789",
    "telegram": "123456789:" + "AAEhBOweik6ad9r_QXMENQjcrTu1mdk8d2k",
    "digitalocean": "dop_v1_" + "0123456789abcdef" * 4,
    "shopify": "shpat_" + "0123456789abcdef" * 2,
    # already detected before 1.5.0: kept as a floor
    "github": "ghp_" + "a" * 36,
    "anthropic": "sk-ant-api03-" + "a1B2_-" * 14,
    "private key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE",
    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
}

HARMLESS = {
    "type annotation": "def f(private_key: PKCS7PrivateKeyTypes, data: bytes) -> bytes:",
    "annotation tail": "    private_key: _EllipticCurvePrivateKey,",
    "placeholder url": "see https://user:pass@example.com/path or http://username:password@host",
    "angle placeholder": "socks5h://<username>:<password>@proxy",
    "template url": "postgres://${DB_USER}:${DB_PASSWORD}@db/app",
    "doc env": "HASS_TOKEN=your-long-lived-access-token",
    "doc hf": "HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx",
    "json word value": '{"api_key": "moa-virtual-provider"}',
    "json refresh word": '{"refresh_token": "singleton-refresh"}',
    "public key": "pk_live_" + "a1B2" * 8,
    "certificate": "-----BEGIN CERTIFICATE-----\nMIIC\n-----END CERTIFICATE-----",
    "code call": "client_secret = load_client_secret(path)",
    "code attr": "session_token = response.session_token",
    "ordinary url": "GET https://example.com:8443/a/b?x=1 200",
    "git ssh": "git@github.com:org/repo.git and ssh://git@host:22/repo",
    "prose": "the token budget is large and the secret is out; basic usage of curl",
    "max tokens": "MAX_TOKEN=4096 and max_tokens=2048 sig=ok",
}


@pytest.mark.parametrize("name", sorted(LIVE))
def test_credential_shapes_are_recognised(name):
    assert contains_secret(LIVE[name]), name
    assert contains_secret("log line before\n" + LIVE[name] + "\nlog line after"), name


@pytest.mark.parametrize("name", sorted(HARMLESS))
def test_placeholders_and_code_are_not_credentials(name):
    assert not contains_secret(HARMLESS[name]), name


def test_secret_prefilter_agrees_with_the_bare_patterns():
    # ``_secret_scan`` skips the regexes on ASCII text without any literal an
    # alternative needs: that list has to stay in step with the patterns.
    rng = random.Random(11)
    fragments = list(LIVE.values()) + list(HARMLESS.values()) + [
        "password=", "token", "Token:", "KEY=", "secret_key:", "://", ":", "@", "\n", " ", '"', "'",
        "abc123", "x" * 24, "0123456789", "Bearer ", "curl ", "-u ", "sig=", "Key=",
    ]
    for _ in range(3000):
        text = "".join(rng.choice(fragments) + rng.choice(["", " ", "\n"]) for _ in range(rng.randint(1, 5)))
        bare = cc._SECRETS_RE.search(text) is not None or cc._SECRETS_EXTRA_RE.search(text) is not None
        assert cc._secret_scan(text) == bare, repr(text)


@pytest.mark.perf
@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda n: "a://b:" * (n // 6), id="schemes"),
        pytest.param(lambda n: "http://" + "u" * n + ":" + "p" * n, id="long-userinfo"),
        pytest.param(lambda n: "curl " * (n // 5), id="curls"),
        pytest.param(lambda n: "curl " + "x" * n + " -u a:b", id="long-curl"),
        pytest.param(lambda n: "A_" * (n // 2) + "TOKEN", id="token-name"),
        pytest.param(lambda n: "a_" * (n // 2) + "client_secret", id="prefixed-keyword"),
        pytest.param(lambda n: "secret_key = " + "1" * n, id="long-value"),
        pytest.param(lambda n: 'password": "' + "a" * n, id="unterminated-quote"),
    ],
)
def test_secret_screen_is_linear_on_hostile_text(make):
    assert_scales_linearly(
        lambda: contains_secret(make(20000)),
        lambda: contains_secret(make(80000)),
        "contains_secret",
    )
