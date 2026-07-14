import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  LayoutDashboard, Users, Inbox, Bot, ShieldCheck, Settings, Lock,
  ChevronRight, ChevronDown, LogOut, Menu, X, ShoppingCart,
} from "lucide-react";
import { clearAuthToken } from "@/lib/auth";
import type { Tab } from "./context";

export function Sidebar({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountsOpen, setAccountsOpen] = useState(
    () => tab === "accounts" || tab === "accounts-autobuy",
  );

  const items: { id: Tab; label: string; icon: typeof LayoutDashboard }[] = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "emails", label: "Emails", icon: Inbox },
    { id: "secure", label: "Secure", icon: ShieldCheck },
    { id: "bot", label: "Bot Config", icon: Bot },
    { id: "settings", label: "Settings", icon: Settings },
  ];

  const select = (id: Tab) => {
    if (id === "accounts" || id === "accounts-autobuy") {
      setAccountsOpen(true);
    }
    setTab(id);
    setMobileOpen(false);
  };

  const signOut = () => {
    clearAuthToken();
    navigate({ to: "/" });
  };

  const accountsActive = tab === "accounts" || tab === "accounts-autobuy";

  const navBody = (
    <>
      <div className="flex h-16 items-center gap-2 px-6">
        <span className="grid h-8 w-8 place-items-center rounded-md bg-gradient-to-br from-[--primary] to-[--accent] text-primary-foreground">
          <Lock className="h-4 w-4" />
        </span>
        <span className="font-display text-lg font-bold tracking-tight">
          Autosecure
        </span>
      </div>

      <nav className="mt-4 flex-1 space-y-1 px-3">
        {/* Overview first */}
        {items.slice(0, 1).map((item) => {
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => select(item.id)}
              className={`group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                active
                  ? "bg-gradient-to-r from-[--primary]/85 to-[--accent]/75 text-foreground shadow-sm border border-[--primary]/30"
                  : "text-muted-foreground hover:bg-card/85 hover:text-foreground"
              }`}
            >
              <item.icon className={`h-4 w-4 ${active ? "text-[--primary]" : ""}`} />
              {item.label}
              {active && <ChevronRight className="ml-auto h-4 w-4 text-[--primary]" />}
            </button>
          );
        })}

        {/* Accounts dropdown */}
        <div className="space-y-1">
          <button
            onClick={() => {
              setAccountsOpen((o) => !o);
              if (!accountsActive) select("accounts");
            }}
            className={`group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
              accountsActive
                ? "bg-gradient-to-r from-[--primary]/85 to-[--accent]/75 text-foreground shadow-sm border border-[--primary]/30"
                : "text-muted-foreground hover:bg-card/85 hover:text-foreground"
            }`}
          >
            <Users className={`h-4 w-4 ${accountsActive ? "text-[--primary]" : ""}`} />
            Accounts
            {accountsOpen ? (
              <ChevronDown className={`ml-auto h-4 w-4 ${accountsActive ? "text-[--primary]" : ""}`} />
            ) : (
              <ChevronRight className={`ml-auto h-4 w-4 ${accountsActive ? "text-[--primary]" : ""}`} />
            )}
          </button>

          {accountsOpen && (
            <div className="ml-4 space-y-0.5 border-l border-border pl-2">
              <button
                onClick={() => select("accounts")}
                className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition ${
                  tab === "accounts"
                    ? "bg-card/80 text-foreground font-medium"
                    : "text-muted-foreground hover:bg-card/60 hover:text-foreground"
                }`}
              >
                <Users className="h-3.5 w-3.5" />
                All accounts
              </button>
              <button
                onClick={() => select("accounts-autobuy")}
                className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition ${
                  tab === "accounts-autobuy"
                    ? "bg-card/80 text-foreground font-medium"
                    : "text-muted-foreground hover:bg-card/60 hover:text-foreground"
                }`}
              >
                <ShoppingCart className="h-3.5 w-3.5" />
                Autobuy accounts
              </button>
            </div>
          )}
        </div>

        {/* Remaining items */}
        {items.slice(1).map((item) => {
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => select(item.id)}
              className={`group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                active
                  ? "bg-gradient-to-r from-[--primary]/85 to-[--accent]/75 text-foreground shadow-sm border border-[--primary]/30"
                  : "text-muted-foreground hover:bg-card/85 hover:text-foreground"
              }`}
            >
              <item.icon className={`h-4 w-4 ${active ? "text-[--primary]" : ""}`} />
              {item.label}
              {active && <ChevronRight className="ml-auto h-4 w-4 text-[--primary]" />}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-border p-3">
        <button
          onClick={signOut}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition hover:bg-card/60 hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <>
      <button
        onClick={() => setMobileOpen(true)}
        aria-label="Open menu"
        className="fixed left-3 top-3 z-30 grid h-10 w-10 place-items-center rounded-lg border border-border bg-card/80 text-muted-foreground backdrop-blur transition hover:text-foreground md:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-card/95 backdrop-blur transition-transform duration-200 md:sticky md:top-0 md:z-auto md:h-screen md:translate-x-0 md:bg-card/40 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <button
          onClick={() => setMobileOpen(false)}
          aria-label="Close menu"
          className="absolute right-3 top-4 grid h-8 w-8 place-items-center rounded-lg text-muted-foreground transition hover:text-foreground md:hidden"
        >
          <X className="h-4 w-4" />
        </button>
        {navBody}
      </aside>
    </>
  );
}
