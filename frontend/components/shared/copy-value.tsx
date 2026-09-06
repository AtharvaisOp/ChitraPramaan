"use client";

import { Check, Copy } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

export function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timeout = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timeout);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setError(false);
    } catch { setError(true); }
  }

  return (
    <div className="rounded-lg border border-line bg-surface-subtle p-4">
      <div className="flex items-center justify-between gap-4">
        <span className="text-xs font-medium text-muted">{label}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium text-accent hover:bg-accent-soft"
          aria-label={copied ? `${label} copied` : `Copy ${label.toLowerCase()}`}
        >
          {copied ? <Check aria-hidden size={16} weight="bold" /> : <Copy aria-hidden size={16} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="mt-3 select-all overflow-wrap-anywhere font-mono text-sm leading-6 text-ink [overflow-wrap:anywhere]">{value}</p>
      {error ? <p role="status" className="mt-2 text-xs text-danger">Copy is unavailable. Select and copy the value above.</p> : null}
      <span className="sr-only" aria-live="polite">{copied ? `${label} copied` : ""}</span>
    </div>
  );
}
