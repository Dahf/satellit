import "server-only";
import fs from "node:fs";
import path from "node:path";

// Spiegel der Dataclasses aus satellit/decisions.py und satellit/view.py.
// Die Oberfläche leitet nichts mehr selbst ab — sie zeigt an, was dort entschieden wurde.

export const DATA_DIR = process.env.DATA_DIR || "/data";

export type Verdikt =
  | "KAUFEN" | "VERKAUFEN" | "HALTEN" | "STOP_ANHEBEN"
  | "NACHKAUFEN" | "WARTEN" | "NICHT_KAUFEN" | "PRUEFEN";

export interface Beleg {
  label: string;
  wert: string;
  erfuellt: boolean | null;
  regel: string;
}

export interface ChartSpec {
  typ: string;
  punkte: { d: string; kurs: number | null; sma10w: number | null }[];
  linien: { y: number | null; label: string; ton: string }[];
  hinweis: string;
}

export interface Feld {
  name: string;
  label: string;
  /** "mehrzeilig" ist Fließtext (Geschäftsmodell, Kill-Kriterien), nicht Zahleneingabe. */
  typ: "dezimal" | "ganzzahl" | "datum" | "text" | "mehrzeilig";
  wert: string | number | null;
  pflicht: boolean;
  /** Nicht leer -> Auswahlliste statt freier Eingabe. */
  auswahl?: string[];
  hinweis?: string;
}

export interface AktionSpec {
  aktion: string;
  label: string;
  felder: Feld[];
  body: Record<string, unknown>;
  bestaetigung: string;
}

export interface Entscheidung {
  schluessel: string;
  art: string;
  topf: string;
  verdikt: Verdikt;
  verdikt_label: string;
  dringlichkeit: number;
  begruendung: string;
  symbol: string;
  isin: string;
  name: string;
  region: string | null;
  waehrung: string | null;
  sektor: string | null;
  hinweise: string[];
  belege: Beleg[];
  regeln: string[];
  chart: ChartSpec | null;
  stueck: number | null;
  betrag_eur: number | null;
  limit_kurs: number | null;
  stop_kurs: number | null;
  neuer_stop: number | null;
  kurs: number | null;
  wert_eur: number | null;
  einstand_eur: number | null;
  gewinn_eur: number | null;
  gewinn_pct: number | null;
  ampel: string | null;
  ampel_label: string | null;
  aktion: AktionSpec | null;
  gesperrt_weil: string | null;
}

export interface Ampel {
  region: string;
  raw: string | null;
  effective: string | null;
  label: string;
  uptrend: number | null;
  breadth: number | null;
  p200: number | null;
  p50: number | null;
  idx_above: boolean | null;
  note: string;
}

export interface EtfEintrag {
  isin: string;
  symbol: string;
  name: string;
  index: string;
  ter: number;
  ertrag: string;
  gruppe: string;
  hinweis?: string;
}

export interface Monat {
  monat: string;
  plan_eur: number | null;
  ausgegeben_eur: number;
  offen_eur: number | null;
  posten: { datum: string; typ: string; symbol: string; betrag_eur: number }[];
}

export interface Gewinn {
  eingezahlt_netto_eur: number;
  wert_eur: number;
  gewinn_eur: number;
  gewinn_pct: number | null;
  unrealisiert_eur: number;
  xirr_pct: number | null;
  xirr_hinweis: string;
}

export interface Band {
  status: "ok" | "unter" | "ueber" | "unbekannt";
  anteil: number | null;
  low: number;
  high: number;
  ziel: number;
}

/** Kopfdaten des letzten Kern-Scans. Er läuft eigenständig und selten (Fundamentaldaten je
 *  Titel), deshalb gehört sein Datum sichtbar dazu — sonst wirkt die Liste tagesaktuell. */
export interface KernScan {
  gelaufen: boolean;
  as_of?: string;
  quelle?: "universum" | "watchlist" | "demo" | string;
  geprueft?: number;
  vorgefiltert?: number;
  trichter?: Record<string, number>;
  hinweise?: string[];
  /** Gesetzt, wenn der Lauf gescheitert ist statt nichts gefunden zu haben. Die beiden
   *  müssen sich unterscheiden: „nichts geprüft" ist kein gültiges Prüfergebnis. */
  fehler?: string | null;
  demo?: boolean;
  watchlist: number;
}

