"""Regression and unit tests for explicit synthetic HR matching (no DB)."""

import pytest

from app.services.synthetic_hr_cleanup import (
    assert_safe_real_domain_examples,
    is_synthetic_hr,
    primary_synthetic_bucket,
    synthetic_match_reasons,
)


@pytest.mark.parametrize(
    "email,name,company",
    [
        ("recruiter@exactlycorp.com", "R", "Exactly"),
        ("h@unacademy.com", "HR", "Unacademy"),
        ("team@talkdesk.com", "T", "Talkdesk"),
        ("x_user@exactlycorp.com", "User", "Exactlycorp"),
        ("contact@xactlycorp.com", "C", "Xactly"),
        ("hello@sub.unacademy.com", "Ann", "Unacademy"),
    ],
)
def test_real_company_domains_never_match(email: str, name: str, company: str) -> None:
    assert not is_synthetic_hr(email=email, name=name, company=company)


def test_assert_safe_real_domain_examples_runs() -> None:
    assert_safe_real_domain_examples()


def test_email_local_prefixes() -> None:
    assert is_synthetic_hr(email="tb0_seed@talkdesk.com", name="Rec", company="Talkdesk")
    assert is_synthetic_hr(email="tb1_a@corp.com", name="A", company="B")
    assert is_synthetic_hr(email="od1_x@corp.com", name="X", company="Y")
    assert is_synthetic_hr(email="od2_x@corp.com", name="X", company="Y")
    assert is_synthetic_hr(email="dm_hr@corp.com", name="D", company="M")
    assert is_synthetic_hr(email="xx_test@corp.com", name="T", company="T")
    assert is_synthetic_hr(email="x_alias@corp.com", name="A", company="B")
    assert is_synthetic_hr(email="x_seed@corp.com", name="Xavier", company="Y")
    assert not is_synthetic_hr(email="xavier@corp.com", name="Xavier", company="Yard")


def test_synthetic_domains_exact_only() -> None:
    assert is_synthetic_hr(email="a@acme.com", name="N", company="C")
    assert is_synthetic_hr(email="b@ACME.COM", name="N", company="C")
    assert not is_synthetic_hr(email="c@notacme.com", name="N", company="C")
    assert not is_synthetic_hr(email="d@acmecorp.com", name="N", company="C")


def test_exact_placeholder_name_or_company() -> None:
    assert is_synthetic_hr(email="z@z.com", name="C0", company="RealCo")
    assert is_synthetic_hr(email="z@z.com", name="Real", company="Co2")
    assert is_synthetic_hr(email="z@z.com", name="Good", company="Other")
    assert not is_synthetic_hr(email="z@z.com", name="Goodwill", company="Other")


def test_primary_bucket_priority_domain_over_prefix() -> None:
    assert primary_synthetic_bucket(email="tb0_x@acme.com", name="N", company="C") == "domain:acme.com"


def test_reasons_lists_all_matches() -> None:
    rs = synthetic_match_reasons(email="tb0_x@acme.com", name="A", company="Co")
    assert "domain:acme.com" in rs
    assert any(r.startswith("email_local_prefix:") for r in rs)
    assert "name_exact:a" in rs
    assert "company_exact:co" in rs
