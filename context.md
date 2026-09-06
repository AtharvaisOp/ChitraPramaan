# ChitraPramaan — Agent Context

> **Purpose:** Give any new coding/review agent enough context to understand the project, its intended semantics, the bugs already investigated/fixed, the current architecture, and the constraints that must not be accidentally broken.
>
> **Read this before changing production code.**

---

## 1. Project in one paragraph

**ChitraPramaan** is an image provenance and verification system. A user uploads a **consented photo**, the backend detects/selects a face, generates a deterministic face crop, sends that crop to **SerpApi / Google Lens** for reverse-image search, keeps results from an explicit supported social-domain allowlist, re-ranks those candidates with the same face-embedding model, and shows the ranked matches to the user. The user must **explicitly review and confirm a candidate** before the system builds a claim, pins the full claim JSON to **IPFS via Pinata**, and anchors the claim fingerprint + CID on an **Ethereum Sepolia Registry contract**. Later, anyone can independently read the Registry record, retrieve the IPFS claim, recompute the fingerprint, and verify whether the on-chain lookup key and fetched claim still match.

### Important semantic boundary

This project **does not prove a person’s identity**.

It proves a narrower statement:

> an image resembling the selected face appeared at a particular URL, and a claim recording that match existed by the time it was anchored on-chain.

A match is **not** proof of name, account ownership, consent by the depicted person, or that arbitrary photos show the same person.

---

## 2. High-level architecture

```text
frontend/       Next.js App Router UI
backend/        FastAPI adapter + process-local review sessions
pipeline/       shared installable provenance_pipeline package
cli/            terminal orchestration
scripts/        independent read-only re-verification
contracts/      Registry Solidity contract + tests + deployment
tests/          Python tests and local browser fixtures
```

### Shared logic

The **CLI and backend share the same pipeline package**. Avoid duplicating search, filtering, ranking, chain, or verification logic in adapters unless necessary.

### Current external systems

```text
Face detection / embeddings  -> InsightFace + ONNX Runtime
Reverse search               -> SerpApi Google Lens
Claim persistence            -> IPFS via Pinata
Blockchain                   -> Ethereum Sepolia
Frontend                     -> Next.js
Backend                      -> FastAPI / Uvicorn
```

---

## 3. Deployed Registry

- **Network:** Ethereum Sepolia
- **Chain ID:** `11155111`
- **Registry contract:** `0x1Df668fad717848a0A99Ed689B00203b14B4272B`
- Contract uses **first-seen semantics**.
- Anchoring the same fingerprint twice is intentionally rejected.
- This is a demo/testnet deployment, not a mainnet production authority.

Do not redeploy the contract casually. Existing runtime bytecode and ABI were checked during debugging and matched the repository deployment.

---

## 4. Core pipeline

### Search / analysis

```text
Upload photo
  ↓
Validate image bytes / format / size / dimensions
  ↓
Decode image
  ↓
Detect faces
  ↓
Select subject
  ↓
Deterministic face crop
  ↓
Compute crop SHA-256
  ↓
Compute embedding digest
  ↓
SerpApi Google Lens reverse search
  ↓
Supported social-domain filter
  ↓
Candidate thumbnail face embedding
  ↓
Cosine similarity re-ranking
  ↓
Return ranked candidates
```

### Human review / anchoring

```text
Ranked candidates
  ↓
Recommended candidate may be preselected
  ↓
ALWAYS show Select / Review UI
  ↓
User may choose another candidate
  ↓
Explicit "Confirm & Anchor"
  ↓
Build claim
  ↓
Pin complete claim JSON to IPFS
  ↓
Anchor fingerprint + CID on Sepolia
```

### Independent verification

```text
fingerprint
  ↓
Read Registry
  ↓
Get anchored CID
  ↓
Fetch claim JSON from IPFS
  ↓
Recompute fingerprint
  ↓
Compare fetched fingerprint with lookup key
  ↓
PASS / mismatch / unavailable
```

---

## 5. Claim fingerprint semantics

The stable fingerprint is SHA-256 over canonical JSON containing only:

```text
platform
normalized_post_url
crop_sha256
embedding_sha256
detector_model_version
```

