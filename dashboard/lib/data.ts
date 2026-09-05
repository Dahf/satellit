import "server-only";
import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import Papa from "papaparse";

// Alle Daten kommen aus dem state/-Volume der Python-Pipeline (read-only gemountet).
export const DATA_DIR = process.env.DATA_DIR || "/data";

// ----------------------------------------------------------------------------- Typen
export type AmpelState = "GREEN" | "YELLOW" | "RED" | null;

export interface Reading {
  date: string;
  region: string;
  raw: AmpelState;
  effective: AmpelState;
  uptrend?: number | null;
  breadth?: number | null;
  p200?: number | null;
  p50?: number | null;
  idx_above?: boolean | null;
  note?: string;
}

export interface Proposal {
  symbol: string;
  isin: string;
  name: string;
  region: string;
  currency: string;
  sector: string;
  close: number;
  breakout_level: number;
  initial_stop: number;
  atr: number;
  rs_rank_pct: number;
  shares: number;
  value_eur: number;
  risk_eur: number;
  risk_pct: number;
  limit_price: number;
  ampel: string;
}

export interface PositionView {
  thesis_id: string;
  symbol: string;
  name: string;
  region: string;
  currency: string;
  sector: string;
  shares: number;
  entry: number;
  entry_date: string;
  stop: number;
  close: number | null;
  week_low: number | null;
  new_stop: number | null;
  stop_raised: boolean;
  soft_exit: boolean;
  hard_stop_hit: boolean;
  pnl_pct: number | null;
  open_risk_eur: number;
  note?: string;
}

export interface Weekly {
  as_of: string;
  readings: Record<string, Reading>;
  kill_active: boolean;
  dry_run: boolean;
  proposals: Proposal[];
  positions: PositionView[];
  data_failed: Record<string, string>;
  notes: string[];
}

export interface Account {
  satellite_equity_eur: number | null;
  updated: string | null;
  high_water_mark: number | null;
  kill_switch_active: boolean;
  kill_switch_reason: string;
  dry_run_until: string | null;
}

export interface RunStatus {
  running?: boolean;
  started?: string;
  finished?: string;
  ok?: boolean;
  error?: string | null;
  as_of?: string;
  report?: string;
  pushed?: boolean;
  candidates?: number;
  failed_symbols?: number;
  demo?: boolean;
  updated?: string;
}

export interface ScreenerRow {
  region: string;
  symbol: string;
  isin: string;
  name: string;
  sector: string;
  currency: string;
  last_date: string;
  close: number | null;
  close_eur: number | null;
  sma50: number | null;
  sma200: number | null;
  trend_ok: boolean;
  rs_score: number | null;
  rs_rank_pct: number | null;
  rs_top: boolean;
  weekly_close: number | null;
  breakout_level: number | null;
  extension: number | null;
  breakout: boolean;
  atr: number | null;
  atr_pct: number | null;
  initial_stop: number | null;
  avg_turnover_eur: number | null;
  liquidity_ok: boolean;
  vol_ok: boolean;
  price_ok: boolean;
  target_value_eur: number | null;
  candidate: boolean;
  watchlist: boolean;
  reason: string;
}

export interface Thesis {
  id: string;
  ticker: string;
  symbol: string;
  name: string;
  status: string;
  setup_type: string | null;
  thesis_type: string | null;
  created_at: string;
  updated_at: string;
  region: string | null;
  currency: string | null;
  sector: string | null;
  ampel: string | null;
  statement: string;
  entry_price: number | null;
  entry_date: string | null;
  shares: number | null;
  stop: number | null;
  initial_stop: number | null;
  exit_price: number | null;
  exit_date: string | null;
  exit_reason: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  r: number | null;
  next_review: string | null;
  stop_ledger: Array<{ date: string; old: number | null; new: number; note: string }>;
  raw: any;
}

export interface Stats {
  closed: number;
  wins: number;
  losses: number;
  winRate: number | null;
  avgR: number | null;
  profitFactor: number | null;
  sumPnl: number;
  best: Thesis | null;
  worst: Thesis | null;
}

// ----------------------------------------------------------------------------- Helfer
function p(...parts: string[]): string {
  return path.join(DATA_DIR, ...parts);
}

function exists(file: string): boolean {
  try {
    return fs.existsSync(file);
  } catch {
    return false;
  }
}

function readJson<T>(file: string): T | null {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8")) as T;
  } catch {
    return null;
  }
}

