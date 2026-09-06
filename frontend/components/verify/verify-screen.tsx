"use client";

import {
  ArrowClockwise,
  ArrowLeft,
  ArrowSquareOut,
  CheckCircle,
  SpinnerGap,
  XCircle,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { verifyFingerprint } from "@/lib/api";
import { formatTimestamp, isValidFingerprint } from "@/lib/format";
import { ipfsGatewayUrl } from "@/lib/platform";
import type { VerifyResponse } from "@/lib/types";
import { AppShell } from "@/components/shared/app-shell";
import { ApiErrorAlert } from "@/components/shared/api-error-alert";
import { CopyValue } from "@/components/shared/copy-value";

type VerificationFlight = {
  controller: AbortController;
  promise: Promise<VerifyResponse>;
  subscribers: number;
  abortTimer: ReturnType<typeof setTimeout> | null;
};

const verificationFlights = new Map<string, VerificationFlight>();

function subscribeToVerification(fingerprint: string) {
  let flight = verificationFlights.get(fingerprint);
  if (!flight) {
    const controller = new AbortController();
    const nextFlight: VerificationFlight = {
      controller,
      promise: Promise.resolve().then(() => verifyFingerprint(fingerprint, controller.signal)),
      subscribers: 0,
      abortTimer: null,
    };
    verificationFlights.set(fingerprint, nextFlight);
    void nextFlight.promise.then(
      () => {
        if (verificationFlights.get(fingerprint) === nextFlight) verificationFlights.delete(fingerprint);
      },
      () => {
        if (verificationFlights.get(fingerprint) === nextFlight) verificationFlights.delete(fingerprint);
      },
    );
    flight = nextFlight;
  }

  if (flight.abortTimer !== null) {
    clearTimeout(flight.abortTimer);
    flight.abortTimer = null;
  }
  flight.subscribers += 1;
  let released = false;

  return {
    promise: flight.promise,
    release() {
      if (released) return;
      released = true;
      flight.subscribers -= 1;
      if (flight.subscribers !== 0 || verificationFlights.get(fingerprint) !== flight) return;
      flight.abortTimer = setTimeout(() => {
        if (flight.subscribers === 0 && verificationFlights.get(fingerprint) === flight) {
          verificationFlights.delete(fingerprint);
          flight.controller.abort();
        }
      }, 0);
    },
  };
}

function RecordRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-6">
      <dt className="text-sm font-medium text-muted">{label}</dt>
      <dd className="min-w-0 text-sm text-ink">{children}</dd>
    </div>
  );
}

