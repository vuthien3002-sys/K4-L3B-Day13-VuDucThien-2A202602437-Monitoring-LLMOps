from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    for cccd in ("001099012345", "079203001234"):
        out = scrub_text(f"CCCD cua toi la {cccd}.")
        assert cccd not in out
        assert "REDACTED_CCCD" in out
        # Không bị nhận nhầm thành số điện thoại dù bắt đầu bằng 0
        assert "REDACTED_PHONE_VN" not in out


def test_scrub_credit_card_formats() -> None:
    cards = (
        "4111111111111111",
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "0123 4567 8901 2345",
    )

    for card in cards:
        out = scrub_text(f"Card: {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out
        assert "REDACTED_PHONE_VN" not in out


def test_scrub_passport_vn() -> None:
    out = scrub_text("Passport B1234567 het han 2030")
    assert "B1234567" not in out
    assert "REDACTED_PASSPORT_VN" in out


def test_scrub_keeps_non_pii_text() -> None:
    text = "How do I debug tail latency for req-1a2b3c4d?"
    assert scrub_text(text) == text
