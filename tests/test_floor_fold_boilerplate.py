from tameru.compress_context import compress_context


def prose(intro, body, fact, outro):
    return intro * 6 + "\n\n" + body * 5 + "\n\n" + fact + "\n\n" + outro * 4 + "\n"


def test_floor_path_drops_bare_fold_boilerplate_when_answer_present():
    text = prose(
        "The monthly report summarises the work of the operations team this quarter. ",
        "The team moved every service to the new data centre without major problems. ",
        "The only outage happened on 2 March when the mail server was unreachable for 64 minutes.",
        "Next quarter the team will add automatic monitoring to every service. ",
    )

    r = compress_context(
        text,
        "when did the outage happen",
        ccr=False,
        citations=False,
        prose_brief=True,
    )

    assert "2 March" in r.compressed_text
    assert "64 minutes" in r.compressed_text
    assert "data centre" not in r.compressed_text
    assert len(r.compressed_text) < 0.2 * len(text)


def test_no_query_hit_behavior_unchanged():
    text = prose(
        "The monthly report summarises the work of the operations team this quarter. ",
        "The team moved every service to the new data centre without major problems. ",
        "The only outage happened on 2 March when the mail server was unreachable for 64 minutes.",
        "Next quarter the team will add automatic monitoring to every service. ",
    )

    r = compress_context(text, "zebra giraffe", ccr=False, citations=False)

    assert "2 March" in r.compressed_text
