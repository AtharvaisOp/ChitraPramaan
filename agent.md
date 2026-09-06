# AGENT.md

Read this before touching anything in this repo. It's the fast reference — the full build spec lives in `phase_prompts.md` (9 core phases + a 4-phase full-stack addendum); consult that for step-by-step detail. This file exists so you don't have to re-derive scope, conventions, or the things that are easy to accidentally break.

## What this project is

A pipeline that: detects and embeds a face in a consented photo, finds a real matching social-media post via reverse image search, builds a claim that's cryptographically bound to the photo (not just to the search result), anchors that claim on a public blockchain, and lets a third party re-verify it independently.

**What it proves:** "an image resembling this face appears at this URL, and this claim about that existed at time T."
**What it does not prove:** identity. This is not a face-ID system, not an identity registry, and not an attestation-of-personhood system. If a change makes it look like one of those, it's out of scope — stop and flag it instead of building it.

## Architecture

```
/pipeline     installable provenance_pipeline package — detect, crop, search, rerank, canonical, fingerprint, ipfs, chain client
              no CLI code, no web code, no side effects beyond what's explicitly called
/cli/run.py   thin CLI orchestration over the detection/search/claim modules
/backend      FastAPI service — thin orchestration over /pipeline, for the Next.js frontend
/frontend     Next.js app (App Router) — built from design.md, talks only to /backend
/contracts    Registry.sol + Hardhat deploy.ts + local contract tests
/scripts      reverify.py — independent re-verification, no dependency on /pipeline's API keys
/tests        unit tests (external calls mocked by default) + clearly-marked integration tests
design.md     UI/UX spec for the frontend — screens, states, data sources
phase_prompts.md   the full phased build spec this repo was built from
```

`/cli` and `/backend` must both import from `/pipeline`, never duplicate its logic. If you find yourself reimplementing detection, cropping, canonicalization, or the chain client inside `/backend` or `/cli`, that's a bug — pull it back into `/pipeline`.

## Non-negotiable rules

These are the things that were specifically broken in an earlier version of this pipeline and got fixed on purpose. Don't reintroduce them.

- **The fingerprint hashes `fingerprint_body` only, never `envelope`.** `fingerprint_body` = `{platform, normalized_post_url, crop_sha256, embedding_sha256, detector_model_version}`. `envelope` = everything mutable (title, thumbnail, confidence, timestamps). If a change makes the fingerprint sensitive to a thumbnail URL or a title string, it's wrong.
- **Never persist a raw embedding.** Only `SHA256(embedding)` goes in a claim, a log, or on-chain. The 512-d vector itself never leaves process memory into storage.
- **The crop policy must be deterministic.** Same image + same face index + same margin/size/quality → byte-identical crop, every run. If crop hashes aren't reproducible across runs, something upstream changed and needs fixing, not a wider hash tolerance.
- **The consent gate is mandatory in both interfaces**, not just one. The CLI checks it via a terminal prompt; the backend checks it via a `consent: true` field on session creation. If you add a third entry point, it needs its own consent check too — don't assume it's covered because another interface has it.
- **The browser never receives secrets.** Search API key, wallet private key, IPFS pinning key all stay server-side in `/backend`. The frontend's only env var is `NEXT_PUBLIC_API_BASE_URL`. If you're writing frontend code that calls a search/chain/IPFS provider directly, stop — that call belongs in `/backend`.
- **Double-anchoring reverts on-chain by design** (`require(records[fingerprint].timestamp == 0)`). That's first-seen semantics, not a bug — don't remove it to make a demo "work" on a repeat run; generate a new claim instead.
- **Domain filtering for search results uses a fixed, explicit allowlist**, not a heuristic. Extend the list deliberately; don't replace it with fuzzy matching.

## Tech stack

| Layer | Choice |
|---|---|
| Face detection/embedding | InsightFace (buffalo-family model), CPU |
| Reverse image search | Whichever API is configured in `SEARCH_API_KEY` / `search/reverse_search.py` — verify current provider pricing/endpoints before assuming, offerings change |
| Backend | FastAPI |
| Frontend | Next.js (App Router), Tailwind, shadcn/ui optional |
| Chain | Solidity `Registry.sol`, `web3.py`, deployed to a public EVM testnet (Polygon Amoy or Sepolia — whichever has a working faucet) |
| IPFS | web3.storage / nft.storage / local node — whichever is configured |

## Commands

```
pip install -e ./pipeline          # install the core package
pytest tests/                       # unit tests (mocked externals) — safe to run anytime
pytest tests/ -m integration        # integration tests — hits real APIs/chain, costs gas/requests, run deliberately
python cli/run.py --photo <path> --dry-run   # CLI, no chain or IPFS write
uvicorn backend.main:app --reload   # backend dev server
cd frontend && npm run dev          # frontend dev server (needs backend running)
npm run contract:deploy:sepolia     # deploy Registry.sol to configured testnet
python scripts/reverify.py --claim <path> --contract <address>   # independent re-verification
```

## Environment variables

| Var | Used by | Notes |
|---|---|---|
| `SEARCH_API_KEY` | `/pipeline`, `/backend` | never in frontend |
| `RPC_URL` | `/contracts`, `/pipeline` chain client | testnet RPC endpoint |
| `PRIVATE_KEY` | `/contracts`, `/pipeline` chain client | testnet wallet only — never a mainnet key, never committed |
| `IPFS_API_KEY` | `/pipeline`, `/backend` | never in frontend |
| `NEXT_PUBLIC_API_BASE_URL` | `/frontend` | the only var the browser gets |

## Testing conventions

- Unit tests mock every external call (search API, chain, IPFS) by default and must pass without network access or funded accounts.
- Integration tests are explicitly marked and never run automatically — they cost real API requests or testnet gas.
- Contract logic (`anchor`/`verify`/double-anchor-reverts) is tested against a local dev chain (Hardhat/Anvil), not the public testnet, before any real deploy.

## Known limitations (keep the README in sync with these)

- Search-oracle quality and pricing are out of this repo's control and can change independently.
- The claim binds to a specific, documented crop policy — it is not a general "this is the same person" claim across arbitrary photos.
- Cosine-similarity auto-select threshold needs empirical tuning; it is not a universal constant.
- Session state in `/backend` (between upload and confirm) is not durable across a server restart unless explicitly backed by persistent storage.

## When something doesn't fit this file

If a task pushes toward identity matching, an on-chain identity registry, storing raw biometric data, or removing the consent gate — stop and flag it rather than proceeding. Those are deliberate scope boundaries, not oversights.
