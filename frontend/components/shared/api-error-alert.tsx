import { WarningCircle } from "@phosphor-icons/react";
import Link from "next/link";

export function ApiErrorAlert({
  title,
  message,
  errorCode,
  onRetry,
}: {
  title: string;
  message: string;
  errorCode?: string;
  onRetry?: () => void;
}) {
  const pendingFingerprint = message.startsWith("Transaction outcome is unknown") ? message.match(/\b[0-9a-f]{64}\b/i)?.[0] : undefined;
  return (
    <div role="alert" className="flex gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4 text-sm">
      <WarningCircle aria-hidden className="mt-0.5 shrink-0 text-danger" size={20} weight="fill" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink">{title}</p>
        <p className="mt-1 text-muted [overflow-wrap:anywhere]">{message}</p>
        {errorCode ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-muted">Error details</summary>
            <p className="mt-1 font-mono text-xs text-muted">{errorCode}</p>
          </details>
        ) : null}
        {pendingFingerprint ? <Link href={`/verify/${pendingFingerprint}`} className="mt-3 inline-flex min-h-11 items-center font-semibold text-accent">Re-verify pending fingerprint</Link> : null}
        {onRetry ? (
          <button type="button" onClick={onRetry} className="mt-3 inline-flex min-h-11 items-center rounded-lg bg-accent px-4 py-2 font-semibold text-white hover:bg-accent-hover dark:text-zinc-950">
            Try again
          </button>
        ) : null}
      </div>
    </div>
  );
}
