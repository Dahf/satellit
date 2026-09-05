import { NextResponse, type NextRequest } from "next/server";

// Leitet Dashboard-Aktionen an die Python-API weiter (satellit serve, Port 8787 im Compose-Netz).
const ALLOWED: Record<string, string> = {
  "journal.new": "/journal/new",
  "journal.open": "/journal/open",
  "journal.close": "/journal/close",
  "journal.stop": "/journal/stop",
  account: "/account",
  "run.weekly": "/run/weekly",
  "universe.import": "/universe/import",
};

export async function POST(req: NextRequest) {
  const base = process.env.SATELLIT_API_URL || "http://satellit:8787";
  const token = process.env.SATELLIT_API_TOKEN || "";
  let payload: { action?: string; body?: Record<string, unknown> };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "ungültiges JSON" }, { status: 400 });
  }
  const path = payload.action ? ALLOWED[payload.action] : undefined;
  if (!path) return NextResponse.json({ ok: false, error: "unbekannte Aktion" }, { status: 400 });
  try {
    const upstream = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Satellit-Token": token },
      body: JSON.stringify(payload.body ?? {}),
      cache: "no-store",
    });
    const data = await upstream.json().catch(() => ({ ok: false, error: `Antwort nicht lesbar (${upstream.status})` }));
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    return NextResponse.json({ ok: false, error: `Python-API nicht erreichbar: ${String(err)}` }, { status: 502 });
  }
}

export async function GET() {
  const base = process.env.SATELLIT_API_URL || "http://satellit:8787";
  try {
    const upstream = await fetch(`${base}/health`, { cache: "no-store" });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch (err) {
    return NextResponse.json({ ok: false, error: `Python-API nicht erreichbar: ${String(err)}` }, { status: 502 });
  }
}
