"use client";

import { WarningCircle } from "@phosphor-icons/react";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-[100dvh] max-w-3xl items-center px-5 py-16">
      <section className="w-full rounded-lg border border-line bg-surface p-6 sm:p-8">
        <WarningCircle aria-hidden size={28} weight="duotone" className="text-danger" />
        <h1 className="mt-5 text-2xl font-semibold tracking-tight">The interface could not load</h1>
        <p className="mt-2 text-muted">Your photo was not submitted. Try loading this screen again.</p>
        <button className="mt-6 rounded-lg bg-accent px-4 py-2.5 font-medium text-white disabled:opacity-50 dark:text-zinc-950" type="button" onClick={reset}>
          Try again
        </button>
      </section>
    </main>
  );
}
