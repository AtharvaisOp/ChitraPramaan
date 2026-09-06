"use client";

import { ArrowSquareOut, ImageBroken, X } from "@phosphor-icons/react";
import Image from "next/image";
import { useState } from "react";
import { ApiErrorAlert } from "@/components/shared/api-error-alert";
import { formatScore } from "@/lib/format";
import { platformFromUrl, safeHttpUrl } from "@/lib/platform";
import type { Candidate } from "@/lib/types";

function CandidateThumbnail({ candidate }: { candidate: Candidate }) {
  const [failed, setFailed] = useState(false);
  const valid = safeHttpUrl(candidate.thumbnail_url)?.protocol === "https:";
  if (failed || !valid) {
    return (
      <div className="grid aspect-square max-w-36 w-full place-items-center rounded-lg bg-surface-subtle text-muted">
        <span className="flex flex-col items-center gap-2 text-xs">
          <ImageBroken aria-hidden size={26} />
          Thumbnail unavailable
        </span>
      </div>
    );
  }
  return (
    <div className="relative aspect-square max-w-36 w-full overflow-hidden rounded-lg bg-surface-subtle">
      <Image
        src={candidate.thumbnail_url}
        alt={candidate.title ? `Thumbnail for ${candidate.title}` : `Thumbnail from ${platformFromUrl(candidate.url)}`}
        fill
        sizes="(max-width: 639px) 100vw, 144px"
        className="object-cover"
        unoptimized
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

export function MatchReviewScreen({
  candidates,
  recommendedIndex,
  selectedIndex,
  confirming,
  error,
  onSelect,
  onConfirm,
  onCancel,
}: {
  candidates: Candidate[];
  recommendedIndex: number | null;
  selectedIndex: number | null;
  confirming: boolean;
  error: string | null;
  onSelect: (index: number) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [cancelPrompt, setCancelPrompt] = useState(false);

  if (candidates.length === 0) {
    return (
      <section className="py-8">
        <h1 className="text-3xl font-semibold tracking-tight">No review candidates were returned</h1>
        <p className="mt-3 text-muted">This session cannot be confirmed. Start another analysis with a different photo.</p>
        <button type="button" onClick={onCancel} className="mt-7 rounded-lg bg-accent px-4 py-2.5 font-semibold text-white dark:text-zinc-950">Start over</button>
      </section>
    );
  }

  function requestCancel() {
    if (selectedIndex !== null) setCancelPrompt(true);
    else onCancel();
  }

  return (
    <section aria-labelledby="review-heading">
      <p className="evidence-kicker mb-3">Review the source evidence</p>
      <h1 id="review-heading" className="text-3xl font-semibold tracking-tight sm:text-4xl">Review possible matches</h1>
      <p className="mt-4 max-w-2xl leading-7 text-muted">
        {recommendedIndex === null
          ? "Compare the sources and choose a candidate only if the visual evidence supports it."
          : "A likely match is recommended below. Compare the sources and choose what should be anchored."}
      </p>

      <p className="evidence-note mt-5 max-w-2xl text-sm leading-6 text-muted">Similarity measures visual resemblance, not identity. You may cancel if none of these sources supports a claim.</p>

      {error ? <div className="mt-7"><ApiErrorAlert title="The claim could not be anchored" message={error} /></div> : null}

      <fieldset className="mt-9 space-y-4" disabled={confirming}>
        <legend className="sr-only">Ranked match candidates</legend>
        {candidates.map((candidate, position) => {
          const checked = selectedIndex === candidate.index;
          const url = safeHttpUrl(candidate.url);
          return (
            <div key={`${candidate.index}-${candidate.url}`} data-selected={checked} className={`candidate-card grid gap-4 rounded-lg border p-4 sm:grid-cols-[9rem_minmax(0,1fr)_auto] sm:items-center ${checked ? "border-accent bg-accent-soft/50" : "border-line bg-surface"}`}>
              <CandidateThumbnail candidate={candidate} />
              <div className="min-w-0">
                <div className="flex items-center gap-3 text-sm text-muted">
                  <span className="font-mono">Rank {position + 1}</span>
                  <span aria-hidden>/</span>
                  <span>{platformFromUrl(candidate.url)}</span>
                  {candidate.index === recommendedIndex ? (
                    <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">Recommended</span>
                  ) : null}
                </div>
                <label htmlFor={`candidate-${candidate.index}`} className="mt-2 block cursor-pointer text-lg font-semibold leading-6">
                  {candidate.title || "Untitled result"}
                </label>
                {url ? (
                  <a href={url.toString()} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex max-w-full items-center gap-1.5 text-sm text-accent hover:text-accent-hover">
                    <span className="break-all font-mono text-xs leading-5">{candidate.url}</span>
                    <ArrowSquareOut aria-hidden size={15} className="shrink-0" />
                  </a>
                ) : (
                  <p className="mt-3 break-all font-mono text-xs text-muted">{candidate.url}</p>
                )}
                {candidate.source ? <p className="mt-2 text-xs text-muted">Source: {candidate.source}</p> : null}
              </div>
              <div className="flex items-center justify-between gap-4 sm:flex-col sm:items-end">
                <div className="text-left sm:text-right">
                  <span className="block font-mono text-xl font-semibold">{formatScore(candidate.score)}</span>
                  <span className="text-xs text-muted">Similarity</span>
                </div>
                <label className="flex min-h-11 cursor-pointer items-center gap-3" htmlFor={`candidate-${candidate.index}`}>
                <input
                  id={`candidate-${candidate.index}`}
                  type="radio"
                  name="candidate"
                  value={candidate.index}
                  checked={checked}
                  onChange={() => onSelect(candidate.index)}
                  className="size-6 accent-[var(--accent)]"
                  aria-label={`Select ${candidate.title || `rank ${position + 1}`}`}
                />
                <span className="text-xs font-semibold text-accent">{checked ? "Selected" : "Select match"}</span>
                </label>
              </div>
            </div>
          );
        })}
      </fieldset>

      {cancelPrompt ? (
        <div className="mt-6 flex flex-col gap-4 rounded-lg border border-warning/30 bg-warning-soft p-4 sm:flex-row sm:items-center sm:justify-between" role="alert">
          <p className="text-sm">Cancel this review? No claim will be anchored from this screen.</p>
          <div className="flex gap-2">
            <button type="button" onClick={() => setCancelPrompt(false)} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-semibold">Keep reviewing</button>
            <button type="button" onClick={onCancel} className="inline-flex items-center gap-2 rounded-lg bg-danger px-3 py-2 text-sm font-semibold text-white dark:text-zinc-950"><X aria-hidden size={16} />Cancel review</button>
          </div>
        </div>
      ) : null}

      <div className="confirmation-bar sticky mt-8 flex flex-col gap-3 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:flex-row sm:items-center sm:justify-end">
        <p className="mr-auto max-w-sm text-xs leading-5 text-muted">{selectedIndex === null ? "Select one source to continue." : "Confirmation pins this claim publicly to IPFS and records its fingerprint on Sepolia."}</p>
        <button type="button" onClick={requestCancel} disabled={confirming} className="rounded-lg border border-line bg-surface px-4 py-2.5 font-semibold hover:bg-surface-subtle disabled:opacity-50">Cancel</button>
        <button type="button" onClick={onConfirm} disabled={selectedIndex === null || confirming} className="rounded-lg bg-accent px-5 py-2.5 font-semibold text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45 dark:text-zinc-950">
          {confirming ? "Pinning and anchoring" : "Confirm & Anchor"}
        </button>
      </div>
    </section>
  );
}
