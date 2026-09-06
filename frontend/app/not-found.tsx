import Link from "next/link";
import { AppShell } from "@/components/shared/app-shell";

export default function NotFound() {
  return (
    <AppShell>
      <section className="py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Page not found</h1>
        <p className="mt-3 max-w-xl text-muted">The requested workflow page does not exist.</p>
        <Link className="button-like mt-8 inline-flex rounded-lg bg-accent px-4 py-2.5 font-medium text-white dark:text-zinc-950" href="/">
          Analyze a photo
        </Link>
      </section>
    </AppShell>
  );
}
