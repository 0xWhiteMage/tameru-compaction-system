from tameru.compress_context import _extract_terms, _topic_terms, estimate_tokens


def test_spanish_accented_term_is_whole():
    query = "¿qué problema hubo con la réplica?"
    assert "réplica" in _topic_terms(query)
    assert "plica" not in _extract_terms(query)


def test_italian_accented_term_is_whole():
    query = "la funzionalità è stata ritirata?"
    assert "funzionalità" in _extract_terms(query)
    assert "funzionalit" not in _extract_terms(query)


def test_portuguese_accented_term_is_whole():
    assert "migração" in _topic_terms("por que a migração falhou?")


def test_german_sharp_s_term_is_whole():
    assert "schlägt" in _topic_terms("Warum schlägt der Größenvergleich fehl?")


def test_vietnamese_term_is_whole():
    assert "chứng" in _extract_terms("gia hạn chứng chỉ")


def test_ascii_terms_unchanged():
    terms = _extract_terms("why did the deploy_job fail on node-7?")
    assert "deploy_job" in terms
    assert "fail" in terms


def test_token_estimation_smoke():
    assert estimate_tokens("la réplica de lectura") > 0