export function VerifyScreen({ initialFingerprint }: { initialFingerprint: string }) {
  const fingerprint = initialFingerprint.trim();
  const valid = isValidFingerprint(fingerprint);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(valid);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<VerifyResponse | null>(null);

  useEffect(() => {
    if (!valid) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setLoading(true);
      setError(null);
      setResult(null);
    });
    const subscription = subscribeToVerification(fingerprint);
    subscription.promise
      .then((response) => { if (active) setResult(response); })
      .catch((reason: unknown) => {
        if (!active) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "An unexpected error occurred.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      subscription.release();
    };
  }, [attempt, fingerprint, valid]);

  function retry() {
    setLoading(true);
    setError(null);
    setResult(null);
    setAttempt((value) => value + 1);
  }

  if (!valid) {
    return (
      <AppShell stage="verify">
        <section className="py-6" aria-labelledby="verify-heading">
          <h1 id="verify-heading" className="text-3xl font-semibold tracking-tight">Re-verify claim</h1>
          <div className="mt-8"><ApiErrorAlert title="Invalid fingerprint" message="Enter a valid 64-character hexadecimal fingerprint, optionally prefixed with 0x." /></div>
          <Link href="/" className="mt-7 inline-flex items-center gap-2 rounded-lg font-medium text-accent hover:text-accent-hover">
            <ArrowLeft aria-hidden size={18} /> Analyze a photo
          </Link>
        </section>
      </AppShell>
    );
  }

  const gateway = result ? ipfsGatewayUrl(result.on_chain_record.uri) : null;
  return (
    <AppShell fingerprint={fingerprint} stage="verify">
      <section aria-labelledby="verify-heading">
        <p className="evidence-kicker">Independent / Read-only check</p>
        <h1 id="verify-heading" className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Re-verify claim</h1>
        <p className="mt-4 max-w-2xl leading-7 text-muted">
          Check the on-chain lookup key against the fingerprint recomputed from the public IPFS claim.
        </p>

        <div className="mt-8">
          <CopyValue label="Requested fingerprint" value={fingerprint} />
        </div>

        {loading ? (
          <div className="mt-9" role="status" aria-live="polite">
            <div className="flex items-center gap-3 text-sm font-medium text-accent">
              <SpinnerGap aria-hidden className="spinner" size={20} weight="bold" />
              Checking Registry and IPFS
            </div>
            <div className="mt-6 space-y-3" aria-hidden>
              <div className="h-14 animate-pulse rounded-lg bg-surface-subtle motion-reduce:animate-none" />
              <div className="h-14 animate-pulse rounded-lg bg-surface-subtle motion-reduce:animate-none" />
              <div className="h-14 animate-pulse rounded-lg bg-surface-subtle motion-reduce:animate-none" />
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="mt-9 space-y-5">
            <ApiErrorAlert title="Verification could not be completed" message={error} />
            <button type="button" onClick={retry} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-semibold text-white hover:bg-accent-hover dark:text-zinc-950">
              <ArrowClockwise aria-hidden size={18} weight="bold" /> Try again
            </button>
          </div>
        ) : null}

        {result ? (
          <div className="mt-9">
            <div className={`flex gap-4 rounded-lg border p-5 ${result.passed ? "border-success/30 bg-success-soft" : "border-danger/30 bg-danger-soft"}`} role="status">
              {result.passed ? (
                <CheckCircle aria-hidden className="mt-0.5 shrink-0 text-success" size={26} weight="fill" />
              ) : (
                <XCircle aria-hidden className="mt-0.5 shrink-0 text-danger" size={26} weight="fill" />
              )}
              <div>
                <p className={`mb-1 font-mono text-xs font-semibold tracking-widest ${result.passed ? "text-success" : "text-danger"}`}>{result.passed ? "PASS" : "FAIL"}</p>
                <h2 className="text-lg font-semibold">{result.passed ? "Verification passed" : result.on_chain_record.exists ? "Verification failed" : "No on-chain record was found"}</h2>
                <p className="mt-1 text-sm leading-6 text-muted">{result.message}</p>
                <p className="mt-2 text-sm leading-6 text-muted">{result.passed ? "The claim fetched from the recorded CID reproduces the requested fingerprint. This confirms claim integrity, not identity or the accuracy of the source." : result.on_chain_record.exists ? "The IPFS comparison failed: the fetched claim produces a different fingerprint. Do not rely on this record as matching evidence." : "The Registry lookup failed to find this fingerprint. IPFS comparison was not performed."}</p>
              </div>
            </div>

            <div className="check-grid mt-6" aria-label="Verification components">
              <div><p className="text-xs text-muted">Sepolia Registry</p><p className="mt-2 text-sm font-semibold">{result.on_chain_record.exists ? "Record found" : "No record"}</p></div>
              <div><p className="text-xs text-muted">IPFS claim</p><p className="mt-2 text-sm font-semibold">{result.fetched_fingerprint ? "Fetched & hashed" : "Not checked"}</p></div>
              <div><p className="text-xs text-muted">Fingerprint comparison</p><p className="mt-2 text-sm font-semibold">{result.passed ? "Exact match" : result.on_chain_record.exists ? "Mismatch" : "Not checked"}</p></div>
            </div>
            <p className="mt-4 text-xs leading-6 text-muted">This check compares a requested fingerprint with the public claim. To recompute a local claim file as well, use the independent verification script.</p>
            <details className="mt-6 border-y border-line" open>
            <summary className="text-sm font-semibold">Technical evidence</summary>
            <section className="mt-5" aria-labelledby="comparison-heading">
              <h2 id="comparison-heading" className="text-lg font-semibold">Fingerprint comparison</h2>
              <dl className="mt-3 border-y border-line">
                <RecordRow label="Lookup fingerprint"><span className="break-all font-mono">{result.fingerprint}</span></RecordRow>
                <RecordRow label="IPFS fingerprint"><span className="break-all font-mono">{result.fetched_fingerprint ?? "Not available"}</span></RecordRow>
                <RecordRow label="Integrity result">{result.passed ? "Match" : "No match"}</RecordRow>
              </dl>
            </section>

            <section className="mt-9" aria-labelledby="record-heading">
              <h2 id="record-heading" className="text-lg font-semibold">On-chain record</h2>
              <dl className="mt-3 border-y border-line">
                <RecordRow label="Exists">{result.on_chain_record.exists ? "Yes" : "No"}</RecordRow>
                <RecordRow label="Submitter"><span className="break-all font-mono">{result.on_chain_record.submitter || "Not available"}</span></RecordRow>
                <RecordRow label="Timestamp">
                  <span>{formatTimestamp(result.on_chain_record.timestamp)}</span>
                  {result.on_chain_record.timestamp > 0 ? <span className="mt-1 block font-mono text-xs text-muted">Unix {result.on_chain_record.timestamp}</span> : null}
                </RecordRow>
                <RecordRow label="Stored URI">
                  <span className="break-all font-mono">{result.on_chain_record.uri || "Not available"}</span>
                  {gateway ? (
                    <a href={gateway} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-2 font-sans text-sm font-medium text-accent hover:text-accent-hover">
                      Open pinned claim <ArrowSquareOut aria-hidden size={15} />
                    </a>
                  ) : null}
                </RecordRow>
              </dl>
            </section>

            </details>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <button type="button" onClick={retry} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-semibold text-white hover:bg-accent-hover dark:text-zinc-950">
                <ArrowClockwise aria-hidden size={18} weight="bold" /> Verify again
              </button>
              <Link href="/" className="button-like inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-surface px-4 py-2.5 font-semibold hover:bg-surface-subtle">
                <ArrowLeft aria-hidden size={18} /> Analyze a photo
              </Link>
            </div>
          </div>
        ) : null}
      </section>
    </AppShell>
  );
}