Descriptive metadata stays in the claim envelope and does **not** affect the fingerprint, including things such as:

- title
- thumbnail URL
- similarity score
- selection method
- query time
- oracle-response hash
- original-image audit hash

Raw 512-dimensional embeddings are **not persisted**. Only their SHA-256 digests are recorded.

---

## 6. Deterministic crop policy

Current crop policy is intentionally deterministic:

- expand each side of selected face box by 30%
- clamp to image bounds
- resize to `320 × 320`
- fixed bilinear resizing
- JPEG quality 95
- fixed 4:2:0 subsampling

The crop hash binds the claim to the exact encoded crop bytes.

**Do not change crop policy casually.** A crop-policy change changes fingerprints.

---

## 7. Supported social sources

The current allowlist is intentionally narrow:

```text
x.com
twitter.com
instagram.com
facebook.com
linkedin.com
reddit.com
tiktok.com
```

Domain matching already handles proper subdomains safely:

```text
www.instagram.com   -> allowed
m.facebook.com      -> allowed
instagram.com       -> allowed

fakeinstagram.com                -> rejected
instagram.com.attacker.example   -> rejected
```

Do not expand the allowlist merely to make a demo image pass.

---

## 8. Search no-result behavior

This was a major debugging thread and is now intentionally separated into three cases.

### Case A — provider returns zero visual matches

Example provider response:

```json
{
  "error": "Google Lens hasn't returned any results for this query."
}
```

Expected user-facing result:

```text
No matching images were found for this photo. Try another photo.
```

### Case B — raw provider matches exist, but none are supported social sources

Expected:

```text
No supported source results were found. Try another photo.
```

### Case C — supported social candidates exist, but no candidate thumbnail has a usable face

Expected:

```text
No candidate thumbnails had a usable face. Try another photo.
```

### Important

- The known SerpApi no-results string is narrowly recognized.
- Auth, quota, rate limit, malformed response, timeout, and 5xx errors remain genuine provider errors.
- The CLI now exits cleanly for A/B/C instead of reaching `select_match()` with an empty list.
- `rerank([])` / `select_match([])` should not be reached unnecessarily.

---

## 9. Candidate selection UX

A previous bug caused `status === "auto_selected"` to immediately call `/confirm`, making the Select step useless.

That is now fixed.

### Required behavior

```text
POST /api/sessions -> 201
  ↓
Select page ALWAYS shown when candidates exist
  ↓
recommended candidate may be preselected
  ↓
user may choose another candidate
  ↓
ONLY explicit user click triggers /confirm
```

### Compatibility naming

The backend still uses existing compatibility terms such as:

```text
auto_selected
selection_method="auto"
selected_candidate.index
```

In the UI, these must be treated as **recommendation metadata only**.

They do **not** authorize automatic anchoring.

### Network acceptance check

After:

```text
POST /api/sessions -> 201
```

there must be **no `/confirm` request** until the user explicitly clicks **Confirm & Anchor**.

---

## 10. Verification request deduplication

A previous frontend bug caused two identical verification requests in Next.js development Strict Mode:

```text
GET /api/verify/<fingerprint>  (one browser request canceled)
GET /api/verify/<fingerprint>  (second request succeeds)
```

Even when the browser aborts the first request, backend/IPFS work may already have started, causing duplicated gateway traffic.

This is now fixed with **keyed in-flight request deduplication with subscriber-aware cancellation**.

### Required behavior

For one stable fingerprint:

```text
one logical GET /api/verify/<fingerprint>
```

If fingerprint changes:

```text
release/abort obsolete request
start exactly one request for new fingerprint
```

Do not “fix” this by globally disabling React Strict Mode.

---

## 11. IPFS verification reliability

The original verification backend always used:

```text
https://ipfs.io/ipfs
```

The public gateway returned 429 / timeout errors during real testing.

`dweb.link` was not treated as truly independent because it shares IPFS Foundation infrastructure/rate limits.

### Current gateway policy

Centralized in shared verification code:

1. `IPFS_GATEWAY_URL`, if configured
2. `IPFS_FALLBACK_GATEWAY_URL`, if configured and independent
3. otherwise bounded defaults:
   - `ipfs.io`
   - `gateway.pinata.cloud`

