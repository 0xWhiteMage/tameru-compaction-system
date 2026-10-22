from tameru.agent_formats import detect_test_runner, _classify_openssl_sclient
from tameru.compress_context import compress_context


def test_unterminated_certificate_is_not_folded():
    lines = [
        "CONNECTED(00000003)",
        "-----BEGIN CERTIFICATE-----",
        "MIIF" + "A" * 20,
        "Verify return code: 20 (unable to get local issuer certificate)",
    ]
    keep, _, _ = _classify_openssl_sclient(lines)
    assert all(keep)


def _sample_text() -> str:
    return (
        "CONNECTED(00000003)\n"
        + "".join(
            f"depth={3 - i} C = US, O = Example Trust {i}, CN = Example Root {i}\n"
            "verify return:1\n"
            for i in range(3)
        )
        + "depth=0 CN = api.example.com\n"
        + "verify error:num=20:unable to get local issuer certificate\n"
        + "verify return:1\n"
        + "---\n"
        + "Certificate chain\n"
        + "".join(
            f" {i} s:CN = node{i}.example.com\n"
            f"   i:CN = Example Intermediate {i + 1}\n"
            "   a:PKEY: rsaEncryption, 2048 (bit); sigalg: RSA-SHA256\n"
            "   v:NotBefore: Jan  1 00:00:00 2026 GMT; NotAfter: Jan  1 00:00:00 2027 GMT\n"
            for i in range(8)
        )
        + "---\n"
        + "Server certificate\n"
        + "-----BEGIN CERTIFICATE-----\n"
        + "".join("MIIF" + "A" * 60 + "\n" for _ in range(25))
        + "-----END CERTIFICATE-----\n"
        + "subject=CN = api.example.com\n"
        + "---\n"
        + "Verification error: unable to get local issuer certificate\n"
        + "---\n"
        + "New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384\n"
        + "Verify return code: 20 (unable to get local issuer certificate)\n"
    )


def test_detect_openssl_sclient() -> None:
    text = _sample_text()
    assert detect_test_runner(text) == "openssl_sclient"


def test_compress_openssl_sclient_keeps_verification_and_folds_body() -> None:
    text = _sample_text()
    for query in ("", "why does certificate verification fail"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "verify error:num=20" in out
        assert "Verify return code: 20" in out
        assert "NotAfter: Jan  1 00:00:00 2027 GMT" in out
        assert "-----BEGIN CERTIFICATE-----" in out
        assert "-----END CERTIFICATE-----" in out
        assert "MIIF" + "A" * 60 not in out
        assert len(out) < 0.6 * len(text)


def test_classify_does_not_fold_private_key_and_drops_pkey() -> None:
    lines = [
        "CONNECTED(00000003)",
        "Certificate chain",
        " 0 s:CN = node0.example.com",
        "   i:CN = Example Intermediate 1",
        "   a:PKEY: rsaEncryption, 2048 (bit); sigalg: RSA-SHA256",
        "   v:NotBefore: Jan  1 00:00:00 2026 GMT; NotAfter: Jan  1 00:00:00 2027 GMT",
        "-----BEGIN PRIVATE KEY-----",
        "XXXX",
        "XXXX",
        "XXXX",
        "-----END PRIVATE KEY-----",
    ]
    keep, _, _ = _classify_openssl_sclient(lines)
    assert keep[4] is False
    for index in range(6, 11):
        assert keep[index] is True


def test_negative_without_connected() -> None:
    text = _sample_text().replace("CONNECTED(00000003)", "CONNECTED?")
    assert detect_test_runner(text) != "openssl_sclient"
