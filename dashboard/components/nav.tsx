"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/", label: "Übersicht" },
  { href: "/screener", label: "Screener" },
  { href: "/journal", label: "Journal" },
  { href: "/ampel", label: "Ampel" },
  { href: "/aktionen", label: "Aktionen" },
];

export function Nav() {
  const pathname = usePathname();
  if (pathname === "/login") return null;
  return (
    <nav className="flex items-center gap-1 overflow-x-auto">
      {ITEMS.map((it) => {
        const active = it.href === "/" ? pathname === "/" : pathname.startsWith(it.href);
        return (
          <Link
            key={it.href}
            href={it.href}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            )}
          >
            {it.label}
          </Link>
        );
      })}
      <form action="/api/logout" method="post" className="ml-auto">
        <button className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent" type="submit">
          Logout
        </button>
      </form>
    </nav>
  );
}
