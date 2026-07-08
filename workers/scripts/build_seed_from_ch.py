"""One-off script: pull real candidate companies from the Companies House
advanced-search API, screen them through the same taxonomy + universe filters
the discovery pipeline uses (cp_workers.connectors.discovery), keep only
smaller filers (exclude anything that already files medium/large/group
accounts — a proxy for "not a huge company"), and write out a real,
CH-verified seed list.

Not part of the cp_workers package/CLI surface — a throwaway build-time tool.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cp_workers import db
from cp_workers.connectors.companies_house import CompaniesHouseClient
from cp_workers.connectors.discovery import (
    _fetch_taxonomy_rules,
    is_taxonomy_candidate,
    passes_universe_filters,
)

TARGET_COUNT = 30

# CH profile accounts.last_accounts.type / accounts.next_accounts.type values
# that indicate a small filer — excludes 'group'/'full'/'medium' filing
# categories so we don't re-pull something Neal's-Yard-sized.
ACCEPTABLE_ACCOUNTS_TYPES = {
    "micro-entity", "micro entity", "small", "dormant", "total-exemption-small",
    "total-exemption-full", "unaudited-abridged", "abbreviated", "unaudited",
}

# Service-business words that show up in SIC 86900/96020/generic-retail hits
# but are not a skincare/personal-care product brand. Broad monthly discovery
# deliberately doesn't filter these (spec 02 §3 casts a wide net), but a
# hand-picked Phase 0 list should not include them.
SERVICE_EXCLUDE_WORDS = (
    "salon", "clinic", "physiotherapy", "physio", "rehab", "dairy", "dairies",
    "care homes", "nursing", "dental", "chiropractic", "barber", "spa hotel",
    "trading", "convenience", "supply", "wholesale", "developments", "homes",
)

# Searched in priority order: genuine cosmetics/toiletries codes first, the
# noisy generic-retail/service codes last (spec 02 §2 — those need the
# hardest keyword filtering, so give the clean codes first crack at the quota).
SIC_PRIORITY = ["20420", "20411", "20412", "46450", "47750", "47910", "47190", "47990", "96020", "86900"]


def _has_real_keyword_signal(name: str, taxonomy_rules: list[dict]) -> bool:
    """Require an actual include-keyword hit in the name (not just a bare SIC
    match) and no generic-service-business words — SIC 86900/96020/47xxx are
    noisy on their own (spec 02 §2 flags 86900 as needing hard keyword
    filtering); this is that filter, applied for seed-list quality."""
    text = name.lower()
    if any(word in text for word in SERVICE_EXCLUDE_WORDS):
        return False
    for rule in taxonomy_rules:
        if any(kw.lower() in text for kw in (rule.get("include_keywords") or [])):
            return True
    return False


def main() -> None:
    taxonomy_rules = _fetch_taxonomy_rules()
    all_sic_codes = {c for rule in taxonomy_rules for c in (rule.get("sic_codes") or [])}
    ordered_sic_codes = [c for c in SIC_PRIORITY if c in all_sic_codes] + sorted(
        all_sic_codes - set(SIC_PRIORITY)
    )
    min_age_years = int(db.get_config("min_company_age_years", 8))
    today = date.today()
    incorp_to = today.replace(year=today.year - min_age_years).isoformat()

    client = CompaniesHouseClient()
    seen: dict[str, dict] = {}
    accepted: list[dict] = []

    try:
        page_size = 100
        max_pages_per_code = 8
        for sic_code in ordered_sic_codes:
            if len(accepted) >= TARGET_COUNT:
                break
            start_index = 0
            for _page in range(max_pages_per_code):
                if len(accepted) >= TARGET_COUNT:
                    break
                result = client.advanced_search(
                    sic_codes=[sic_code],
                    status="active",
                    incorp_to=incorp_to,
                    start_index=start_index,
                    size=page_size,
                )
                items = result.get("items") or []
                if not items:
                    break
                start_index += page_size

                for item in items:
                    number = item.get("company_number")
                    name = item.get("company_name") or ""
                    if not number or number in seen:
                        continue
                    seen[number] = item

                    incorp_raw = item.get("date_of_creation")
                    incorp_date = None
                    if incorp_raw:
                        try:
                            incorp_date = date.fromisoformat(incorp_raw)
                        except ValueError:
                            pass

                    ch_sic_codes = item.get("sic_codes") or []
                    if not is_taxonomy_candidate(name, ch_sic_codes, taxonomy_rules):
                        continue
                    if not _has_real_keyword_signal(name, taxonomy_rules):
                        continue

                    ok, _reason = passes_universe_filters(
                        status=item.get("company_status"),
                        incorporation_date=incorp_date,
                        name=name,
                        min_age_years=min_age_years,
                        taxonomy_rules=taxonomy_rules,
                        today=today,
                    )
                    if not ok:
                        continue

                    # Screen out large filers via the full profile's accounts type.
                    try:
                        profile = client.get_profile(number)
                    except Exception:
                        continue
                    accounts = profile.get("accounts") or {}
                    accounts_type = (accounts.get("last_accounts") or {}).get("type") or (
                        accounts.get("next_accounts") or {}
                    ).get("type")
                    if accounts_type and accounts_type.lower() not in ACCEPTABLE_ACCOUNTS_TYPES:
                        print(f"skip {number} {name!r}: accounts type {accounts_type!r} too large")
                        continue

                    accepted.append(
                        {
                            "company_number": number,
                            "name": name,
                            "incorporation_date": incorp_raw,
                            "accounts_type": accounts_type,
                            "sic_codes": ";".join(ch_sic_codes),
                        }
                    )
                    print(f"accept {number} {name!r} (sic={sic_code}, accounts_type={accounts_type})")
                    if len(accepted) >= TARGET_COUNT:
                        break
                time.sleep(0.2)
    finally:
        client.close()

    out_path = Path(__file__).resolve().parents[1] / "seed.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["company_number", "name", "incorporation_date", "accounts_type", "sic_codes"]
        )
        writer.writeheader()
        writer.writerows(accepted)

    print(f"\nWrote {len(accepted)} CH-verified candidates to {out_path}")


if __name__ == "__main__":
    main()