Only **two sequential attempts** are allowed.

### Availability failures that may trigger fallback

Examples:

```text
timeout
connection/network error
HTTP 408
HTTP 425
HTTP 429
HTTP 500
HTTP 502
HTTP 503
HTTP 504
```

### Failures that must NOT trigger gateway shopping

```text
invalid CID
bad gateway config
non-retryable HTTP error
invalid JSON
JSON not an object
malformed claim
bad fingerprint body
digest/fingerprint computation failure
fingerprint mismatch
```

A valid fetched claim whose recomputed fingerprint differs from the on-chain lookup key is a normal verification result:

```text
passed = false
```

It is **not** an infrastructure error and must not cause fallback attempts until “something matches”.

### Timeouts

Current bounded gateway timeout:

```text
connect: ~4s
read:    ~8s
```

Maximum two attempts.

---

## 12. Real verification smoke-test evidence

A previously anchored fingerprint was used for a read-only smoke test:

```text
2708d934f8355a9d88bf3838d280d529a52788b14d91009b582479c2a577735c
```

Registry lookup:

```text
exists = true
```

Anchored CID:

```text
bafkreiaq4iqgi7yqopuwd6vjgz72f4cxb6pthm4dnpyxbkfympthgpqqiq
```

Observed post-fix behavior:

```text
ipfs.io attempt -> timeout
independent Pinata gateway fallback -> success
/api/verify -> 200
passed = true
```

No new blockchain write was required for this smoke test.

---

## 13. Blockchain / wallet behavior

### Required backend secret

`PRIVATE_KEY` must be the **actual 32-byte Ethereum private key**, not the public wallet address.

A debugging incident occurred because a 20-byte public address had been placed in `PRIVATE_KEY`.

The original exception was effectively:

```text
The private key must be exactly 32 bytes long, instead of 20 bytes.
```

That is now handled with a focused sanitized server response instead of a vague generic 502.

### Safe behavior now includes

- private-key format failure classification
- insufficient-funds classification
- duplicate fingerprint pre-check
- first-seen semantics preserved
- no duplicate transaction preparation for already-anchored fingerprint
- unknown send/receipt outcomes remain protected from blind resubmission
- process-local pending-nonce lock retained

### Important uncertainty rule

If transaction broadcast outcome is uncertain:

> **Do not blindly retry / resubmit.**

The session should become an uncertain state and require read-only reconciliation.

---

## 14. IPFS pinning

Pinning uses Pinata and happens only during confirmation.

Secrets:

```text
PINATA_JWT
IPFS_API_KEY   # compatibility alias
```

Pinning and verification are deliberately separated:

- pinning may require Pinata credential
- independent verification should remain possible without that credential

Never forward `PINATA_JWT` to arbitrary public gateway hosts.

---

## 15. Environment variables

### Backend secrets / configuration

```text
SERPAPI_KEY
SEARCH_API_KEY              compatibility alias

RPC_URL

PRIVATE_KEY

PINATA_JWT
IPFS_API_KEY                compatibility alias

IPFS_GATEWAY_URL            preferred verification gateway
IPFS_FALLBACK_GATEWAY_URL   optional independent fallback

FRONTEND_ORIGIN
```

### Frontend browser-visible configuration

```text
NEXT_PUBLIC_API_BASE_URL
```

Only browser-safe values belong in `NEXT_PUBLIC_*`.

### Important local behavior

Historically, local `.env` values were not assumed to magically exist in every shell/process. Make sure production configuration is injected into the actual backend process.

Do not expose or log secret values.

---

## 16. Backend session model

Backend review state is currently **process-local and non-durable**.

Important consequences:

- use **one backend worker**
- restarting backend loses unconfirmed sessions
- state is not shared across multiple workers
- original upload bytes / query embeddings exist only while confirmation is pending
- sessions expire and are cleaned up
- session model includes lifecycle states such as:
  - ready
  - anchoring
  - anchored
  - uncertain

Do not configure multiple Uvicorn/Gunicorn workers unless session storage is moved to a shared store.

For demo deployment, one worker is acceptable if documented.

---

## 17. Upload safety

Existing upload rules include:

