import { useEffect, useState } from "react";
import { Search, ShoppingCart, User } from "lucide-react";
import { authHeaders } from "./context";
import { AccountDetail, type Account } from "./Accounts";

export type AutobuyAccount = Account & {
  sell_id: number;
  seller_discord_id: number;
  sell_email: string;
  sold_at: string;
  amount_usd?: number | null;
  seller_ltc?: string | null;
  sell_account_id?: string | null;
};

export function AutobuyAccounts() {
  const [rows, setRows] = useState<AutobuyAccount[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () =>
      fetch("/api/accounts/autobuy", { headers: authHeaders() })
        .then((r) => r.json())
        .then((data: AutobuyAccount[]) => {
          setRows(Array.isArray(data) ? data : []);
        })
        .catch(() => setRows([]))
        .finally(() => setLoading(false));
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  const filtered = rows.filter((r) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (r.ms_email || "").toLowerCase().includes(q) ||
      (r.sell_email || "").toLowerCase().includes(q) ||
      (r.mc_name || "").toLowerCase().includes(q) ||
      String(r.seller_discord_id || "").includes(q)
    );
  });

  if (selected) {
    return (
      <AccountDetail
        account={selected}
        onBack={() => setSelected(null)}
        onDeleted={() => {
          setRows((prev) => prev.filter((a) => a.account_id !== selected.account_id));
          setSelected(null);
        }}
      />
    );
  }

  return (
    <div className="flex-1 flex flex-col space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
            Autobuy Accounts
          </h1>
          <p className="mt-1 text-sm font-semibold text-muted-foreground">
            {filtered.length} sold via Discord autobuy
            {rows.length !== filtered.length ? ` · ${rows.length} total` : ""}
          </p>
        </div>
      </div>

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search email, MC name, seller ID…"
          className="w-full rounded-lg border border-border bg-card/60 py-2.5 pl-10 pr-3 text-sm outline-none transition focus:border-[--primary]/50"
        />
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-[--primary] border-t-transparent" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-20 text-muted-foreground">
          <ShoppingCart className="h-10 w-10 opacity-40" />
          <p className="text-sm font-medium">No autobuy sales yet</p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((row) => {
            const hasDb =
              row.sell_account_id ||
              (row.account_id && !String(row.account_id).startsWith("sell-"));
            return (
              <button
                key={row.sell_id}
                type="button"
                onClick={async () => {
                  if (!hasDb) return;
                  const id = row.sell_account_id || row.account_id;
                  try {
                    const res = await fetch(`/api/accounts/${id}`, {
                      headers: authHeaders(),
                    });
                    if (!res.ok) {
                      setSelected(row);
                      return;
                    }
                    const full = (await res.json()) as Account;
                    setSelected(full);
                  } catch {
                    setSelected(row);
                  }
                }}
                className="group rounded-xl border border-border bg-card/50 p-4 text-left transition hover:border-[--primary]/40 hover:bg-card/80"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-foreground">
                      {row.ms_email || row.sell_email}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {row.mc_name || "—"} · {row.mc_method || "—"}
                    </p>
                  </div>
                  {row.amount_usd != null && (
                    <span className="shrink-0 rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-400">
                      ${Number(row.amount_usd).toFixed(2)}
                    </span>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <User className="h-3 w-3" />
                    Seller {row.seller_discord_id}
                  </span>
                  <span>
                    {row.sold_at
                      ? new Date(row.sold_at.replace(" ", "T") + "Z").toLocaleString()
                      : "—"}
                  </span>
                </div>
                {!hasDb && (
                  <p className="mt-2 text-xs text-amber-400/90">
                    Sell recorded — secured account row not linked
                  </p>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
