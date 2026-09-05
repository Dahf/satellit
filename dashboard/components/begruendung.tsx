"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Aufklapp-Panel für die Begründung einer Entscheidung.
 *
 * Öffnet per Zeigen, Klicken und Tastaturfokus. Alles, was hier steht, ist auch ohne Maus
 * erreichbar — keine Information existiert ausschließlich im Hover.
 *
 * Gerendert wird in einem Portal am body: sonst schneidet der `overflow`-Container der
 * Liste das Panel ab, der klassische Fehler bei selbstgebauten Tooltips.
 */
export function Begruendung({ titel, children }: { titel: string; children: React.ReactNode }) {
  const [offen, setOffen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; breite: number } | null>(null);
  const [schmal, setSchmal] = useState(false);
  const knopf = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const id = useId();

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const setzen = () => setSchmal(mq.matches);
    setzen();
    mq.addEventListener("change", setzen);
    return () => mq.removeEventListener("change", setzen);
  }, []);

  useLayoutEffect(() => {
    if (!offen || schmal || !knopf.current) return;
    const platzieren = () => {
      const r = knopf.current!.getBoundingClientRect();
      const breite = Math.min(380, window.innerWidth - 32);
      const hoehe = panel.current?.offsetHeight ?? 320;
      // Nach oben kippen, wenn unten kein Platz ist; horizontal im Sichtfeld klemmen.
      const untenFrei = window.innerHeight - r.bottom;
      const top = untenFrei > hoehe + 16 ? r.bottom + 8 : Math.max(16, r.top - hoehe - 8);
      const left = Math.min(Math.max(16, r.left), window.innerWidth - breite - 16);
      setPos({ top, left, breite });
    };
    platzieren();
    window.addEventListener("scroll", platzieren, true);
    window.addEventListener("resize", platzieren);
    return () => {
      window.removeEventListener("scroll", platzieren, true);
      window.removeEventListener("resize", platzieren);
    };
  }, [offen, schmal]);

  useEffect(() => {
    if (!offen) return;
    const taste = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOffen(false);
        knopf.current?.focus();
      }
    };
    const draussen = (e: MouseEvent) => {
      const z = e.target as Node;
      if (!panel.current?.contains(z) && !knopf.current?.contains(z)) setOffen(false);
    };
    document.addEventListener("keydown", taste);
    document.addEventListener("mousedown", draussen);
    return () => {
      document.removeEventListener("keydown", taste);
      document.removeEventListener("mousedown", draussen);
    };
  }, [offen]);

  const abbrechen = () => timer.current && clearTimeout(timer.current);
  const verzoegertSchliessen = () => {
    abbrechen();
    timer.current = setTimeout(() => setOffen(false), 150);
  };

  const inhalt = (
    <div
      ref={panel}
      id={id}
      role="dialog"
      aria-label={`Begründung: ${titel}`}
      onMouseEnter={abbrechen}
      onMouseLeave={schmal ? undefined : verzoegertSchliessen}
      className={
        schmal
          ? "einblenden fixed inset-x-0 bottom-0 z-50 max-h-[80vh] overflow-y-auto rounded-t-xl border-t border-border bg-card p-5 shadow-2xl"
          : "einblenden fixed z-50 max-h-[70vh] overflow-y-auto rounded-lg border border-border bg-card p-4 shadow-xl"
      }
      style={schmal ? undefined : { top: pos?.top ?? -9999, left: pos?.left ?? -9999, width: pos?.breite ?? 360 }}
    >
      {schmal && (
        <div className="mb-3 flex items-center justify-between">
          <span className="font-display text-ansage">{titel}</span>
          <button onClick={() => setOffen(false)} className="text-etikett text-muted-foreground underline">
            Schließen
          </button>
        </div>
      )}
      {children}
    </div>
  );

  return (
    <>
      <button
        ref={knopf}
        type="button"
        aria-expanded={offen}
        aria-controls={offen ? id : undefined}
        onClick={() => setOffen((o) => !o)}
        onFocus={() => setOffen(true)}
        onMouseEnter={() => {
          if (window.matchMedia("(hover: hover)").matches) {
            abbrechen();
            setOffen(true);
          }
        }}
        onMouseLeave={verzoegertSchliessen}
        className="rounded-sm text-etikett text-muted-foreground underline decoration-dotted underline-offset-4 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        Warum?
      </button>
      {offen && typeof document !== "undefined" && createPortal(inhalt, document.body)}
    </>
  );
}
