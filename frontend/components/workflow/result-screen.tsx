import { ArrowSquareOut, CheckCircle, MagnifyingGlass } from "@phosphor-icons/react";
import Link from "next/link";
import { CopyValue } from "@/components/shared/copy-value";
import { formatScore, shortFingerprint } from "@/lib/format";
import { ipfsGatewayUrl, safeHttpUrl } from "@/lib/platform";
import type { ConfirmResponse } from "@/lib/types";

export function ResultScreen({ result, onStartOver }: { result: ConfirmResponse; onStartOver: () => void }) {
  const gateway = ipfsGatewayUrl(result.cid);
  const explorer = safeHttpUrl(result.explorer_link);
  const method = result.selection_method === "auto" ? "Recommended match confirmed" : "Selected by you";

  return (
    <section aria-labelledby="result-heading">
      <p className="evidence-kicker mb-4">Provenance record / Sepolia</p>
      <div className="flex items-start gap-4 border-b border-line pb-8">
        <CheckCircle aria-hidden size={34} weight="fill" className="mt-1 shrink-0 text-success" />
        <div>
          <h1 id="result-heading" className="text-3xl font-semibold tracking-tight sm:text-4xl">Claim anchored</h1>
          <p className="mt-3 text-muted">{method} - similarity {formatScore(result.score)}</p>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Your selected provenance claim is pinned to IPFS and its fingerprint is recorded on Ethereum Sepolia. Re-verify to independently check the public record.</p>
        </div>
      </div>

      <div className="mt-7 flex flex-col gap-3 sm:flex-row">
        <Link href={`/verify/${encodeURIComponent(result.fingerprint)}`} className="button-like inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 font-semibold text-white hover:bg-accent-hover dark:text-zinc-950">
          <MagnifyingGlass aria-hidden size={19} weight="bold" />
          Re-verify
        </Link>
        <button type="button" onClick={onStartOver} className="min-h-11 rounded-lg border border-line bg-surface px-5 py-2.5 font-semibold hover:bg-surface-subtle">
          Analyze another photo
        </button>
      </div>

      <div className="evidence-layout mt-8">
      <div className="grid min-w-0 gap-6">
        <div>
          <p className="mb-2 text-sm font-semibold">Fingerprint</p>
          <p className="mb-3 font-mono text-sm text-muted">{shortFingerprint(result.fingerprint)}</p>
          <CopyValue label="Full fingerprint" value={result.fingerprint} />
        </div>
        <div>
          <p className="mb-2 text-sm font-semibold">IPFS claim</p>
          <CopyValue label="CID" value={result.cid} />
          {gateway ? (
            <a href={gateway} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-2 rounded-lg text-sm font-medium text-accent hover:text-accent-hover">
              Open pinned claim <ArrowSquareOut aria-hidden size={16} />
            </a>
          ) : <p className="mt-3 text-sm text-muted">Gateway link unavailable</p>}
        </div>
        <div>
          <p className="mb-2 text-sm font-semibold">Sepolia transaction</p>
          <CopyValue label="Transaction hash" value={result.tx_hash} />
          {explorer ? (
            <a href={explorer.toString()} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-2 rounded-lg text-sm font-medium text-accent hover:text-accent-hover">
              View on Sepolia Etherscan <ArrowSquareOut aria-hidden size={16} />
            </a>
          ) : <p className="mt-3 text-sm text-muted">Explorer link unavailable</p>}
        </div>
      </div>

      <aside className="evidence-summary" aria-label="Provenance timeline">
        <p className="evidence-kicker">Recorded evidence</p>
        <h2 className="mt-3 text-lg font-semibold">The claim’s path</h2>
        <ol className="evidence-timeline">
          <li>Image analyzed<small>Face crop and visual comparison</small></li>
          <li>Candidate selected<small>{method} · Score {formatScore(result.score)}</small></li>
          <li>Fingerprint generated<small>SHA-256 of fingerprint_body only</small></li>
          <li>Claim pinned to IPFS<small>Full claim available by CID</small></li>
          <li>Anchored on Sepolia<small>Confirmed transaction receipt</small></li>
        </ol>
        <p className="mt-6 border-t border-line pt-4 text-xs leading-6 text-muted">The record establishes this claim’s existence. It does not establish identity or ownership. The block timestamp is available through Re-verify.</p>
      </aside>
      </div>

    </section>
  );
}
