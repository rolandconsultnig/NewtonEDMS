"""Insurance & Claims Lifecycle & Adjudication Engine."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database import now
from app.models import InsuranceClaim, InsurancePolicy, User

logger = logging.getLogger("newtonedms.insurance.engine")


def adjudicate_claim(
    db: Session,
    claim: InsuranceClaim,
    policy: InsurancePolicy,
    auto_approval_threshold: float = 1500.0,
) -> dict[str, Any]:
    """
    Automated Claims Routing & Adjudication Logic.
    1. Low-Value Auto-Approval: If estimated loss <= threshold and no bodily injury and fraud score < 20.
    2. Severe Loss Routing: If property loss > $50,000, route to Senior Loss Assessor.
    3. Specialized Routing: If bodily injury, route to Medical Injury Unit.
    """
    actions_taken: list[str] = []

    # Check Coverage Limit
    if claim.estimated_loss > (policy.coverage_limit or float("inf")):
        claim.fraud_flags = (claim.fraud_flags or []) + ["Estimated loss exceeds policy coverage limit."]
        actions_taken.append("Exceeds Coverage Limit")

    # Auto-Approval Rule
    is_auto_eligible = (
        claim.estimated_loss <= auto_approval_threshold
        and claim.loss_type != "bodily_injury"
        and (claim.fraud_score or 0) < 20
        and policy.status == "active"
    )

    if is_auto_eligible:
        claim.auto_approved = True
        claim.status = "approved"
        # Settlement equals estimated loss minus deductible
        deductible = float(policy.deductible or 0.0)
        claim.settlement_amount = max(0.0, float(claim.estimated_loss) - deductible)
        actions_taken.append(f"Auto-Approved (Under ${auto_approval_threshold:,.2f} Threshold, Settlement: ${claim.settlement_amount:,.2f})")
    elif claim.loss_type == "bodily_injury":
        claim.status = "under_review"
        actions_taken.append("Routed to Specialized Bodily Injury Adjuster")
    elif claim.estimated_loss >= 50000.0:
        claim.status = "under_review"
        actions_taken.append("Routed to Senior Commercial Loss Assessor")
    else:
        claim.status = "under_review"
        actions_taken.append("Assigned to Standard Claims Queue")

    db.commit()
    db.refresh(claim)

    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "status": claim.status,
        "auto_approved": claim.auto_approved,
        "settlement_amount": claim.settlement_amount,
        "actions": actions_taken,
    }
