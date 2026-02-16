"""V4 report section: verification cost summary."""

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from refcheck.models.verification import VerificationResult

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

logger = logging.getLogger(__name__)


def add_cost_section(
    doc: "DocxDocument",
    verifications: list[VerificationResult],
) -> None:
    """Add verification cost and tier resolution statistics to report."""
    if not verifications:
        return

    doc.add_heading("Verification Statistics (V4 Multi-Model)", level=2)

    # Tier resolution stats
    tier_counts: dict[int, int] = defaultdict(int)
    total_models = 0
    consensus_counts: dict[str, int] = defaultdict(int)

    for v in verifications:
        tier_counts[v.final_tier] += 1
        total_models += v.total_models_consulted
        if v.consensus_type:
            consensus_counts[v.consensus_type] += 1

    total = len(verifications)
    doc.add_paragraph(f"Total verifications: {total}")
    doc.add_paragraph(f"Total model calls: {total_models}")

    # Tier resolution breakdown
    doc.add_heading("Tier Resolution", level=3)
    for tier in sorted(tier_counts.keys()):
        count = tier_counts[tier]
        pct = (count / total * 100) if total > 0 else 0
        doc.add_paragraph(
            f"Tier {tier}: {count} ({pct:.1f}%)",
            style="List Bullet",
        )

    # Consensus types
    if consensus_counts:
        doc.add_heading("Consensus Types", level=3)
        for ctype, count in sorted(
            consensus_counts.items(), key=lambda x: -x[1],
        ):
            doc.add_paragraph(
                f"{ctype}: {count}", style="List Bullet",
            )

    # Escalation summary
    escalated = sum(1 for v in verifications if len(v.escalation_path) > 1)
    doc.add_paragraph(
        f"Escalated claims: {escalated} ({escalated/total*100:.1f}% of total)"
        if total > 0 else "No claims to summarize",
    )
