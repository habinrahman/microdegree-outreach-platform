"""Email templates with variables: hr_name, company, student_name, skills, experience."""
import re
import random

# Variables allowed in templates: hr_name, company, student_name, skills, experience
VARIABLE_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(text: str, context: dict) -> str:
    """Replace {{ variable }} with context[variable]. Unknown vars left as-is."""
    def repl(match: re.Match) -> str:
        key = match.group(1)
        return str(context.get(key, match.group(0)))
    return VARIABLE_PATTERN.sub(repl, text)


def pick_template(email_type: str) -> dict:
    """Randomly select one template for the given email_type. Returns {subject, body}."""
    templates = TEMPLATES.get(email_type, TEMPLATES["initial"])
    return random.choice(templates)


# At least 5 templates per type; we use 5 for initial and reuse variants for follow-ups.
TEMPLATES = {
    "initial": [
        {
            "subject": "Application for Opportunities - {{student_name}}",
            "body": """Hello {{hr_name}},

My name is {{student_name}}. I am reaching out to explore potential opportunities at {{company}}.

I have {{experience}} years of experience and my key skills include: {{skills}}.

I have attached my resume for your consideration. I would welcome the opportunity to discuss how I can contribute to your team.

Best regards,
{{student_name}}""",
        },
        {
            "subject": "{{student_name}} - Interest in career opportunities at {{company}}",
            "body": """Dear {{hr_name}},

I am {{student_name}}, and I am very interested in opportunities at {{company}}.

With {{experience}} years of experience and skills in {{skills}}, I believe I can add value to your organization.

Please find my resume attached. I would be glad to connect at your convenience.

Thank you,
{{student_name}}""",
        },
        {
            "subject": "Opportunities at {{company}} - {{student_name}}",
            "body": """Hello {{hr_name}},

I hope this email finds you well. I am {{student_name}}, writing to express my interest in roles at {{company}}.

My background includes {{experience}} years of experience with a focus on {{skills}}.

I have attached my resume and would appreciate the chance to discuss potential fit.

Best regards,
{{student_name}}""",
        },
        {
            "subject": "Resume - {{student_name}} for {{company}}",
            "body": """Dear {{hr_name}},

I am {{student_name}}, reaching out regarding opportunities at {{company}}.

I bring {{experience}} years of experience and expertise in {{skills}}. My resume is attached for your review.

Looking forward to your response.

Sincerely,
{{student_name}}""",
        },
        {
            "subject": "{{student_name}} - Application for {{company}}",
            "body": """Hello {{hr_name}},

My name is {{student_name}}. I am writing to apply for relevant positions at {{company}}.

Experience: {{experience}} years. Skills: {{skills}}.

Please find my resume attached. I would welcome the opportunity to speak with you.

Best regards,
{{student_name}}""",
        },
    ],
    "followup_1": [
        {
            "subject": "Re: Application for Opportunities - {{student_name}} (Follow-up)",
            "body": """Hello {{hr_name}},

I had written to you last week regarding opportunities at {{company}}. I am {{student_name}}.

I wanted to follow up and reiterate my interest. My resume is attached again for your reference ({{experience}} years, {{skills}}).

Would you have a few minutes to connect?

Best regards,
{{student_name}}""",
        },
        {
            "subject": "Following up - {{student_name}} / {{company}}",
            "body": """Dear {{hr_name}},

I am following up on my earlier email about roles at {{company}}. I am {{student_name}}.

I remain very interested and would appreciate any feedback or next steps. My background: {{experience}} years, {{skills}}.

Thank you,
{{student_name}}""",
        },
    ],
    "followup_2": [
        {
            "subject": "Second follow-up - {{student_name}} / {{company}}",
            "body": """Hello {{hr_name}},

This is a second follow-up from {{student_name}} regarding opportunities at {{company}}.

I understand you may be busy. If there is a better time or person to contact, I would be grateful for a brief pointer.

Best regards,
{{student_name}}""",
        },
    ],
    "followup_3": [
        {
            "subject": "Final follow-up - {{student_name}} / {{company}}",
            "body": """Dear {{hr_name}},

This is my final follow-up regarding opportunities at {{company}}. I am {{student_name}} ({{experience}} years, {{skills}}).

If your hiring needs change in the future, I would be happy to hear from you.

Thank you for your time.

{{student_name}}""",
        },
    ],
}


def build_template_context(student, hr) -> dict:
    """Same placeholders as campaign_generator / TEMPLATES."""
    return {
        "hr_name": getattr(hr, "name", None) or "",
        "company": getattr(hr, "company", None) or "",
        "student_name": getattr(student, "name", None) or "",
        "skills": getattr(student, "skills", None) or "N/A",
        "experience": str(getattr(student, "experience_years", None) or 0),
    }


def render_templated_email(student, hr, email_type: str = "initial") -> tuple[str, str]:
    """Pick a random template variant and render subject + body."""
    ctx = build_template_context(student, hr)
    template = pick_template(email_type)
    subj = render_template(template["subject"], ctx)
    bod = render_template(template["body"], ctx)
    return subj, bod


def resolve_email_content(
    student,
    hr,
    subject: str | None,
    body: str | None,
    *,
    stored_subject: str | None = None,
    stored_body: str | None = None,
    email_type: str = "initial",
    days_since_sent: int | None = None,
) -> tuple[str, str]:
    """
    Per field: non-empty custom wins, else stored (e.g. EmailCampaign row), else TEMPLATES.
    """
    from app.services.reply_classifier import FOLLOWUP_TEMPLATES, get_followup_stage

    t_subj, t_body = render_templated_email(student, hr, email_type=email_type)
    if email_type in ("followup_1", "followup_2", "followup_3") and days_since_sent is not None:
        stage = get_followup_stage(days_since_sent)
        fb = FOLLOWUP_TEMPLATES.get(stage)
        if fb:
            t_body = fb
    subj = (subject or "").strip() or (stored_subject or "").strip() or t_subj
    bod = (body or "").strip() or (stored_body or "").strip() or t_body
    return subj, bod
