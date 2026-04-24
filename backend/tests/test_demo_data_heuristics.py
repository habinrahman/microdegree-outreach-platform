"""Unit tests for demo/synthetic row heuristics (no database)."""

from app.services.demo_data_heuristics import assess_hr, assess_student


def test_is_demo_always_high_risk():
    r = assess_student(name="Real Person", gmail_address="real@gmail.com", is_demo=True)
    assert r.score >= 100
    h = assess_hr(name="Recruiter", company="Acme Inc", email="rec@acme.com", is_demo=True)
    assert h.score >= 100


def test_disposable_domain_student():
    r = assess_student(name="Alice", gmail_address="alice@example.com", is_demo=False)
    assert r.score >= 50
    assert any("domain_disposable" in x for x in r.reasons)


def test_real_gmail_low_risk():
    r = assess_student(name="Jane Doe", gmail_address="jane.doe@gmail.com", is_demo=False)
    assert r.score < 50


def test_synthetic_exact_name_not_enough_alone():
    r = assess_student(name="Tie", gmail_address="tie@gmail.com", is_demo=False)
    # Exact synthetic name = 25, below default cleanup threshold 50
    assert 20 <= r.score < 50


def test_synthetic_name_plus_disposable_domain():
    r = assess_student(name="Tie", gmail_address="tie@example.com", is_demo=False)
    assert r.score >= 50


def test_hr_company_pattern():
    r = assess_hr(name="HR", company="C0", email="h@company.com", is_demo=False)
    assert any("company_pattern" in x for x in r.reasons)
    assert r.score >= 20


def test_local_prefix_fixture():
    r = assess_student(name="Bob", gmail_address="test.user@company.com", is_demo=False)
    assert any(x.startswith("local_prefix") for x in r.reasons)
    assert r.score >= 35
