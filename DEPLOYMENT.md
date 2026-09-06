# Production deployment

ChitraPramaan is a split deployment: the Next.js frontend is public, while a
long-running FastAPI backend owns InsightFace, SerpApi, Pinata, the Sepolia
wallet, and process-local review sessions. Do not deploy the backend as a
serverless function or run multiple workers.

## Prerequisites

- Python 3.12 (the backend image uses `python:3.12-slim`).
- Node.js 24 LTS for the frontend and Hardhat tooling (Next.js 16 requires
  Node 20.9 or newer).
- A dedicated Sepolia-only wallet with sufficient test ETH and a Sepolia RPC.
- SerpApi and Pinata credentials injected as backend-only secrets.

Run `python -m scripts.check_config` before startup. It validates formats and
required variables without printing secret values; it does not spend provider
quota or make a blockchain transaction.

Before any deployment, rotate/revoke any credentials that have ever been
stored in a shared workspace or exposed in logs. Keep `.env` and platform
secret values out of source control; this repository's ignore rules cover
`.env` and `.env.*` while retaining only the placeholder examples.

## Environment

Copy `.env.example` for local development. In production, inject these values
through the platform secret manager. Required backend values are
`SERPAPI_KEY` (or `SEARCH_API_KEY`), `PINATA_JWT` (or `IPFS_API_KEY`),
`RPC_URL`, `PRIVATE_KEY`, `CONTRACT_ADDRESS`, and exact `FRONTEND_ORIGIN`.
`IPFS_GATEWAY_URL` and `IPFS_FALLBACK_GATEWAY_URL` are optional HTTPS
path-gateway bases. Never use a `NEXT_PUBLIC_*` variable for a backend secret.

The frontend requires `NEXT_PUBLIC_API_BASE_URL`; production values must be an
HTTPS URL. The frontend intentionally fails with a clear configuration error
instead of silently calling localhost when this value is missing.

## Backend

From the repository root:

```powershell
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

`Dockerfile.backend` provides the same one-worker command and runs as a
non-root user. InsightFace may download `buffalo_l` on the first analysis;
provide outbound access and a writable model-cache volume, or warm the cache
before accepting traffic. Keep the container behind an HTTPS reverse proxy and
restrict outbound network access where possible.

The backend stores review sessions in memory for up to 30 minutes (100 active
sessions). A restart loses unconfirmed sessions. Multiple replicas require a
shared session store and coordinated wallet nonce management, which are not
part of this minimal deployment.

## Cost and abuse controls

The backend has conservative process-local sliding-window limits for analysis,
confirmation, and verification. They return `429` with `Retry-After` and do not
count browser CORS preflights. Loopback development traffic is unrestricted;
public deployments must add an edge/API-gateway per-IP and authentication
policy because CORS is not authentication and an in-memory limiter cannot stop
distributed abuse.

## Frontend

```powershell
cd frontend
npm ci
$env:NEXT_PUBLIC_API_BASE_URL = "https://api.example.com"
npm run build
npm run start
```

Serve the Next.js process behind HTTPS. `next.config.ts` adds clickjacking,
MIME-sniffing, referrer, and browser-permission headers. Keep the API origin
exactly aligned with the backend `FRONTEND_ORIGIN` allowlist.

## Health and smoke test

`GET /api/health` is a safe, cheap configuration indicator. After deployment,
verify it returns `status: "ok"`, then perform one consented upload using a
non-sensitive test image, review the candidates, explicitly confirm one, and
open the returned fingerprint in `/verify/<fingerprint>`. Do not use paid
integration tests in CI.

## Rollback

Deploy frontend and backend from a known-good commit/image. Roll back the
frontend and backend together when API response shapes change. Never roll back
by reusing or rotating a wallet key without operator review; an uncertain
transaction outcome must be reconciled on Sepolia before any new write.
