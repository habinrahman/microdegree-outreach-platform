from app.services.resume_profile_extract import _guess_experience_years, _guess_skills_line


def test_guess_experience_from_text():
    t = "Software engineer with 5 years of experience in Python."
    assert _guess_experience_years(t) == 5


def test_guess_skills_from_skills_header():
    t = "Skills: Python, AWS, Kubernetes\n\nExperience\n..."
    s = _guess_skills_line(t)
    assert s is not None
    assert "Python" in s
