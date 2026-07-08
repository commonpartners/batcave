import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { isAllowlisted } from "@/lib/allowlist";

/**
 * Magic-link callback. Exchanges the auth code for a session, then enforces
 * the reviewer allowlist server-side: any address not in
 * NEXT_PUBLIC_ALLOWLISTED_EMAILS is signed straight back out and redirected
 * to an error page, even though Supabase already issued a valid session.
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/";

  if (code) {
    const supabase = createClient();
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);

    if (!error) {
      const email = data.user?.email;
      if (!isAllowlisted(email)) {
        await supabase.auth.signOut();
        return NextResponse.redirect(`${origin}/auth/auth-code-error?reason=not-allowlisted`);
      }
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(`${origin}/auth/auth-code-error`);
}
