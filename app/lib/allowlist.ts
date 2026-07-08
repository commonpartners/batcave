/**
 * Reads the allowlisted reviewer emails from NEXT_PUBLIC_ALLOWLISTED_EMAILS
 * (comma-separated). Sign-in attempts from any other address are rejected
 * at the /auth/callback route.
 */
export function getAllowlistedEmails(): string[] {
  const raw = process.env.NEXT_PUBLIC_ALLOWLISTED_EMAILS ?? "";
  return raw
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
}

export function isAllowlisted(email: string | null | undefined): boolean {
  if (!email) return false;
  return getAllowlistedEmails().includes(email.trim().toLowerCase());
}

/** Maps an allowlisted email to the `decided_by` enum used by `decisions`. */
export function decidedByFromEmail(email: string | null | undefined): "julia" | "ben" {
  if (email?.toLowerCase().startsWith("julia")) return "julia";
  return "ben";
}
