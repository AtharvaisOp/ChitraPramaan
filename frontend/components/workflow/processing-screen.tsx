import { SpinnerGap } from "@phosphor-icons/react";

export function ProcessingScreen() {
  return (
    <section className="mx-auto max-w-2xl py-8 sm:py-14" aria-labelledby="processing-heading">
      <div className="flex items-center gap-3 text-accent" aria-hidden>
        <SpinnerGap className="spinner" size={28} weight="bold" />
        <span className="h-px flex-1 bg-line" />
      </div>
      <h1 id="processing-heading" className="mt-8 text-3xl font-semibold tracking-tight">
        Analyzing photo
      </h1>
      <p className="mt-4 max-w-xl leading-7 text-muted" aria-live="polite">
        Detecting a face and searching for matching social results. This may take a moment.
      </p>
      <p className="mt-3 text-sm leading-6 text-muted">Keep this tab open. Leaving the page does not stop work already running on the backend.</p>

      <div className="mt-9 rounded-lg border border-line bg-surface p-6" role="status" aria-live="polite">
        <p className="evidence-kicker">Analysis in progress</p>
        <p className="mt-3 text-sm leading-7 text-muted">Detecting subject → Searching sources → Comparing matches</p>
        <p className="mt-3 text-xs leading-6 text-muted">These are the stages of this request. The backend returns the ranked results when all stages are complete.</p>
      </div>
    </section>
  );
}
