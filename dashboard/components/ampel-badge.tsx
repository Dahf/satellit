import { Badge } from "@/components/ui/badge";
import type { AmpelState } from "@/lib/data";

export const AMPEL_LABEL: Record<string, string> = { GREEN: "GRÜN", YELLOW: "GELB", RED: "ROT" };

export function ampelVariant(state: AmpelState | string | null | undefined): "green" | "yellow" | "red" | "gray" {
  if (state === "GREEN") return "green";
  if (state === "YELLOW") return "yellow";
  if (state === "RED") return "red";
  return "gray";
}

export function AmpelBadge({ state, className }: { state: AmpelState | string | null | undefined; className?: string }) {
  return (
    <Badge variant={ampelVariant(state)} className={className}>
      {state ? AMPEL_LABEL[state] ?? state : "UNBEKANNT"}
    </Badge>
  );
}
