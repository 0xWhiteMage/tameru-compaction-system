import pytest

from tameru.compress_context import _is_filler_query


FILLER_ONLY_QUERIES = [
    "sammanfatta",
    "Sammanfatta",
    "samenvatting",
    "vat samen",
    "oppsummering",
    "yhteenveto",
    "shrnutí",
    "rezumat",
    "összefoglaló",
    "περίληψη",
    "резюме",
    "підсумуй",
    "zusammenfassen",
    "synthèse",
]


NON_FILLER_QUERIES = [
    "sammanfatta databasen",
    "rezumat replica lag",
    "резюме postgres",
]


@pytest.mark.parametrize("query", FILLER_ONLY_QUERIES)
def test_filler_only_query_is_filler(query):
    assert _is_filler_query(query) is True


@pytest.mark.parametrize("query", NON_FILLER_QUERIES)
def test_filler_word_plus_topic_is_not_filler(query):
    assert _is_filler_query(query) is False
