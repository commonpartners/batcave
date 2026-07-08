import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const CH_NUMBER_RE = /^\d{8}$|^[A-Z]{2}\d{6}$/;

/**
 * Intake stub (spec 02 §7 / 05 §1): pastes of company names/numbers land
 * here. This writes directly to `companies` with lifecycle='discovered' so
 * they show up for the next refresh/enrich/score run; a Python CLI
 * (`cp_workers.connectors.companies_house.intake_from_csv`, Agent A) is
 * expected to hit the same table eventually and do the real CH-number
 * resolution for name-only rows. For now, name-only rows get a placeholder
 * `PENDING-*` company_number since that column is NOT NULL UNIQUE and we
 * have no CH lookup available server-side in this app.
 */
export async function POST(request: Request) {
  const supabase = createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not authenticated." }, { status: 401 });
  }

  const body = await request.json().catch(() => null);
  const text = typeof body?.text === "string" ? body.text : "";
  const lines = text
    .split("\n")
    .map((l: string) => l.trim())
    .filter(Boolean);

  if (lines.length === 0) {
    return NextResponse.json({ error: "No rows provided." }, { status: 400 });
  }

  let count = 0;
  const errors: string[] = [];

  for (const line of lines) {
    const isNumber = CH_NUMBER_RE.test(line.toUpperCase());
    const company_number = isNumber
      ? line.toUpperCase()
      : `PENDING-${line.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40)}`;
    const legal_name = isNumber ? line.toUpperCase() : line;

    const { error } = await supabase
      .from("companies")
      .upsert([{ company_number, legal_name, lifecycle: "discovered" }], {
        onConflict: "company_number",
        ignoreDuplicates: true,
      });

    if (error) {
      errors.push(`${line}: ${error.message}`);
    } else {
      count += 1;
    }
  }

  return NextResponse.json({ count, errors });
}
