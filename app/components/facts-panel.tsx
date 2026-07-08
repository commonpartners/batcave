import type { CompanyDetailRow, MoneyEstimate } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatPence, titleCase } from "@/lib/utils";

function MoneyBadge({ label, estimate }: { label: string; estimate: MoneyEstimate | null }) {
  if (!estimate) {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="text-muted-foreground">—</span>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1.5">
        <span className="font-medium">{formatPence(estimate.value_pence)}</span>
        <Badge variant={estimate.method === "filed" ? "outline" : "warning"}>
          {estimate.method === "filed" ? "filed" : "estimate"}
        </Badge>
        <Badge variant="outline">{estimate.confidence} confidence</Badge>
      </div>
    </div>
  );
}

export function FactsPanel({ company }: { company: CompanyDetailRow }) {
  // Reviews / stockists have no dedicated columns in the schema (spec 01 §1
  // only stores revenue/ebitda estimates + digital_maturity on `companies`);
  // best-effort surface anything relevant from latent_upside signal evidence.
  const upsideSignals = company.signals.filter((s) => s.family === "latent_upside");
  const reviewSignal = upsideSignals.find((s) => s.name === "reviews_strong_digital_weak");
  const distributionSignal = upsideSignals.find((s) => s.name === "narrow_distribution");

  return (
    <div className="space-y-4 text-sm">
      <section className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">Financials</h3>
        <MoneyBadge label="Revenue" estimate={company.revenue_estimate} />
        <MoneyBadge label="EBITDA" estimate={company.ebitda_estimate} />
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Employees</span>
          <span>{company.employee_count ?? "—"}</span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Filing category</span>
          <span>{titleCase(company.filing_category ?? undefined) || "Unknown"}</span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Latest accounts</span>
          <span>{formatDate(company.latest_accounts_date)}</span>
        </div>
      </section>

      <section className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">People</h3>
        {company.people.length === 0 ? (
          <p className="text-muted-foreground">No officer data.</p>
        ) : (
          <ul className="space-y-1">
            {company.people
              .filter((p) => p.is_active)
              .map((p) => (
                <li key={`${p.person_id}-${p.role}-${p.appointed_on}`} className="flex items-center justify-between">
                  <span>
                    {p.name ?? "Unnamed"} <span className="text-muted-foreground">({titleCase(p.role)})</span>
                  </span>
                  <span className="text-muted-foreground">
                    {p.age_years ? `~${p.age_years}y` : ""} {p.tenure_years ? `· ${p.tenure_years.toFixed(1)}y tenure` : ""}
                  </span>
                </li>
              ))}
          </ul>
        )}
      </section>

      <section className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">Digital maturity</h3>
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold">{company.digital_maturity ?? "—"}/5</span>
        </div>
      </section>

      {(reviewSignal || distributionSignal) && (
        <section className="space-y-1.5">
          <h3 className="text-xs font-semibold uppercase text-muted-foreground">Reviews &amp; distribution</h3>
          {reviewSignal && (
            <p className="text-muted-foreground">
              Review strength signal: <span className="font-medium text-foreground">{reviewSignal.value.toFixed(2)}</span>
              {reviewSignal.rationale ? ` — ${reviewSignal.rationale}` : ""}
            </p>
          )}
          {distributionSignal && (
            <p className="text-muted-foreground">
              Distribution breadth signal:{" "}
              <span className="font-medium text-foreground">{distributionSignal.value.toFixed(2)}</span>
              {distributionSignal.rationale ? ` — ${distributionSignal.rationale}` : ""}
            </p>
          )}
        </section>
      )}

      <section className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">Links</h3>
        <ul className="space-y-1">
          <li>
            <a
              className="underline"
              target="_blank"
              rel="noreferrer"
              href={`https://find-and-update.company-information.service.gov.uk/company/${company.company_number}`}
            >
              Companies House
            </a>
          </li>
          {company.website && (
            <li>
              <a className="underline" target="_blank" rel="noreferrer" href={company.website}>
                Website
              </a>
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
