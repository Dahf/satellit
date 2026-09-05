import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1.5rem", screens: { "2xl": "1400px" } },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        rail: "hsl(var(--rail))",
        // Handlungssignale — gesättigte Farbe gibt es auf dieser Seite nur hier.
        kaufen: { DEFAULT: "var(--kaufen)", weich: "var(--kaufen-weich)" },
        verkauf: { DEFAULT: "var(--verkauf)", weich: "var(--verkauf-weich)" },
        achtung: { DEFAULT: "var(--achtung)", weich: "var(--achtung-weich)" },
        neutral: { DEFAULT: "var(--neutral)", weich: "var(--neutral-weich)" },
      },
      fontFamily: {
        // Spectral trägt die Stimme der Seite, Archivo die Bedienung, Plex Mono die Daten
        // und die Regel-Fundstellen.
        display: ['Spectral', 'Georgia', 'Times New Roman', 'serif'],
        sans: ['Archivo', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      fontSize: {
        // Ein knapper, bewusst gesetzter Maßstab statt der vollen Tailwind-Leiter.
        marginalie: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.08em" }],
        etikett: ["0.75rem", { lineHeight: "1.1rem", letterSpacing: "0.04em" }],
        lauftext: ["0.9375rem", { lineHeight: "1.5rem" }],
        ansage: ["1.0625rem", { lineHeight: "1.55rem" }],
        titel: ["clamp(1.75rem, 1.2rem + 2.2vw, 2.75rem)", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
