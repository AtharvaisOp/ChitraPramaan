import { ArrowUpRight, Check } from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { MotionSurface } from "@/components/shared/motion-surface";

const stages = ["Upload", "Analyze", "Select", "Record", "Re-verify"];
export function AppShell({ children, fingerprint, stage = "upload" }: {
  children: ReactNode; fingerprint?: string; wide?: boolean;
  stage?: "upload" | "processing" | "review" | "anchoring" | "result" | "verify";
}) {
  const active = { upload: 0, processing: 1, review: 2, anchoring: 3, result: 3, verify: 4 }[stage];
  return (
    <div className="app-root" data-stage={stage}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="app-header">
        <div className="shell-width flex items-center justify-between gap-4 py-5">
          <Link href="/" className="brand flex min-w-0 items-center gap-3">
            <span className="brand-mark"><Image src="/apple-touch-icon.png" alt="" width={40} height={40} priority /></span>
            <span><span className="block text-lg font-semibold tracking-tight">ChitraPramaan</span>
              <span className="brand-caption">A little more certainty.</span></span>
          </Link>
          <div className="flex items-center gap-6">
            <span className="network-label"><span aria-hidden />Sepolia testnet</span>
            {fingerprint ? <Link className="inline-flex min-h-11 shrink-0 items-center gap-1 whitespace-nowrap text-sm font-semibold text-accent" href={`/verify/${encodeURIComponent(fingerprint)}`}>Re-verify <ArrowUpRight aria-hidden size={16} /></Link> : null}
          </div>
        </div>
      </header>
      <div className="shell-width">
        <ol className="workflow-stages" aria-label="Provenance workflow">
          {stages.map((label, index) => <li key={label} aria-current={active === index ? "step" : undefined} className={active === index ? "stage-active" : ""}>
            <span className="stage-number" aria-hidden>{index < active ? <Check size={12} /> : index + 1}</span><span>{label}</span>
          </li>)}
        </ol>
      </div>
      <main id="main-content" className="shell-width main-content" tabIndex={-1}><MotionSurface motionKey={stage}>{children}</MotionSurface></main>
      <footer className="shell-width app-footer"><span>ChitraPramaan <span className="footer-divider">/</span> A clearer picture.</span><span>Visual resemblance does not confirm identity.</span></footer>
    </div>
  );
}
