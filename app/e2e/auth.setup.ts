import { test as setup } from "@playwright/test";
import { createClient } from "@supabase/supabase-js";

const authFile = "e2e/.auth/user.json";

/**
 * Signs a real reviewer in against a live (test) Supabase project so the
 * rest of the suite runs authenticated, without a human clicking an email
 * link: `admin.generateLink` mints a real magic-link action_link, we
 * navigate the browser straight to it, and the app's own
 * /auth/callback route handler does the normal PKCE code exchange and sets
 * the session cookies exactly as it would for Julia or Ben in production.
 *
 * Requires SUPABASE_SERVICE_ROLE_KEY (test project) in the environment -
 * this is a test-only secret and must never point at the production
 * project.
 */
setup("authenticate as allowlisted reviewer", async ({ page, baseURL }) => {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const email = (process.env.NEXT_PUBLIC_ALLOWLISTED_EMAILS ?? "julia@thebothy.club").split(",")[0].trim();

  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error(
      "auth.setup.ts requires NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY for a test Supabase project."
    );
  }

  const admin = createClient(supabaseUrl, serviceRoleKey);
  const { data, error } = await admin.auth.admin.generateLink({
    type: "magiclink",
    email,
    options: { redirectTo: `${baseURL}/auth/callback` },
  });

  if (error || !data?.properties?.action_link) {
    throw error ?? new Error("generateLink returned no action_link");
  }

  await page.goto(data.properties.action_link);
  await page.waitForURL(`${baseURL}/`);
  await page.context().storageState({ path: authFile });
});
