export default function AuthCodeErrorPage({
  searchParams,
}: {
  searchParams: { reason?: string };
}) {
  const notAllowlisted = searchParams.reason === "not-allowlisted";

  return (
    <div className="flex min-h-[70vh] items-center justify-center text-center">
      <div className="max-w-sm space-y-2">
        <h1 className="text-lg font-semibold">Sign-in failed</h1>
        <p className="text-sm text-muted-foreground">
          {notAllowlisted
            ? "That email address isn't on the reviewer allowlist for this tool. Ask Julia or Ben to check NEXT_PUBLIC_ALLOWLISTED_EMAILS."
            : "The sign-in link was invalid or expired. Request a new magic link and try again."}
        </p>
        <a href="/login" className="text-sm underline">
          Back to sign in
        </a>
      </div>
    </div>
  );
}
