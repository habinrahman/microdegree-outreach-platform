"""Best-effort resume text → profile hints (pilot; PDF-focused)."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SKILLS_LEN = 2000


def extract_profile_from_resume_file(local_path: str) -> dict[str, Any]:
    """
    Return {"experience_years": int | None, "skills": str | None}.
    On failure or non-PDF, returns empty dict (caller keeps existing DB fields).
    """
    path = (local_path or "").strip()
    if not path.lower().endswith(".pdf"):
        return {}

    text = _extract_pdf_text(path)
    if not (text or "").strip():
        return {}

    exp = _guess_experience_years(text)
    skills = _guess_skills_line(text)
    out: dict[str, Any] = {}
    if exp is not None:
        out["experience_years"] = exp
    if skills:
        out["skills"] = skills[:_MAX_SKILLS_LEN]
    return out


def _extract_pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts: list[str] = []
        for page in reader.pages[:5]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    except Exception as e:
        logger.info("resume PDF text extract skipped: %s", e)
        return ""


def _guess_experience_years(text: str) -> int | None:
    t = text.lower()
    patterns = [
        r"(\d+)\+?\s*(?:years?|yrs?\.?)\s+(?:of\s+)?(?:relevant\s+)?experience",
        r"(?:experience|exp\.?)\s*[:\-]\s*(\d+)\+?\s*(?:years?|yrs?)",
        r"(\d+)\+?\s*years?\s+in\s+",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            try:
                n = int(m.group(1))
                if 0 <= n <= 60:
                    return n
            except (TypeError, ValueError):
                continue
    return None


def _guess_skills_line(text: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("skills") or low.startswith("technical skills") or low.startswith("core competencies"):
            chunk = [ln]
            for j in range(i + 1, min(i + 8, len(lines))):
                nxt = lines[j]
                if len(nxt) > 200:
                    break
                if re.match(r"^(experience|education|projects?|work)\b", nxt.lower()):
                    break
                chunk.append(nxt)
            joined = " ".join(chunk)
            joined = re.sub(r"^\s*skills\s*[:\-]\s*", "", joined, flags=re.I)
            if len(joined) > 15:
                return joined
    # Fallback: first substantial line with commas (often a skill list)
    for ln in lines[:40]:
        if "," in ln and 10 < len(ln) < 400 and not ln.lower().startswith("http"):
            return ln
    return None