- JPEG / PNG / WebP only
- actual image decoding
- max upload size
- max megapixels (`25 MP`)
- decompression-bomb protection
- malformed image rejection
- no arbitrary file persistence expected

Do not weaken upload validation.

---

## 18. Outbound network / SSRF protections

The project already contains redirect/public-destination protections for provider URLs and thumbnails.

Keep protections against:

- localhost
- loopback
- private IP ranges
- link-local
- metadata/internal services
- redirect-to-private-host
- oversized streamed responses
- DNS rebinding risk where applicable

Warnings such as:

```text
Could not resolve source redirects; retaining normalized input
```

have appeared during normal runs and are not necessarily fatal.

Do not weaken network protections to make social links easier to follow.

---

## 19. Health endpoint

Current backend health endpoint reports safe configuration-level status similar to:

```json
{
  "status": "ok",
  "services": {
    "search": "configured",
    "ipfs": "configured",
    "blockchain": "configured"
  }
}
```

It should not expose secret values.

---

## 20. Public API endpoints

Key API surface:

```text
POST /api/sessions
POST /api/sessions/{session_id}/confirm
GET  /api/verify/{fingerprint}
GET  /api/health
```

### Semantics

`POST /api/sessions`
- consented upload
- validation
- face detection
- reverse search
- filtering
- ranking
- returns candidates/session

`POST /api/sessions/{id}/confirm`
- user-confirmed candidate only
- claim construction
- IPFS pin
- Sepolia anchor

`GET /api/verify/{fingerprint}`
- read-only Registry + IPFS verification

---

## 21. Important implementation files

### Search

```text
pipeline/src/provenance_pipeline/search/reverse_search.py
pipeline/src/provenance_pipeline/search/domain_filter.py
```

### Chain

```text
pipeline/src/provenance_pipeline/chain/client.py
pipeline/src/provenance_pipeline/chain/ipfs.py
```

### Verification

```text
pipeline/src/provenance_pipeline/verification.py
scripts/reverify.py
```

### Backend

```text
backend/main.py
```

### Frontend workflow

```text
frontend/components/workflow/workflow.tsx
frontend/components/workflow/match-review-screen.tsx
frontend/components/workflow/processing-screen.tsx
frontend/components/workflow/upload-screen.tsx
frontend/components/workflow/result-screen.tsx
```

### Frontend verification

```text
frontend/components/verify/verify-screen.tsx
```

### Frontend validation

```text
frontend/lib/validation.ts
```

---

## 22. Tests / known passing state

After the latest workflow + verification changes, reported test state was:

```text
Python non-integration suite:
131 passed, 2 integration tests deselected

Frontend:
23 passed

Frontend lint:
passed
```

Earlier focused chain/verification suites also passed after their respective fixes.

Before production changes, rerun current tests instead of trusting these historical counts blindly.

Recommended commands:

```powershell
python -m pytest -m "not integration"
```

Frontend:

```powershell
cd frontend
npm test
npm run lint
npm run build
```

Contract:

```powershell
npm run contract:test
npm run contract:compile
```

Do not run paid/live integration tests unless deliberately requested.

---

## 23. Local development commands

Backend:

