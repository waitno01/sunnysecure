import { useState, useEffect, useRef, useCallback } from "react";
import {
  Search, Plus, X, Mail, MailOpen, Inbox, RotateCcw, Loader2, ChevronRight,
  Trash2, CheckSquare, Square, ChevronLeft, ChevronsLeft, ChevronsRight,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger,
} from "@/components/ui/dialog";
import { useNotifications, authHeaders } from "./context";
import { clearAuthToken } from "@/lib/auth";
import type { EmailEntry, EmailMessage } from "./types";
import { toast } from "sonner";

const PER_PAGE = 10;

export function EmailsPanel() {
  const [emails, setEmails] = useState<EmailEntry[]>([]);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [creating, setCreating] = useState(false);
  const [modalEmail, setModalEmail] = useState<string | null>(null);
  const [hideEmpty, setHideEmpty] = useState(false);
  const [selectedMsg, setSelectedMsg] = useState<EmailMessage | null>(null);
  const [domain, setDomain] = useState("example.com");
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(0);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedEmails, setSelectedEmails] = useState<Set<string>>(new Set());
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showSelectMenu, setShowSelectMenu] = useState(false);
  const [showBar, setShowBar] = useState(false);
  const barVisible = selectMode && selectedEmails.size > 0;
  const [freshIds, setFreshIds] = useState<Set<number>>(new Set());
  const [sortBy, setSortBy] = useState<"unread" | "most" | "least" | "latest">("unread");
  const [showSortMenu, setShowSortMenu] = useState(false);

  useEffect(() => {
    if (barVisible) {
      setShowBar(true);
    } else {
      const timer = setTimeout(() => setShowBar(false), 300);
      return () => clearTimeout(timer);
    }
  }, [barVisible]);
  const [barStyle, setBarStyle] = useState<React.CSSProperties>({});
  const knownIds = useRef<Set<number>>(
    new Set(JSON.parse(typeof localStorage !== "undefined" ? localStorage.getItem("known-email-ids") || "[]" : "[]"))
  );
  const { addNotification } = useNotifications();

  function playNotificationSound() {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.1);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.4);
      setTimeout(() => ctx.close(), 500);
    } catch {}
  }

  const load = () => {
    const start = Date.now();
    setRefreshing(true);
    const done = () => {
      const elapsed = Date.now() - start;
      if (elapsed < 1500) setTimeout(() => setRefreshing(false), 1500 - elapsed);
      else setRefreshing(false);
    };
    return Promise.all([
      fetch("/api/emails", { credentials: "include", headers: authHeaders() }),
      fetch("/api/config", { credentials: "include", headers: authHeaders() }),
    ]).then(async ([emailsRes, configRes]) => {
      if (emailsRes.status === 401 || configRes.status === 401) {
        clearAuthToken();
        return;
      }
      if (!emailsRes.ok || !configRes.ok) return;
      const e: EmailEntry[] = await emailsRes.json();
      const c = await configRes.json();
      const current = new Set<number>();
      const newMessages: { id: number; email: string; subject: string }[] = [];
      for (const entry of e as EmailEntry[]) {
        for (const msg of entry.inbox) {
          current.add(msg.id);
          if (!knownIds.current.has(msg.id)) {
            newMessages.push({ id: msg.id, email: entry.email, subject: msg.subject });
          }
        }
      }
      if (newMessages.length > 0) {
        playNotificationSound();
        setFreshIds(prev => {
          const next = new Set(prev);
          for (const m of newMessages) next.add(m.id);
          return next;
        });
        for (const nm of newMessages) {
          addNotification(`New email at ${nm.email}`, nm.subject || "(no subject)");
          toast(`New email at ${nm.email}`, {
            description: nm.subject || "(no subject)",
          });
        }
      }
      knownIds.current = current;
      localStorage.setItem("known-email-ids", JSON.stringify([...current]));
      setEmails(e);
      setDomain(c.domain);
    }).finally(done);
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const withNewCount = emails.map(e => ({
    ...e,
    newCount: e.inbox.filter(m => freshIds.has(m.id)).length,
    lastReceived: e.inbox.reduce((latest, m) => m.received_at > latest ? m.received_at : latest, ""),
  }));

  const q = search.toLowerCase().trim();
  const filtered = withNewCount.filter(e =>
    e.email.toLowerCase().includes(q) && (!hideEmpty || e.inbox_count > 0)
  ).sort((a, b) => {
    if (q) {
      const aStarts = a.email.toLowerCase().startsWith(q) ? 0 : 1;
      const bStarts = b.email.toLowerCase().startsWith(q) ? 0 : 1;
      if (aStarts !== bStarts) return aStarts - bStarts;
    }
    if (sortBy === "most") return b.inbox_count - a.inbox_count;
    if (sortBy === "least") return a.inbox_count - b.inbox_count;
    if (sortBy === "latest") return b.lastReceived.localeCompare(a.lastReceived);
    return b.newCount - a.newCount || b.inbox_count - a.inbox_count;
  });

  const totalPages = Math.ceil(filtered.length / PER_PAGE);
  const safePage = Math.min(page, totalPages - 1);
  const paginated = filtered.slice(safePage * PER_PAGE, (safePage + 1) * PER_PAGE);

  function toggleSelect(email: string) {
    setSelectedEmails(prev => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  }

  function selectAll() {
    setSelectedEmails(new Set(filtered.map(e => e.email)));
  }

  function selectEmpty() {
    setSelectedEmails(new Set(withNewCount.filter(e => e.inbox_count === 0).map(e => e.email)));
  }

  async function handleDelete() {
    setDeleting(true);
    for (const email of selectedEmails) {
      await fetch(`/api/emails?email=${encodeURIComponent(email)}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
    }
    setDeleting(false);
    setShowDeleteConfirm(false);
    setSelectedEmails(new Set());
    setSelectMode(false);
    load();
  }

  function toggleSelectMode() {
    const next = !selectMode;
    setSelectMode(next);
    if (!next) setSelectedEmails(new Set());
  }

  function goToPage(p: number) {
    setPage(Math.max(0, Math.min(p, totalPages - 1)));
  }

  const getBarStyle = useCallback(() => {
    const main = document.querySelector("main");
    if (!main) return {};
    const rect = main.getBoundingClientRect();
    return {
      left: `${rect.left + rect.width / 2}px`,
      transform: "translateX(-50%)",
    };
  }, []);

  useEffect(() => {
    if (selectMode && selectedEmails.size > 0) {
      setBarStyle(getBarStyle());
      const onResize = () => setBarStyle(getBarStyle());
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }
  }, [selectMode, selectedEmails.size, getBarStyle]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newEmail) return;
    setCreating(true);
    let email = newEmail;
    if (!email.includes("@")) email = `${email}@${domain}`;
    await fetch("/api/emails", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ email }),
    });
    setNewEmail("");
    setShowForm(false);
    setCreating(false);
    load();
  }

  return (
    <div className="flex flex-1 flex-col space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Emails</h1>
          <p className="mt-1 text-sm font-semibold text-muted-foreground">
            {emails.length} email{emails.length !== 1 ? "s" : ""} in database
          </p>
        </div>
        <Dialog open={showForm} onOpenChange={setShowForm}>
          <DialogTrigger asChild>
            <button
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-[0_0_25px_-8px_color-mix(in_oklab,var(--primary)_40%,transparent)] transition hover:opacity-95"
            >
              <Plus className="h-4 w-4" />
              Create
            </button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Create Email</DialogTitle>
              <DialogDescription>Add a new email address to the database.</DialogDescription>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-5">
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Email</label>
                  <input
                    type="text" required value={newEmail} onChange={e => setNewEmail(e.target.value)}
                    placeholder={`user@${domain}`}
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-3 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
              </div>
              <button
                type="submit" disabled={creating}
                className="w-full inline-flex cursor-pointer items-center justify-center gap-3 rounded-xl bg-gradient-to-r from-[--primary] to-[--accent] px-6 py-3.5 text-base font-semibold text-primary-foreground shadow-[0_0_25px_-8px_color-mix(in_oklab,var(--primary)_40%,transparent)] transition hover:opacity-95 disabled:opacity-60"
              >
                {creating ? <Loader2 className="h-5 w-5 animate-spin" /> : <Mail className="h-5 w-5" />}
                {creating ? "Creating\u2026" : "Add Email"}
              </button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="flex gap-3 items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search emails..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full rounded-lg border border-border bg-card/60 py-2.5 pl-10 pr-4 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
          />
        </div>
        <button
          onClick={() => setHideEmpty(v => !v)}
          className={`grid h-9 shrink-0 place-items-center rounded-lg border px-3 text-xs font-semibold transition ${hideEmpty ? "border-[--accent] bg-[--accent]/15 text-[--accent]" : "border-border bg-card/60 text-muted-foreground hover:text-foreground"}`}
          title={hideEmpty ? "Show all" : "Hide empty"}
        >
          {hideEmpty ? "All" : "With mail"}
        </button>
        <div className="relative">
          <button
            onClick={() => setShowSortMenu(v => !v)}
            className="grid h-9 shrink-0 place-items-center rounded-lg border border-border bg-card/60 px-3 text-xs font-semibold text-muted-foreground transition hover:text-foreground"
            title="Sort emails"
          >
            {sortBy === "unread" ? "Unread" : sortBy === "most" ? "Most" : sortBy === "least" ? "Least" : "Latest"}
          </button>
          {showSortMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowSortMenu(false)} />
              <div className="absolute right-0 top-full mt-1 z-50 flex min-w-32 flex-col gap-1 rounded-xl border border-border bg-card p-2 shadow-xl animate-in fade-in zoom-in-95 duration-150">
                {([["unread", "Unread"], ["most", "Most emails"], ["least", "Least emails"], ["latest", "Latest received"]] as const).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => { setSortBy(key); setShowSortMenu(false); }}
                    className={`flex items-center gap-3 rounded-lg px-3 py-2 text-xs font-semibold transition text-left ${sortBy === key ? "text-[--accent] bg-[--accent]/10" : "text-foreground hover:bg-muted"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        <button
          onClick={toggleSelectMode}
          className={`grid h-9 shrink-0 place-items-center rounded-lg border px-3 text-xs font-semibold transition ${selectMode ? "border-[--accent] bg-[--accent]/15 text-[--accent]" : "border-border bg-card/60 text-muted-foreground hover:text-foreground"}`}
          title={selectMode ? "Exit selection" : "Select emails"}
        >
          {selectMode ? "Done" : "Select"}
        </button>
        <button onClick={() => { setFreshIds(new Set()); load(); }} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-card/60 text-muted-foreground transition hover:text-foreground" title="Refresh">
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin animation-duration-3000" /> : <RotateCcw className="h-4 w-4" />}
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-1 items-center justify-center rounded-2xl border border-border bg-card/40 backdrop-blur">
          <div className="mx-auto flex max-w-md flex-col items-center text-center">
            <div className="grid h-20 w-20 place-items-center rounded-full border-2 border-[--accent]/60 text-[--accent]">
              <Inbox className="h-9 w-9" />
            </div>
            <h2 className="mt-6 font-display text-2xl font-bold">No emails yet</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Create an email address to start receiving messages.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="flex flex-1 flex-col">
            {paginated.map((e, i) => {
              const isNew = e.newCount > 0;
              const absIndex = safePage * PER_PAGE + i;
              const prev = absIndex > 0 ? filtered[absIndex - 1] : null;
              const showSep = prev && ((prev.newCount > 0 && !isNew) || (prev.newCount === 0 && isNew));
              const isSelected = selectedEmails.has(e.email);
              return (
                <div key={e.email} className={absIndex > 0 && !showSep ? "mt-3" : ""}>
                  {showSep && (
                    <div className="flex items-center gap-3 py-3">
                      <div className="h-px flex-1 bg-border/40" />
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/50">Earlier</span>
                      <div className="h-px flex-1 bg-border/40" />
                    </div>
                  )}
                  <button
                    onClick={() => {
                      if (selectMode) {
                        toggleSelect(e.email);
                      } else {
                        setFreshIds(prev => {
                          const next = new Set(prev);
                          for (const m of e.inbox) next.delete(m.id);
                          return next;
                        });
                        setModalEmail(e.email);
                        const msgs = e.inbox;
                        setSelectedMsg(msgs[msgs.length - 1] ?? null);
                      }
                    }}
                    className={`animate-in fade-in slide-in-from-left-2 duration-400 flex w-full items-center gap-4 rounded-2xl border px-5 py-4 text-left transition ${
                      isSelected
                        ? "border-[--accent] bg-[--accent]/10"
                        : "border-border bg-card/40 backdrop-blur hover:bg-background/30"
                    } ${selectMode ? "cursor-pointer" : ""}`}
                    style={{ animationDelay: `${i * 50}ms` }}
                  >
                    {selectMode && (
                      <div className={`grid h-5 w-5 shrink-0 place-items-center rounded border-2 transition ${
                        isSelected
                          ? "border-[--accent] bg-[--accent] text-white scale-110"
                          : "border-muted-foreground/40 bg-transparent"
                      }`}>
                        {isSelected && <CheckSquare className="h-4 w-4" />}
                      </div>
                    )}
                    <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-lg ${isNew ? "bg-gradient-to-br from-[--primary]/30 to-[--accent]/20 text-[--accent]" : "bg-muted text-muted-foreground"}`}>
                      {isNew ? <Mail className="h-5 w-5" /> : <MailOpen className="h-5 w-5" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className={`text-sm font-medium ${isNew ? "text-foreground" : "text-muted-foreground"}`}>{e.email}</p>
                        {isNew && (
                          <span className="rounded-full bg-[--accent]/15 px-2 py-0.5 text-[10px] font-semibold text-[--accent]">
                            {e.newCount} new
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {e.inbox_count} message{e.inbox_count !== 1 ? "s" : ""}
                      </p>
                    </div>
                    {!selectMode && <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
                  </button>
                </div>
              );
            })}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-2">
              <button
                onClick={() => goToPage(0)}
                disabled={safePage === 0}
                className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-card/60 text-muted-foreground transition hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronsLeft className="h-4 w-4" />
              </button>
              <button
                onClick={() => goToPage(safePage - 1)}
                disabled={safePage === 0}
                className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-card/60 text-muted-foreground transition hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              {Array.from({ length: totalPages }, (_, i) => (
                <button
                  key={i}
                  onClick={() => goToPage(i)}
                  className={`grid h-8 min-w-8 place-items-center rounded-lg border px-2 text-xs font-semibold transition ${
                    i === safePage
                      ? "border-[--accent] bg-[--accent]/15 text-[--accent]"
                      : "border-border bg-card/60 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
              <button
                onClick={() => goToPage(safePage + 1)}
                disabled={safePage >= totalPages - 1}
                className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-card/60 text-muted-foreground transition hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
              <button
                onClick={() => goToPage(totalPages - 1)}
                disabled={safePage >= totalPages - 1}
                className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-card/60 text-muted-foreground transition hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronsRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {showBar && (
            <div className={`fixed bottom-6 z-50 flex w-max items-center gap-4 rounded-2xl border border-[--accent]/30 bg-card/95 px-5 py-3 shadow-xl backdrop-blur-xl ${barVisible ? "animate-in slide-in-from-bottom-4 fade-in" : "animate-out slide-out-to-bottom-4 fade-out"} duration-300`} style={barStyle}>
              <div className="relative">
                <button
                  onClick={() => setShowSelectMenu(v => !v)}
                  className="flex items-center gap-2 text-xs font-semibold text-muted-foreground transition hover:text-foreground"
                >
                  <CheckSquare className="h-4 w-4" />
                  Select
                </button>
                {showSelectMenu && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setShowSelectMenu(false)} />
                    <div className="absolute bottom-full left-0 mb-2 z-50 flex min-w-40 flex-col gap-1 rounded-xl border border-border bg-card p-2 shadow-xl animate-in fade-in zoom-in-95 duration-150">
                      <button
                        onClick={() => { selectAll(); setShowSelectMenu(false); }}
                        className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-muted text-left"
                      >
                        <CheckSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                        All ({filtered.length})
                      </button>
                      <button
                        onClick={() => { selectEmpty(); setShowSelectMenu(false); }}
                        className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-muted text-left"
                      >
                        <Inbox className="h-4 w-4 shrink-0 text-muted-foreground" />
                        Empty only ({withNewCount.filter(e => e.inbox_count === 0).length})
                      </button>
                    </div>
                  </>
                )}
              </div>
              <div className="h-6 w-px bg-border/40" />
              <span className="text-sm font-semibold text-foreground">
                {selectedEmails.size} selected
              </span>
              <div className="h-6 w-px bg-border/40" />
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-red-600/90 px-4 py-2 text-xs font-semibold text-white transition hover:bg-red-600"
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </button>
            </div>
          )}
        </>
      )}

      {modalEmail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={() => { setModalEmail(null); setSelectedMsg(null); }}>
          <div className="flex h-[80vh] w-[90vw] max-w-5xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl backdrop-blur animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
            <div className="flex w-80 shrink-0 flex-col border-r border-border">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <p className="text-sm font-semibold truncate">{modalEmail}</p>
                <button onClick={() => { setModalEmail(null); setSelectedMsg(null); }} className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 divide-y divide-border/50 overflow-y-auto">
                {(emails.find(e => e.email === modalEmail)?.inbox ?? []).length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-muted-foreground">No messages.</p>
                ) : (
                  emails.find(e => e.email === modalEmail)?.inbox.slice().reverse().map(msg => (
                    <button
                      key={msg.id}
                      onClick={() => setSelectedMsg(msg)}
                      className={`w-full px-4 py-3 text-left transition hover:bg-background/40 ${selectedMsg?.id === msg.id ? "bg-[--primary]/10" : ""}`}
                    >
                      <p className="truncate text-sm font-medium">{msg.subject || "(no subject)"}</p>
                      <p className="truncate text-xs text-muted-foreground">{msg.from_address}</p>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground/60">{msg.body?.slice(0, 80)}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground/40">{msg.received_at?.slice(0, 16).replace("T", " ")}</p>
                    </button>
                  ))
                )}
              </div>
            </div>
            <div className="flex flex-1 flex-col overflow-y-auto">
              {selectedMsg ? (
                <div className="flex flex-col p-6">
                  <div className="flex items-start justify-between gap-4">
                    <h2 className="font-display text-xl font-bold">{selectedMsg.subject || "(no subject)"}</h2>
                    <span className="shrink-0 text-xs text-muted-foreground">{selectedMsg.received_at?.slice(0, 16).replace("T", " ")}</span>
                  </div>
                  <p className="mt-4 text-sm text-muted-foreground">From: <span className="text-foreground">{selectedMsg.from_address}</span></p>
                  <p className="mt-1 text-sm text-muted-foreground">To: <span className="text-foreground">{selectedMsg.to_address}</span></p>
                  <div className="mt-6 whitespace-pre-wrap rounded-xl border border-border bg-background/40 p-5 text-sm leading-relaxed">{selectedMsg.body}</div>
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <div className="text-center">
                    <Mail className="mx-auto h-12 w-12 text-muted-foreground/30" />
                    <p className="mt-3 text-sm text-muted-foreground">Select a message to read</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <Dialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <DialogContent className="sm:max-w-md animate-in fade-in zoom-in-95 duration-200">
          <DialogHeader>
            <DialogTitle>Delete emails</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete {selectedEmails.size} email{selectedEmails.size !== 1 ? "s" : ""}? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setShowDeleteConfirm(false)}
              disabled={deleting}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-card/60 px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:text-foreground disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-red-600/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-600 disabled:opacity-60"
            >
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {deleting ? "Deleting\u2026" : "Delete"}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}