from tameru.compress_context import _extract_terms, _topic_terms, _is_filler_query


def test_spanish_question_word_is_not_term():
    terms = _extract_terms("¿qué problema hubo con la réplica?")
    assert "qué" not in terms
    assert "réplica" in terms


def test_malay_question_word_is_not_topic_term():
    terms = _topic_terms("bila gangguan berlaku?")
    assert "bila" not in terms
    assert "gangguan" in terms


def test_generic_non_english_asks_are_filler_queries():
    for query in (
        "summarize this",
        "what happened?",
        "¿qué pasó?",
        "o que aconteceu?",
        "résume le rapport",
        "ringkasan",
        "riassunto",
    ):
        assert _is_filler_query(query)


def test_longer_non_english_queries_are_not_filler():
    for query in (
        "why did the report job fail",
        "resume upload failed for user 42",
        "¿por qué falló la réplica?",
    ):
        assert not _is_filler_query(query)


def test_report_is_real_term_in_longer_query():
    assert "report" in _topic_terms("why did the report job fail")