```powershell
uvicorn backend.main:app --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

Frontend:

```text
http://localhost:3000
```

Production must **not** use `--reload`.

---

## 24. Python compatibility

Repository documentation prefers:

```text
Python 3.11 or 3.12
```

Local debugging was performed on Python 3.13 and passed tests, but InsightFace/skimage emitted deprecation warnings.

Do not treat those warnings as the cause of unrelated runtime failures.

For deployment, prefer a documented supported Python version.

---

## 25. Known UX / behavioral invariants

Agents should preserve these:

1. User sees candidate review before anchoring.
2. Recommendation does not auto-anchor.
3. User can choose a non-recommended candidate.
4. Confirm button sends selected backend candidate index.
5. Confirm is protected against double submission.
6. Verification should issue one logical request per stable fingerprint.
7. Verification mismatch is a result, not a 502.
8. Infrastructure unavailability is not an integrity failure.
9. No face / no matches / unsupported matches / unusable thumbnails remain separate cases.
10. Existing successful pipeline behavior should remain unchanged unless a concrete bug is proven.

---

## 26. Security invariants

Do not:

- expose `PRIVATE_KEY`
- expose `PINATA_JWT`
- expose SerpApi key
- expose authenticated RPC URL
- put secrets in `NEXT_PUBLIC_*`
- log raw embeddings
- log uploaded image bytes
- log signed raw transactions
- commit `.env`
- disable TLS verification
- weaken SSRF protections
- weaken CID validation
- expand social allowlist just for demo success
- bypass fingerprint recomputation
- treat mismatch as gateway failure
- blindly resubmit uncertain blockchain transactions

---

## 27. Production-readiness concerns still worth reviewing

The project works end-to-end, but a separate production-readiness audit should verify/harden these areas without redesigning working behavior.

### Authentication / abuse protection

The demo API may consume:

- SerpApi quota
- Pinata operations
- Sepolia gas

A public deployment should not allow unlimited anonymous expensive calls.

Review minimal protections such as:

- deployment-layer auth
- API auth
- request rate limiting
- per-IP limits
- session/action limits

Do not invent a full user-account system unless required.

### Process-local sessions

For a serious multi-instance/multi-worker deployment, sessions need a shared durable store such as Redis/SQLite/Postgres.

For a demo or single-instance deployment, one worker can be acceptable if documented.

### Deployment

Likely clean deployment split:

```text
Frontend  -> Vercel or equivalent Next.js host
Backend   -> long-running Python container/server
Chain     -> Sepolia
Pinning   -> Pinata
Search    -> SerpApi
```

InsightFace/model loading makes a normal long-running backend more natural than a tiny serverless function.

### Production build / security checks

Before calling it production-ready, verify:

- backend startup on supported Python
- frontend `npm run build`
- frontend lint/tests
- Python tests
- contract compile/tests
- exact production CORS
- no real secrets committed
- outbound request timeouts
- upload limits
- auth/rate/cost protections
- one-worker deployment constraint
- production startup command
- `DEPLOYMENT.md` or equivalent instructions

---

## 28. Good demo explanation

> ChitraPramaan is an image provenance and verification system. A consented photo is analyzed, reverse-searched, and re-ranked against supported social-source candidates using face embeddings. The user reviews the candidate before confirming it. The resulting claim is pinned to IPFS and its cryptographic fingerprint is anchored on Ethereum Sepolia, producing a timestamped, tamper-evident record. Later, anyone can independently read the blockchain record, retrieve the IPFS claim, recompute the fingerprint, and verify whether the evidence still matches. It does not claim to prove a person’s identity; it proves the existence and integrity of the recorded image-match evidence.

### Example uses

- fake-profile investigation
- social-media evidence collection
- journalism / misinformation investigation
- brand/person impersonation cases
- digital forensics
- proving integrity and timestamped existence of a captured image-match claim

---

## 29. Agent working rules

When debugging:

1. **Prove the failing stage before changing code.**
2. Separate configuration failure, provider availability, parser bug, policy/filter result, integrity mismatch, and chain write failure.
3. Preserve sanitized user-facing errors.
4. Put useful low-risk detail in server logs, not browser responses.
5. Avoid broad refactors.
6. Prefer focused regression tests for the exact bug.
7. Run full relevant tests after the focused fix.
8. Do not spend paid provider quota when mocks can prove logic.
9. Use read-only chain/IPFS checks before attempting new writes.
10. If current behavior is correct by policy, do not “fix” it merely to force a demo result.

---

## 30. Current status summary

At the end of the debugging work represented by this context:

```text
Upload validation             working
InsightFace                    working
Google Lens search             working
Social filtering               working
Candidate ranking              working
Recommendation                 working
Manual candidate selection     fixed / working
Explicit confirmation          fixed / working
IPFS pinning                   working
Sepolia signing                fixed / working
Sepolia anchoring              working
Duplicate-anchor handling      hardened
Registry lookup                working
IPFS verification fallback     fixed / working
Availability vs integrity      separated
Duplicate verify suppression   fixed / working
CLI no-result handling         fixed / working
```

The next major activity should be **production-readiness review/hardening**, not another redesign of the working core pipeline.
