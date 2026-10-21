import pytest

from tameru.compress_context import _fold_repeated_sentences, compress_context


def prose(intro: str, body: str, fact: str, outro: str) -> str:
    return intro * 6 + "\n\n" + body * 5 + "\n\n" + fact + "\n\n" + outro * 4 + "\n"


CASES = [
    (
        "english",
        "The quarterly report summarises the activity of the operations team. ",
        "During the quarter the services were migrated to the new cluster without serious incidents. ",
        "The only outage happened on 14 August, when the load balancer rejected connections for 37 minutes.",
        "The team plans to automate certificate renewal next quarter. ",
        ["14 August", "37 minutes"],
    ),
    (
        "spanish",
        "¿Qué hizo el equipo este mes? El equipo trabajó en la migración de la base de datos. ",
        "¡La migración terminó a tiempo! Los usuarios no notaron cambios importantes. ",
        "El único problema fue el 30 de abril: la réplica de lectura se retrasó 18 minutos.",
        "El próximo mes revisaremos los índices de la base de datos. ",
        ["30 de abril", "18 minutos"],
    ),
    (
        "vietnamese",
        "Báo cáo này tóm tắt công việc của nhóm vận hành trong quý. ",
        "Trong quý, nhóm đã chuyển toàn bộ dịch vụ sang trung tâm dữ liệu mới. ",
        "Sự cố duy nhất xảy ra vào ngày 12 tháng 8, khi bộ cân bằng tải từ chối kết nối trong 41 phút.",
        "Quý tới nhóm sẽ tự động hóa việc gia hạn chứng chỉ. ",
        ["12 tháng 8", "41 phút"],
    ),
    (
        "thai",
        "รายงานนี้สรุปการทำงานของทีมระบบในไตรมาสนี้ ",
        "ในไตรมาสนี้ทีมได้ย้ายบริการทั้่งหมดไปยั่่งศู่่นย์ข้อมูลแห่่งใหม่่ ",
        "เหตุขัดข้องครั้่งเดียวเกิดขึ้้นวันที่ 5 สิงหาคม เมื่่อฐานข้อมูลหยุดทำงานนาน 33 นาที",
        "ไตรมาสหน้าทีมจะเพิ่่มการแจ้้งเตือนอัติโนมัติ ",
        ["5 สิงหาคม", "33 นาที"],
    ),
    (
        "arabic",
        "يلخص هذا التقرير عمل فريق البنية التحتية خلال الشهر. ",
        "قام الفريق هذا الشهر بتحديث خوادم قاعدة البيانات دون انقطاع. ",
        "حدث العطل الوحيد في 17 مايو عندما توقفت الخدمة لمدة 48 دقيقة.",
        "سيقوم الفريق الشهر القادم بإعداد تنبيهات لمساحة القرص. ",
        ["17 مايو", "48 دقيقة"],
    ),
    (
        "hindi",
        "यह रिपोर्ट इस महीने की संचालन टीम के काम का सारंश देती है। ",
        "इस महीने टीम ने सभी सर्वरों को नए डेटा सेंटर में स्थानांतरित किया। ",
        "एकमात्र समस्या 14 जून को हुई, जब भुगतान सेवा 29 मिनट तक बंद रही।",
        "अगले महीने टीम स्वचालित निगरानी जोड़ेंगी। ",
        ["14 जून", "29 मिनट"],
    ),
]


@pytest.mark.parametrize("name,intro,body,fact,outro,facts", CASES)
def test_repeated_sentence_fold_in_compress_context(
    name: str, intro: str, body: str, fact: str, outro: str, facts: list[str]
) -> None:
    text = prose(intro, body, fact, outro)
    r = compress_context(
        text,
        "",
        ccr=False,
        citations=False,
        anchor_errors=True,
        prose_brief=True,
    )

    for f in facts:
        assert f in r.compressed_text
    assert "[\u00d76]" in r.compressed_text
    assert len(r.compressed_text) < len(text) * 0.5


def test_fold_repeated_sentences_short_count_and_line_unchanged() -> None:
    line = "Status ok. " * 2
    assert _fold_repeated_sentences([line]) == [line]


def test_fold_repeated_sentences_preserves_indent() -> None:
    line = "  " + "The cache was warmed for all regions. " * 3
    assert _fold_repeated_sentences([line]) == [
        "  [\u00d73] The cache was warmed for all regions."
    ]


def test_fold_repeated_sentences_distinct_sentences_unchanged() -> None:
    line = "The build passed. The deploy started. The deploy finished on time today."
    assert _fold_repeated_sentences([line]) == [line]


def test_fold_repeated_sentences_unit_too_short_unchanged() -> None:
    line = "ab " * 40
    assert _fold_repeated_sentences([line]) == [line]
