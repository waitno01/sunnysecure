import { X, Mail } from "lucide-react";
import type { EmailEntry, EmailMessage } from "./types";

export function EmailInboxModal({
  email,
  emails,
  selectedMsg,
  onClose,
  onSelectMsg,
}: {
  email: string;
  emails: EmailEntry[];
  selectedMsg: EmailMessage | null;
  onClose: () => void;
  onSelectMsg: (msg: EmailMessage | null) => void;
}) {
  const msgs = emails.find(e => e.email === email)?.inbox ?? [];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={() => { onClose(); onSelectMsg(null); }}>
      <div className="flex h-[80vh] w-[90vw] max-w-5xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl backdrop-blur animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
        <div className="flex w-80 shrink-0 flex-col border-r border-border">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <p className="text-sm font-semibold truncate">{email}</p>
            <button onClick={() => { onClose(); onSelectMsg(null); }} className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 divide-y divide-border/50 overflow-y-auto">
            {msgs.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">No messages.</p>
            ) : (
              msgs.slice().reverse().map(msg => (
                <button
                  key={msg.id}
                  onClick={() => onSelectMsg(msg)}
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
  );
}
