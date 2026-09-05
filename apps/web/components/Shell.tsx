"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { brain, clearSession, getToken } from "@/lib/api";
import { ThemeToggle } from "./ui";

const NAV: { group: string; links: { label: string; href: string }[] }[] = [
  {
    group: "Merchant",
    links: [
      { label: "Overview", href: "/app" },
      { label: "Unresolved money", href: "/app/money" },
      { label: "Attention", href: "/app/attention" },
      { label: "Decisions", href: "/app/decisions" },
      { label: "What if", href: "/app/simulate" },
      { label: "Copilot", href: "/app/copilot" },
    ],
  },
  {
    group: "Admin console",
    links: [
      { label: "Analytics", href: "/app/admin/analytics" },
      { label: "Agents & trust", href: "/app/admin/agents" },
      { label: "Decision pipeline", href: "/app/admin/pipeline" },
      { label: "Events", href: "/app/admin/events" },
      { label: "Data explorer", href: "/app/admin/data" },
      { label: "Audit trail", href: "/app/admin/audit" },
      { label: "Policy & memory", href: "/app/admin/policy" },
      { label: "Test lab", href: "/app/admin/testing" },
      { label: "System", href: "/app/admin/system" },
    ],
  },
];

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<any>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setReady(true);
    brain
      .me()
      .then(setMe)
      .catch(() => null);
  }, [router]);

  if (!ready) {
    return (
      <main style={{ padding: 32 }}>
        <p className="subtle">Opening Business Brain…</p>
      </main>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            BB
          </span>
          <span>
            <span className="brand-name">Business Brain</span>
            <br />
            <span className="brand-sub">{me?.merchant_name || "Merchant intelligence"}</span>
          </span>
        </div>

        {NAV.map((section) => (
          <div key={section.group}>
            <div className="nav-group">{section.group}</div>
            {section.links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="nav-link"
                aria-current={path === link.href ? "page" : undefined}
              >
                <span className="dot" aria-hidden="true" />
                {link.label}
              </Link>
            ))}
          </div>
        ))}

        <div className="sidebar-foot">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <ThemeToggle />
            <button
              className="btn subtle sm"
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </div>
          <div className="tiny">
            {me?.email || "—"}
            <br />
            <span className="mono">{me?.merchant_id}</span>
          </div>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

export function PageHead({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p className="subtle">{description}</p>}
      </div>
      {actions && <div className="row tight">{actions}</div>}
    </header>
  );
}
