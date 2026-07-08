import type { Metadata } from "next";
import "./globals.css";
import { createClient } from "@/lib/supabase/server";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "Common Partners — Deal Review",
  description: "Ranked acquisition shortlist review tool for Common Partners.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        {user && <Nav email={user.email} />}
        <main className="container py-4 pb-24 sm:pb-6">{children}</main>
      </body>
    </html>
  );
}