function listFiles(dir: string, prefix: string, ext: string): string[] {
  if (!exists(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => f.startsWith(prefix) && f.endsWith(ext))
    .sort();
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function bool(v: unknown): boolean {
  if (typeof v === "boolean") return v;
  const s = String(v ?? "").toLowerCase();
  return s === "true" || s === "1";
}

// ----------------------------------------------------------------------------- Status & Konto
export function getRunStatus(): RunStatus {
  return readJson<RunStatus>(p("run_status.json")) ?? {};
}

export function getAccount(): Account {
  const file = p("account.yaml");
  const fallback: Account = {
    satellite_equity_eur: null,
    updated: null,
    high_water_mark: null,
    kill_switch_active: false,
    kill_switch_reason: "",
    dry_run_until: null,
  };
  if (!exists(file)) return fallback;
  try {
    const doc = yaml.load(fs.readFileSync(file, "utf-8")) as Partial<Account>;
    return { ...fallback, ...doc };
  } catch {
    return fallback;
  }
}

export function drawdown(acc: Account): number | null {
  if (!acc.satellite_equity_eur || !acc.high_water_mark) return null;
  return 1 - acc.satellite_equity_eur / acc.high_water_mark;
}

// ----------------------------------------------------------------------------- Wochenlauf
export function listWeeklyDates(): string[] {
  return listFiles(p("reports"), "weekly_", ".json").map((f) => f.slice("weekly_".length, -".json".length));
}

export function getWeekly(asOf?: string): Weekly | null {
  const dates = listWeeklyDates();
  if (dates.length === 0) return null;
  const date = asOf && dates.includes(asOf) ? asOf : dates[dates.length - 1];
  return readJson<Weekly>(p("reports", `weekly_${date}.json`));
}

export function getWeeklyMarkdown(asOf: string): string | null {
  const file = p("reports", `weekly_${asOf}.md`);
  return exists(file) ? fs.readFileSync(file, "utf-8") : null;
}

// ----------------------------------------------------------------------------- Ampel-Historie
export function getAmpelHistory(): Reading[] {
  const file = p("regime", "ampel_history.csv");
  if (!exists(file)) return [];
  const parsed = Papa.parse<Record<string, string>>(fs.readFileSync(file, "utf-8"), { header: true, skipEmptyLines: true });
  return parsed.data
    .map((r) => ({
      date: r.date,
      region: r.region,
      raw: (r.raw || null) as AmpelState,
      effective: (r.effective || null) as AmpelState,
      uptrend: num(r.uptrend),
      breadth: num(r.breadth),
      p200: num(r.p200),
      p50: num(r.p50),
      idx_above: r.idx_above === "" ? null : bool(r.idx_above),
      note: r.note,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ----------------------------------------------------------------------------- Screener
export function getScreener(asOf?: string): { asOf: string | null; rows: ScreenerRow[] } {
  const files = listFiles(p("reports"), "screener_", ".csv");
  if (files.length === 0) return { asOf: null, rows: [] };
  const wanted = asOf ? `screener_${asOf}.csv` : files[files.length - 1];
  const file = files.includes(wanted) ? wanted : files[files.length - 1];
  const parsed = Papa.parse<Record<string, string>>(fs.readFileSync(p("reports", file), "utf-8"), {
    header: true,
    skipEmptyLines: true,
  });
  const rows: ScreenerRow[] = parsed.data.map((r) => ({
    region: r.region,
    symbol: r.symbol,
    isin: r.isin,
    name: r.name,
    sector: r.sector,
    currency: r.currency,
    last_date: r.last_date,
    close: num(r.close),
    close_eur: num(r.close_eur),
    sma50: num(r.sma50),
    sma200: num(r.sma200),
    trend_ok: bool(r.trend_ok),
    rs_score: num(r.rs_score),
    rs_rank_pct: num(r.rs_rank_pct),
    rs_top: bool(r.rs_top),
    weekly_close: num(r.weekly_close),
    breakout_level: num(r.breakout_level),
    extension: num(r.extension),
    breakout: bool(r.breakout),
    atr: num(r.atr),
    atr_pct: num(r.atr_pct),
    initial_stop: num(r.initial_stop),
    avg_turnover_eur: num(r.avg_turnover_eur),
    liquidity_ok: bool(r.liquidity_ok),
    vol_ok: bool(r.vol_ok),
    price_ok: bool(r.price_ok),
    target_value_eur: num(r.target_value_eur),
    candidate: bool(r.candidate),
    watchlist: bool(r.watchlist),
    reason: r.reason,
  }));
  return { asOf: file.slice("screener_".length, -".csv".length), rows };
}

// ----------------------------------------------------------------------------- Journal
function toThesis(doc: any): Thesis {
  const prov = doc?.origin?.raw_provenance ?? {};
  const entry = doc?.entry ?? {};
  const exit = doc?.exit ?? {};
  const pos = doc?.position ?? {};
  const outcome = doc?.outcome ?? {};
  const entryPrice = num(entry.actual_price);
  const shares = num(pos.shares);
  const initialStop = num(prov.initial_stop) ?? num(exit.stop_loss);
  const pnl = num(outcome.pnl_dollars);
  let r: number | null = null;
  if (pnl !== null && entryPrice !== null && initialStop !== null && shares) {
    const risk = (entryPrice - initialStop) * shares;
    r = risk > 0 ? pnl / risk : null;
  } else if (pnl !== null && num(pos.risk_dollars)) {
    r = pnl / (num(pos.risk_dollars) as number);
  }
  return {
    id: doc.thesis_id,
    ticker: doc.ticker,
    symbol: prov.symbol || doc.ticker,
    name: String(doc.thesis_statement || "").split(":")[0],
    status: doc.status,
    setup_type: doc.setup_type ?? null,
    thesis_type: doc.thesis_type ?? null,
    created_at: doc.created_at,
    updated_at: doc.updated_at,
    region: prov.region ?? null,
    currency: prov.currency ?? null,
    sector: doc?.market_context?.sector ?? null,
    ampel: prov.ampel ?? doc?.market_context?.regime ?? null,
    statement: doc.thesis_statement ?? "",
    entry_price: entryPrice,
    entry_date: entry.actual_date ? String(entry.actual_date).slice(0, 10) : null,
    shares,
    stop: num(exit.stop_loss),
    initial_stop: initialStop,
    exit_price: num(exit.actual_price),
    exit_date: exit.actual_date ? String(exit.actual_date).slice(0, 10) : null,
    exit_reason: exit.exit_reason ?? null,
    pnl,
    pnl_pct: num(outcome.pnl_pct),
    r,
    next_review: doc?.monitoring?.next_review_date ?? null,
    stop_ledger: Array.isArray(prov.stop_ledger) ? prov.stop_ledger : [],
    raw: doc,
  };
}

export function getTheses(): Thesis[] {
  const dir = p("theses");
  if (!exists(dir)) return [];
  const out: Thesis[] = [];
  for (const f of fs.readdirSync(dir)) {
    if (!f.startsWith("th_") || !(f.endsWith(".yaml") || f.endsWith(".yml"))) continue;
    try {
      const doc = yaml.load(fs.readFileSync(path.join(dir, f), "utf-8"));
      if (doc && typeof doc === "object") out.push(toThesis(doc));
    } catch {
      // defekte Datei überspringen — die Pipeline validiert beim Schreiben
    }
  }
  return out.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
}

export function getThesis(id: string): Thesis | null {
  return getTheses().find((t) => t.id === id) ?? null;
}

export function isSatellite(t: Thesis): boolean {
  return t.setup_type !== "core_holding";
}

export function computeStats(theses: Thesis[]): Stats {
  const closed = theses.filter((t) => t.status === "CLOSED" && isSatellite(t));
  const withR = closed.filter((t) => t.r !== null);
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0);
  const losses = closed.filter((t) => (t.pnl ?? 0) < 0);
  const sumWin = wins.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const sumLoss = Math.abs(losses.reduce((s, t) => s + (t.pnl ?? 0), 0));
  const avgR = withR.length ? withR.reduce((s, t) => s + (t.r as number), 0) / withR.length : null;
  const sorted = [...closed].sort((a, b) => (b.r ?? 0) - (a.r ?? 0));
  return {
    closed: closed.length,
    wins: wins.length,
    losses: losses.length,
    winRate: closed.length ? wins.length / closed.length : null,
    avgR,
    profitFactor: sumLoss > 0 ? sumWin / sumLoss : sumWin > 0 ? null : null,
    sumPnl: closed.reduce((s, t) => s + (t.pnl ?? 0), 0),
    best: sorted[0] ?? null,
    worst: sorted.length ? sorted[sorted.length - 1] : null,
  };
}

// ----------------------------------------------------------------------------- Digest
export function getLatestDigest(): any | null {
  const files = listFiles(p("reports", "digest"), "weekly_digest_", ".json");
  if (files.length === 0) return null;
  return readJson<any>(p("reports", "digest", files[files.length - 1]));
}
