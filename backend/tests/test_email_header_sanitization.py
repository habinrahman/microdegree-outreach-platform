from app.services.email_sender import _sanitize_rfc_header_value


def test_sanitize_strips_crlf():
    assert "\n" not in _sanitize_rfc_header_value("a\nBcc: evil@x.com")
    assert "\r" not in _sanitize_rfc_header_value("a\rb")


def test_sanitize_truncates():
    long = "x" * 2000
    s = _sanitize_rfc_header_value(long, max_len=100)
    assert len(s) == 100
