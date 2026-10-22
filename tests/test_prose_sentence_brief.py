import pytest

from tameru.compress_context import compress_context, _split_prose_sentences


def notes(title, line, fact, n=24, cut=14):
    body = [line.format(i=i + 1, r=(i * 7) % 83 + 3) for i in range(n)]
    return title + "\n\n" + " ".join(body[:cut]) + "\n\n" + fact + "\n\n" + " ".join(body[cut:]) + "\n"


def brief(t):
    return compress_context(t, "", ccr=False, citations=False, prose_brief=True)


CASES = [
    (
        "Resumo semanal",
        "Na semana {i}, a equipe revisou {r} pedidos de mudança e atualizou a documentação interna.",
        "O incidente mais grave ocorreu em 11 de outubro: a fila de pagamentos ficou bloqueada por 37 minutos.",
        ["11 de outubro", "37 minutos"],
    ),
    (
        "Ringkasan mingguan",
        "Pada minggu ke-{i}, tim menyelesaikan {r} tiket dan memperbarui catatan rilis.",
        "Masalah terbesar terjadi pada 4 Juli ketika layanan login gagal selama 58 menit.",
        ["4 Juli", "58 menit"],
    ),
    (
        "สรุปงานประจำสัปดาห์",
        "ในสัปดาห์ที่ {i} ทีมได้ตรวจสอบอุปกรณ์ {r} เครื่องและปรับปรุงเอกสาร",
        "เหตุการณ์สำคัญเกิดขึ้นวันที่ 19 กันยายน เมื่อเราเตอร์หลักรีบูตเองและเครือข่ายล่มนาน 26 นาที",
        ["19 กันยายน", "26 นาที"],
    ),
    (
        "साप्ताहिक सारांश",
        "सप्ताह {i} में टीम ने {r} टिकट बंद किए और दस्तावेज़ अपडेट किए।",
        "सबसे बड़ी समस्या 8 अगस्त को हुई, जब खोज सेवा 44 मिनट तक उपलब्ध नहीं रही।",
        ["8 अगस्त", "44 मिनट"],
    ),
    (
        "Haftalık özet",
        "{i}. haftada ekip {r} değişiklik talebini inceledi ve belgeleri güncelledi.",
        "En ciddi sorun 23 Mart'ta yaşandı: veritabanı yedeği 71 dakika boyunca kilitli kaldı.",
        ["23 Mart", "71 dakika"],
    ),
]


@pytest.mark.parametrize("title,line,fact,facts", CASES)
def test_prose_sentence_brief_keeps_facts_and_compresses(title, line, fact, facts):
    text = notes(title, line, fact)
    result = brief(text)
    for needle in facts:
        assert needle in result.compressed_text
    assert len(result.compressed_text) < 0.3 * len(text)
    assert not result.fail_open


def test_distinct_prose_stays_whole():
    sentences = [
        "The new espresso machine in the lobby finally works again.",
        "Marta presented the hiring plan to the board on Tuesday.",
        "The river path near the old mill smells like rain.",
        "A quiet bakery opened beside the station this spring.",
        "The librarian saved the last copy of the field guide.",
        "Our repair van missed the bridge closure by minutes.",
        "The night crew painted the crosswalk before dawn.",
        "A small ferry carried the mail across the bay.",
        "The museum guard found a coin in the coat pocket.",
        "The bakery cat slept on the warm flour sacks.",
        "A storm dropped power to the hillside homes.",
        "The post office returned the package to its sender.",
    ]
    paragraph = " ".join(sentences)
    text = "Status notes\n\n" + paragraph + "\n"
    lines = _split_prose_sentences(text.split("\n"))
    assert len([line for line in lines if line]) >= 12
    assert brief(text).compressed_text == text


def test_split_prose_sentences_short_line_identity():
    lines = ["short line."]
    assert _split_prose_sentences(lines) is lines


def test_split_prose_sentences_does_not_split_numbered_weeks():
    line = (
        "1. haftada ekip 42 talebi inceledi ve belgeleri güncelledi. "
        "2. haftada ekip 17 talebi inceledi ve belgeleri güncelledi. "
        "3. haftada ekip 9 talebi inceledi ve belgeleri güncelledi."
    )
    parts = [part for part in _split_prose_sentences([line]) if part]
    assert parts
    for part in parts:
        assert part[0].isdigit()
        assert part[1:].startswith(". haftada")
