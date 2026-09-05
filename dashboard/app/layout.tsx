import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Satellit",
  description: "Wochenzettel für das Core-Satellite-Depot",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <head>
        {/* Über <link> statt next/font: der Container-Build soll nicht daran scheitern,
            wenn Google Fonts vom Server aus nicht erreichbar ist. Die Fallback-Stacks
            in tailwind.config.ts tragen die Seite dann allein. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Spectral:wght@500;600&display=swap"
        />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">{children}</body>
    </html>
  );
}
