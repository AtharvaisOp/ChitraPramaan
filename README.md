# ChitraPramaan
### Image Provenance & Verification

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/node-LTS-339933?logo=node.js&logoColor=white)
![Network](https://img.shields.io/badge/network-Sepolia%20testnet-8A2BE2?logo=ethereum&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/frontend-Next.js-000000?logo=next.js&logoColor=white)
![Status](https://img.shields.io/badge/status-demo%20%2F%20not%20audited-D97706)

**ChitraPramaan** ("image proof" in Hindi/Marathi) proves one narrow, auditable statement:

> An image resembling a selected face appears at a particular URL, and a claim recording that match existed by the time it was anchored on-chain.

That statement is deliberately modest. **A match is not identity confirmation.** It does not prove the person's name, ownership of an account, consent by the depicted person, or that two arbitrary photos show the same person. Everything below is built around keeping that boundary honest.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Deployed registry](#deployed-registry)
- [Getting started](#getting-started)
- [Quickstart — CLI](#quickstart--cli)
- [Pipeline walkthrough](#pipeline-walkthrough)
- [Claim binding & crop policy](#claim-binding--crop-policy)
- [Running the full-stack app](#running-the-full-stack-app)
- [FastAPI backend](#fastapi-backend)
- [Re-verify independently](#re-verify-independently)
- [Safe browser demo fixtures](#safe-browser-demo-fixtures)
- [Tests](#tests)
- [Design invariants](#design-invariants)
- [Security practices](#security-practices)
- [Known limitations](#known-limitations)
- [Production-hardening roadmap](#production-hardening-roadmap)
- [Example uses](#example-uses)

---

## What it does

The CLI takes a **consented photo**, detects and selects a face, creates a deterministic crop, uploads that crop to a reverse-image-search provider, filters results to an explicit social-domain allowlist, re-ranks candidate thumbnails with the same face-embedding model, and builds a claim. A human always reviews the ranked candidates and explicitly confirms one before anything is written anywhere. The confirmed claim is pinned to IPFS and its fingerprint/CID pair is anchored in a Registry smart contract on Ethereum Sepolia — producing a timestamped, tamper-evident record that anyone can later re-check without needing any of the original credentials.

**Where this is useful:** fake-profile investigation, social-media evidence collection, journalism and misinformation research, brand or person impersonation cases, and general digital forensics where you need to *prove the existence and integrity* of a recorded image-match claim — not the identity behind it.

## Architecture

<img src="assets/architecture.svg" alt="ChitraPramaan system architecture: CLI and Next.js frontend both sit on top of a shared pipeline package, which talks to InsightFace, SerpApi, Pinata, and the Sepolia Registry contract; a separate read-only verifier only touches IPFS and Sepolia." width="100%"/>

The CLI and backend **import the same pipeline package** — search, filtering, ranking, chain, and verification logic lives once, in `pipeline/`, so the two adapters can't drift apart. Search, wallet, and IPFS credentials are server-side only and are never exposed to browser code; the frontend's only environment variable is `NEXT_PUBLIC_API_BASE_URL`.

## Repository layout

| Path | Contents |
|---|---|
| `pipeline/` | Installable `provenance_pipeline` package — shared pipeline logic only |
| `cli/` | Terminal orchestration and consent/selection prompts |
| `backend/` | FastAPI adapter and process-local review sessions |
| `frontend/` | Next.js guided provenance and re-verification workflow |
| `scripts/` | Independent, read-only re-verification |
| `contracts/` | Registry Solidity source, tests, deploy script, and deployed address |
| `tests/` | Python unit and opt-in integration tests |

## Deployed registry

| | |
|---|---|
| **Network** | Ethereum Sepolia (chain ID `11155111`) |
| **Contract** | [`0x1Df668fad717848a0A99Ed689B00203b14B4272B`](https://sepolia.etherscan.io/address/0x1Df668fad717848a0A99Ed689B00203b14B4272B) |
| **Deployment tx** | [`0x0811d433ccb247c4a853cc9805354da118d8dd457d91b13265aecaedb094f643`](https://sepolia.etherscan.io/tx/0x0811d433ccb247c4a853cc9805354da118d8dd457d91b13265aecaedb094f643) |
| **Semantics** | First-seen — anchoring the same fingerprint twice reverts |

This is a testnet deployment with **no monetary or identity authority**.

## Getting started

**Prerequisites:** Python 3.11 or 3.12, and a current Node.js LTS release.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\pipeline[face,dev]"
npm install
npm run contract:compile
```

The base package installs independently with `python -m pip install -e ./pipeline`; the `face` extra adds InsightFace and ONNX Runtime, and `dev` adds pytest. InsightFace may download the `buffalo_l` model on its first detection run. Contract compilation doesn't depend on Python packaging and validates the Solidity source before deployment.

### Environment variables

Four secrets drive the pipeline:

| Variable | Purpose | Where to get it |
|---|---|---|
| `SERPAPI_KEY` (alias `SEARCH_API_KEY`) | Uploads the deterministic crop and requests Google Lens visual matches | [SerpApi sign-up](https://serpapi.com/users/sign_up) → [Manage API Key](https://serpapi.com/manage-api-key) |
| `RPC_URL` | Connects to Ethereum Sepolia for the anchor transaction | A Sepolia endpoint from [Alchemy](https://dashboard.alchemy.com/), Infura, or QuickNode — use a dedicated write endpoint |
| `PRIVATE_KEY` | Signs the Sepolia anchor transaction | A **dedicated testnet-only account's** exported key (never a mainnet key) — [MetaMask export guide](https://support.metamask.io/configure/accounts/how-to-export-an-accounts-private-key/); fund it from a [Sepolia faucet](https://ethereum.org/developers/docs/networks/#sepolia). Must be the raw 32-byte key, not the public address |
| `PINATA_JWT` (alias `IPFS_API_KEY`, same value) | Pins the full claim JSON via Pinata's [`pinJSONToIPFS`](https://docs.pinata.cloud/api-reference/endpoint/ipfs/pin-json-to-ipfs) | [Pinata API Keys](https://app.pinata.cloud/developers/api-keys) |

Read-only verification (API and CLI) instead uses `IPFS_GATEWAY_URL` (preferred) and an optional `IPFS_FALLBACK_GATEWAY_URL` — both must end in `/ipfs`, hold no CID or credentials, and are never used with `PINATA_JWT`.

Copy the root `.env.example` as a reference, then set real values for the current shell only:

```powershell
$env:SERPAPI_KEY = "your-serpapi-key"
$env:RPC_URL = "your-sepolia-rpc-url"
$env:PRIVATE_KEY = "your-testnet-wallet-private-key"
$env:PINATA_JWT = "your-pinata-jwt"
```

The deployed contract address is already in `contracts/deployed_address.txt` and packaged as the pipeline's Sepolia fallback — set `CONTRACT_ADDRESS` only to deliberately target another compatible deployment. Local `.env` files are git-ignored; the backend auto-loads the repo-root `.env` for local dev, while deployment platforms should inject environment variables directly.

## Quickstart — CLI

Run the complete search → claim → IPFS pin → Sepolia anchor pipeline on the included sample photo:

```powershell
python cli/run.py --photo Images/phase-2-crop.jpg --network sepolia
```

The CLI first confirms you have the right to search the web using the photo. If multiple faces are found, it asks which one to use; if the best match is below the cosine threshold, it asks you to choose from the ranked candidates. On success it writes `Images/phase-2-crop.claim.json` and prints the fingerprint, selection method and score, IPFS CID, transaction hash, and Etherscan link.

Add `--dry-run` to exercise the pipeline without pinning or spending Sepolia ETH. `--auto-threshold FLOAT` overrides the documented default (currently `0.60`), which needs empirical tuning for the configured embedding space.

## Pipeline walkthrough

<img src="assets/pipeline-flow.svg" alt="Three-stage flow: Search and Analyze produces ranked candidates; Human Review and Anchor requires an explicit confirm before pinning to IPFS and anchoring on Sepolia; Independent Verification re-reads the registry and IPFS to report PASS, mismatch, or unavailable." width="100%"/>

**1 · Search & analyze.** The upload is validated and decoded, a face is detected and the subject selected (deterministic area-times-detection-score policy for multi-face photos), a fixed-policy crop is produced, SerpApi runs the reverse image search, results are filtered to the social-domain allowlist, and surviving candidate thumbnails are re-ranked by cosine similarity against the same face embedding.

**2 · Human review & anchor.** The ranked candidates are *always* shown — a recommendation being pre-selected never triggers anchoring by itself. Only an explicit user confirmation builds the claim, pins it to IPFS, and anchors it on Sepolia.

**3 · Independent verification.** Anyone can later look up the fingerprint on the Registry, fetch the claim from IPFS, recompute the fingerprint locally, and compare it against the on-chain lookup key. A mismatch is reported as a normal result — not an infrastructure failure — and gateway unavailability is never confused with an integrity problem.

## Claim binding & crop policy

The stable `fingerprint_body` is SHA-256 over canonical JSON containing **only**:

```text
platform, normalized_post_url, crop_sha256, embedding_sha256, detector_model_version
```

Descriptive metadata — title, thumbnail URL, similarity score, selection method, query time, oracle-response hash, original-image audit hash — lives in a separate `envelope` and never affects the fingerprint. Raw 512-dimensional embeddings are **never persisted**; only their SHA-256 digests are recorded.

The current deterministic crop policy: expand each side of the selected bounding box by 30%, clamp to the image, resize to 320×320 with fixed bilinear settings, encode JPEG at quality 95 with fixed 4:2:0 subsampling. The hash binds the claim to those exact encoded crop bytes — **changing the crop policy changes every future fingerprint**, so it isn't something to adjust casually.

## Running the full-stack app

Start the backend from the repository root:

```powershell
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload  # development only; production uses --workers 1
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The app guides a consented upload through processing, conditional match review, IPFS pinning, testnet anchoring, and independent re-verification. The backend's default CORS allowlist covers the local frontend origins; set `FRONTEND_ORIGIN` to an exact deployed origin when hosting elsewhere.

## FastAPI backend

Interactive docs are available at `http://127.0.0.1:8000/docs` once the server is running.

| Endpoint | Behavior |
|---|---|
| `POST /api/sessions` | Consented upload → validation → face detection → reverse search → filtering → ranking → returns candidates/session |
| `POST /api/sessions/{session_id}/confirm` | The **only** operation that pins to IPFS or writes to Sepolia — user-confirmed candidate only |
| `GET /api/verify/{fingerprint}` | Read-only Registry + IPFS comparison |
| `GET /api/health` | Safe configuration-level status (never exposes secret values) |

Review state is **process-local and non-durable** — one process's memory, lost on restart, not shared across multiple Uvicorn workers. Sessions expire after 30 minutes (a cleanup task runs every minute, capped at 100 retained sessions). Original upload bytes and the raw query embedding exist only while confirmation is pending and are cleared on success, an uncertain transaction outcome, or expiry.

## Re-verify independently

A third party only needs Python dependencies, the saved claim JSON, and the contract address — **not** the search key, face model, source photo, wallet/private key, or Pinata key:

```powershell
python scripts/reverify.py --claim path/to/claim.json --contract 0x1Df668fad717848a0A99Ed689B00203b14B4272B
```

The verifier recomputes the local fingerprint, looks it up in the Registry, downloads the anchored CID through a public IPFS gateway, recomputes the fetched claim's fingerprint, and reports whether all three views match. It defaults to a no-key public Sepolia RPC and the public `ipfs.io` gateway (falling back to `gateway.pinata.cloud` on availability failures only, in at most two sequential attempts). `--rpc-url` and `--gateway` are optional reliability overrides, not pipeline API keys.

## Safe browser demo fixtures

`tests/browser_fixture.py` is a separate, localhost-only test API with no pipeline imports or external integrations — it must **never** replace the real backend in deployment.

```powershell
python -m uvicorn tests.browser_fixture:app --host 127.0.0.1 --port 8765
# In a separate PowerShell, from frontend/:
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8765"
node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3001
```

Open `http://localhost:3001` and use `tests/visual-fixtures/human.png`, `auto.png`, or `error.png` (synthetic test drawings). Verification fixtures: 64 `a` characters = PASS, `c` = mismatch, `d` = missing record, `e` = gateway error. All chain/IPFS values shown in this mode are fixtures — remove the environment override before running the real app. See `REVIEW.md` for the review scope and validation record.

## Tests

Unit tests mock external search, IPFS, and chain calls. Integration tests are opt-in because they consume provider quota and Sepolia gas.

```powershell
python -m pytest -m "not integration"
npm run contract:test
```

Run integration tests deliberately, with credentials configured:

```powershell
python -m pytest -m integration
```

## Design invariants

These UX guarantees hold across the pipeline and are worth knowing before you touch the workflow:

- The user always sees candidate review before anchoring — a recommendation never auto-anchors.
- The user can choose a non-recommended candidate; the confirm action sends the selected index explicitly.
- Confirmation is protected against double submission, and an uncertain broadcast/receipt blocks further writes from that session rather than retrying blindly.
- Verification issues exactly one logical request per stable fingerprint, even under React Strict Mode's double-invocation in development.
- A verification mismatch is a result (`passed = false`), never a 502 — infrastructure unavailability and evidence integrity are always kept separate.
- No face found, no matches, unsupported-source matches, and unusable thumbnails are three distinct, clearly messaged cases — not one generic failure.

## Security practices

- Search, wallet, and IPFS credentials never reach the browser — the frontend's only environment variable is `NEXT_PUBLIC_API_BASE_URL`.
- Raw embeddings, uploaded image bytes, and signed raw transactions are never logged.
- Outbound requests to provider/thumbnail URLs are checked for public DNS destinations on each redirect with a bounded, streamed download — deploy behind outbound network restrictions for full protection against DNS rebinding and internal/metadata services.
- CORS is not authentication — `FRONTEND_ORIGIN` narrows origins but a public multi-tenant deployment still needs its own auth and rate limiting.
- The social-source allowlist and CID validation are not meant to be widened or weakened just to make a demo pass.
- Don't expose this demo API on the public internet unauthenticated — it can spend server-funded provider quota and Sepolia gas.

## Known limitations

- Reverse search is an external oracle — its indexing, ranking, coverage, and thumbnail availability are opaque to this project, and provider quota exhaustion or upstream changes can yield no candidates even when a matching post exists.
- A claim is bound to one URL, model version, embedding digest, and the documented crop policy — it is not a durable claim about "the person" in the abstract, and any of those changing produces a different fingerprint.
- Face similarity is probabilistic; the recommendation threshold is embedding-space- and dataset-dependent, so both false matches and missed matches remain possible. A recommendation is always reviewed and explicitly confirmed before anchoring.
- The consent prompt is a required operational guard, not proof that consent was validly obtained.
- Public RPC and IPFS gateways are best-effort infrastructure — independent verification can be retried with another endpoint without changing the claim.
- Backend review sessions are process-local and non-durable; multi-worker deployments need a shared state store such as SQLite or Redis.
- The Registry and deployment are for demonstration on a public testnet and have not been presented as an audited production system.

## Production-hardening roadmap

The project works end-to-end; a separate production-readiness pass is what's left before wider deployment:

- **Auth & abuse protection** — the demo API can consume SerpApi quota, Pinata operations, and Sepolia gas with no request limits. A public deployment needs deployment- or API-layer auth plus per-IP/session rate limiting, without necessarily building a full account system.
- **Durable session storage** — a serious multi-instance deployment needs sessions moved to Redis/SQLite/Postgres; a single-worker demo can remain acceptable if documented as such.
- **Suggested deployment split** — frontend on Vercel or equivalent, backend as a long-running Python container (InsightFace's model loading fits a long-running process better than serverless), chain on Sepolia, pinning via Pinata, search via SerpApi.
- **Pre-launch checklist** — supported Python startup, `npm run build` + frontend lint/tests, Python tests, contract compile/tests, exact production CORS, no committed secrets, outbound timeouts, upload limits, auth/rate/cost protections, the one-worker constraint, a documented production start command, and a `DEPLOYMENT.md`.

## Example uses

- Fake-profile investigation
- Social-media evidence collection
- Journalism / misinformation investigation
- Brand or person impersonation cases
- Digital forensics
- Proving the integrity and timestamped existence of a captured image-match claim

---

<sub>ChitraPramaan is a demo/testnet system. It has not been presented as an audited production system, and no license file is currently included in the repository.</sub>