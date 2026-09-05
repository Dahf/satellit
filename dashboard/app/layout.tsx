import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "Satellit",
  description: "Core-Satellite Trading-Dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <body className="min-h-screen font-sans antialiased">
        <header className="border-b bg-background/95 backdrop-blur">
          <div className="container flex h-14 items-center gap-6">
            <span className="text-base font-semibold tracking-tight">🛰️ Satellit</span>
            <Nav />
          </div>
        </header>
        <main className="container py-6">{children}</main>
        <footer className="container py-6 text-xs text-muted-foreground">
          Regelwerk: docs/TRADING_PLAN.md · Keine Anlageberatung.
        </footer>
      </body>
    </html>
  );
}
