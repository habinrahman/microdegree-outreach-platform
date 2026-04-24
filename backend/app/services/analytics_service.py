"""Analytics / scoring utilities used by targeting + dashboards."""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.email_campaign import EmailCampaign


def compute_hr_scores(db: Session, hr_ids: Optional[Iterable[object]] = None) -> dict:
    """
    HR scoring system (bounce + reply quality).

    Implements the formula requested in the phase-2 spec:
      score = (replies / sent) * 100 - (bounces * 20)
    where:
      sent = count(EmailCampaign.id)
      replies = sum(case((EmailCampaign.reply_status != None, 1), else_=0))
      bounces = sum(case((EmailCampaign.delivery_status == "FAILED", 1), else_=0))
    """
    hr_query = db.query(
        EmailCampaign.hr_id,
        func.count(EmailCampaign.id).label("sent"),
        func.sum(case((EmailCampaign.reply_status.isnot(None), 1), else_=0)).label("replies"),
        func.sum(case((EmailCampaign.delivery_status == "FAILED", 1), else_=0)).label("bounces"),
    ).group_by(EmailCampaign.hr_id)

    if hr_ids is not None:
        id_list = list(hr_ids)
        if not id_list:
            return {}
        hr_query = hr_query.filter(EmailCampaign.hr_id.in_(id_list))

    hr_stats = hr_query.all()

    scores: dict = {}
    for h in hr_stats:
        sent = int(getattr(h, "sent", 0) or 0)
        replies = int(getattr(h, "replies", 0) or 0)
        bounces = int(getattr(h, "bounces", 0) or 0)

        score = 0.0
        if sent > 0:
            score += (replies / sent) * 100
        score -= bounces * 20
        scores[getattr(h, "hr_id")] = round(score, 2)

    return scores

