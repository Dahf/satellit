// Login per Passwort (DASHBOARD_PASSWORD) — Session-Cookie = SHA-256(Passwort + Salt).
// Läuft in Middleware (Edge) und Route Handlers (Node) gleichermaßen, daher Web Crypto statt node:crypto.

export const SESSION_COOKIE = "satellit_session";

async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function expectedSessionToken(): Promise<string | null> {
  const password = process.env.DASHBOARD_PASSWORD;
  if (!password) return null;
  const salt = process.env.SESSION_SALT || "satellit";
  return sha256Hex(`${password}:${salt}:v1`);
}

export async function passwordMatches(candidate: string): Promise<boolean> {
  const password = process.env.DASHBOARD_PASSWORD;
  if (!password) return false;
  // Längenunabhängiger Vergleich über Hashes
  const a = await sha256Hex(candidate);
  const b = await sha256Hex(password);
  return a === b;
}

export async function isValidSession(cookieValue: string | undefined): Promise<boolean> {
  if (!cookieValue) return false;
  const expected = await expectedSessionToken();
  return expected !== null && cookieValue === expected;
}
