"""Distribution footprint (spec 03 §6).

`notable_stockists` comes from §1 LLM extraction (stockists mentioned on the
website) cross-checked against retailer stockist scrapes (spec 02 §8, owned by
Agent A's sourcing pipeline); `marketplace_presence` comes from an Amazon UK
storefront search by brand name (presence + review count only). This module
just turns those two facts into the single `distribution_breadth` 0-1 figure
consumed by the latent-upside signals and the scoring engine.
"""
from __future__ import annotations

from typing import Any

# Above this many notable stockists, distribution is considered "broad" and the
# stockist term of the score saturates at 1.0.
_BROAD_STOCKIST_COUNT = 6


def distribution_breadth(
    notable_stockists: list[str] | None,
    marketplace_presence: dict[str, Any] | bool | None,
) -> float:
    """0-1 breadth score blending stockist count and marketplace presence.

    Never raises: missing/None inputs are treated as "no distribution evidence
    found" (0.0 contribution), not an error — distribution evidence is often
    genuinely absent for small brands, and that itself is signal (see
    `signals.latent_upside.narrow_distribution`).
    """
    stockists = notable_stockists or []
    stockist_count = len([s for s in stockists if s])
    stockist_score = min(1.0, stockist_count / _BROAD_STOCKIST_COUNT)

    if isinstance(marketplace_presence, dict):
        has_marketplace = bool(marketplace_presence.get("present"))
        review_count = marketplace_presence.get("review_count") or 0
        # A storefront with meaningful review volume counts for more than a bare listing.
        marketplace_score = 1.0 if has_marketplace and review_count >= 20 else (0.6 if has_marketplace else 0.0)
    else:
        marketplace_score = 1.0 if marketplace_presence else 0.0

    # Weighted blend: stockists matter more than a single marketplace channel.
    breadth = 0.7 * stockist_score + 0.3 * marketplace_score
    return max(0.0, min(1.0, breadth))
