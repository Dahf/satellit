import { ActionsPanel } from "@/components/actions-panel";
import { getAccount, getTheses, isSatellite } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function ActionsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const theses = getTheses().filter(isSatellite);
  const options = theses
    .filter((t) => ["ENTRY_READY", "ACTIVE", "PARTIALLY_CLOSED"].includes(t.status))
    .map((t) => ({ id: t.id, label: `${t.symbol} · ${t.status} · Stop ${t.stop ?? "–"}`, status: t.status, stop: t.stop, entry: t.entry_price }));
  const account = getAccount();
  return (
    <ActionsPanel
      initialAction={sp.action ?? "new"}
      prefill={{ symbol: sp.symbol ?? "", entry: sp.entry ?? "", stop: sp.stop ?? "", id: sp.id ?? "" }}
      theses={options}
      equity={account.satellite_equity_eur}
      dryRunUntil={account.dry_run_until}
      killActive={account.kill_switch_active}
    />
  );
}
