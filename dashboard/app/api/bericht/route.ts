import fs from "node:fs";
import path from "node:path";
import { DATA_DIR, getView } from "@/lib/view";

/**
 * Den Wochenbericht ausliefern.
 *
 * `daten.bericht` wurde seit jeher befüllt und nirgends verlinkt: die Oberfläche zitierte
 * neben jeder Zeile eine Fundstelle, während der ausführliche Bericht als Datei auf dem
 * Server lag und für den Nutzer unerreichbar war.
 *
 * Die Route nimmt bewusst **keinen** Parameter. Der Dateiname kommt aus der Ansicht, nicht
 * aus der Anfrage — damit gibt es keinen Weg, über `../` aus dem Datenverzeichnis
 * herauszulaufen. Zusätzlich muss der Name dem Muster des Berichtsschreibers entsprechen.
 *
 * Der Pfad in der Ansicht stammt aus dem satellit-Container (`/app/state/...`); das
 * Dashboard mountet dasselbe Volume unter `/data`. Übernommen wird deshalb nur der
 * Dateiname, nie der Pfad.
 */
const NAME = /^weekly_\d{4}-\d{2}-\d{2}\.md$/;

export const dynamic = "force-dynamic";

export async function GET() {
  const pfad = getView()?.daten?.bericht;
  if (!pfad) {
    return new Response("Noch kein Bericht erzeugt.", { status: 404 });
  }
  const name = path.basename(pfad.replace(/\\/g, "/"));
  if (!NAME.test(name)) {
    return new Response("Unerwarteter Berichtsname.", { status: 404 });
  }
  try {
    const text = fs.readFileSync(path.join(DATA_DIR, "reports", name), "utf-8");
    return new Response(text, {
      status: 200,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch {
    return new Response("Bericht nicht lesbar.", { status: 404 });
  }
}
