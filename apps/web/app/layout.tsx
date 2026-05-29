import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "GuardianOps AI",
  description: "Plateforme d'audit permanent SI, monitoring et sécurité.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr" className="dark">
      <body className="min-h-screen bg-guardian-bg text-slate-100 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