export interface View {
  schema: number;
  as_of: string;
  erzeugt: string;
  demo: boolean;
  onboarding_noetig: boolean | null;
  portfolio: {
    satellit_eur: number | null;
    gebunden_eur: number | null;
    cash_eur: number | null;
    cash_je_topf: Record<string, number>;
    hoch_eur: number | null;
    drawdown: number | null;
    positionen: { offen: number; max: number };
    offenes_risiko_pct: number | null;
    offenes_risiko_max_pct: number | null;
    kern_eur: number | null;
    kern_etf_eur: number | null;
    kern_aktien_eur: number | null;
    kern_aktien_cash_eur: number | null;
    gesamt_eur: number | null;
    kern_pct: number | null;
    satellit_pct: number | null;
    band: Partial<Band>;
    kauffenster: { offen?: boolean; grund?: string; naechstes?: string | null };
  };
  monat: Monat | null;
  gewinn: Gewinn | null;
  sparplan: { tag: number; offen: boolean; rate_eur: number } | null;
  etf: { isin?: string; symbol?: string; name?: string; anteil_kern?: number } | null;
  etf_katalog: EtfEintrag[];
  ampel: Record<string, Ampel>;
  entscheidungen: Entscheidung[];
  /** Geprüfte Kern-Aktien aus dem letzten Kern-Scan — Vorschläge, kein Bestand. */
  kern_kandidaten: Entscheidung[];
  kern_scan: KernScan;
  abgelehnt: Entscheidung[];
  screener_trichter: Record<string, number>;
  sperren: {
    kill_switch: { aktiv: boolean; grund: string };
    trockenlauf: { aktiv: boolean; bis: string | null };
  };
  daten: {
    fx: { kurse: Record<string, number>; quelle: string };
    universum: Record<string, { quelle: string | null; alter_tage: number | null; anzahl: number; ok: boolean }>;
    universum_warnungen: string[];
    fehlende_symbole: Record<string, string>;
    hinweise: string[];
    kurse_alter_tage: number | null;
    letzter_lauf: string;
    bericht: string | null;
  };
}

// Wort UND Zeichen — nie nur Farbe. Der Ausdruck und Farbfehlsichtigkeit sollen es tragen.
export const VERDIKT: Record<Verdikt, { ton: "kaufen" | "verkauf" | "achtung" | "neutral"; zeichen: string }> = {
  KAUFEN: { ton: "kaufen", zeichen: "▲" },
  NACHKAUFEN: { ton: "kaufen", zeichen: "＋" },
  VERKAUFEN: { ton: "verkauf", zeichen: "▼" },
  STOP_ANHEBEN: { ton: "achtung", zeichen: "↑" },
  PRUEFEN: { ton: "achtung", zeichen: "?" },
  HALTEN: { ton: "neutral", zeichen: "•" },
  WARTEN: { ton: "neutral", zeichen: "⏸" },
  NICHT_KAUFEN: { ton: "neutral", zeichen: "–" },
};

/** "Trading-Plan 5.2" -> "TP 5.2" für die schmale Regel-Spalte. */
export function regelKurz(regel: string): string {
  return regel
    .replace(/^Trading-Plan\s*/i, "TP ")
    .replace(/^KERN\.md\s*/i, "Kern ")
    .replace(/^Leitsatz\s*/i, "LS ")
    .trim();
}

export function getView(): View | null {
  const datei = path.join(DATA_DIR, "view_latest.json");
  try {
    return JSON.parse(fs.readFileSync(datei, "utf-8")) as View;
  } catch {
    return null;
  }
}

/**
 * Laufstatus des Kern-Scans — eigener Zweig in derselben Datei.
 *
 * Beide Läufe schreiben `run_status.json`; flach nebeneinander würden `ok`, `error` und
 * `finished` einander überschreiben und die Oberfläche behauptete nach einem Kern-Scan
 * etwas über den letzten Wochenlauf.
 */
export interface KernLauf {
  running?: boolean;
  ok?: boolean | null;
  error?: string | null;
  started?: string;
  finished?: string;
  geprueft?: number;
  bestanden?: number;
  demo?: boolean;
  fortschritt?: { geprueft: number; gesamt: number } | null;
}

export interface Laufstatus {
  running?: boolean;
  ok?: boolean;
  error?: string | null;
  finished?: string;
  fortschritt?: { geladen: number; gesamt: number } | null;
  kern?: KernLauf;
}

export function getLaufstatus(): Laufstatus {
  try {
    return JSON.parse(fs.readFileSync(path.join(DATA_DIR, "run_status.json"), "utf-8")) as Laufstatus;
  } catch {
    return {};
  }
}
