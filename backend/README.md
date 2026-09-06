# Backend

This FastAPI service is a thin HTTP adapter over the installable
`provenance_pipeline` package. Search, wallet, and IPFS credentials stay in the
backend process and are never returned to the browser.

## Quick start

Install and run from the **repository root**:

```powershell
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload  # development only
```

## Environment

The backend auto-loads `<repo-root>/.env` via `python-dotenv`.  Copy
`.env.example` to `.env` and fill in the required values:

| Variable          | Purpose                              | Required for       |
|-------------------|--------------------------------------|--------------------|
| `SERPAPI_KEY`     | SerpApi reverse-image search         | Source search       |
| `PINATA_JWT`      | Pinata IPFS pinning                  | Claim pinning       |
| `PRIVATE_KEY`     | 32-byte Sepolia wallet private key (not its public address) | Blockchain anchoring|
| `RPC_URL`         | Sepolia JSON-RPC endpoint            | Blockchain          |
| `IPFS_GATEWAY_URL` | Preferred read-only path-gateway base ending in `/ipfs` | Verification |
| `IPFS_FALLBACK_GATEWAY_URL` | Optional independent fallback path-gateway base | Verification |
| `CONTRACT_ADDRESS`| Override Registry address (optional) | Blockchain          |
| `FRONTEND_ORIGIN` | Exact comma-separated browser origins | CORS                |

The default process-local limiter allows 5 analyses, 10 confirmations, and 60
verification reads per client per 10 minutes, with separate instance-wide
caps. Override these values with the `*_RATE_LIMIT` variables in
`.env.example`; add an edge/API-gateway limiter for distributed deployments.

Gateway values are path-gateway bases such as `https://example-gateway/ipfs`;
do not include the CID, credentials, query parameters, or fragments. Verification
tries the preferred gateway and at most one independent fallback sequentially.
`ipfs.io` and `dweb.link` are treated as the same failure domain. Public claim
reads never use `PINATA_JWT`.

## Verify configuration

After starting the backend, check that services are configured:

```powershell
curl http://localhost:8000/api/health
```

Expected response when all services are configured:

```json
{"status": "ok", "services": {"search": "configured", "ipfs": "configured", "blockchain": "configured"}}
```

For a deployment-safe format check (without printing secret values), run
`python -m scripts.check_config` before starting the service.

## Common failure messages

| Message | Cause |
|---------|-------|
| "No matching images were found for this photo. Try another photo." | Google Lens returned zero visual matches for the crop |
| "No supported source results were found. Try another photo." | Visual matches existed, but none belonged to a supported social domain |
| "No candidate thumbnails had a usable face. Try another photo." | Supported-source matches existed, but face re-ranking could not use their thumbnails |
| "Source search is not configured on this server." | `SERPAPI_KEY` is missing from `.env` |
| "The source-search service rejected the server credentials." | API key is invalid |
| "The source-search service is temporarily rate-limited..." | SerpApi quota exhausted |
| "The source-search service is temporarily unavailable." | SerpApi 5xx or network error |

## API

- `POST /api/sessions`: multipart `photo`, required `consent=true`, and optional
  `auto_threshold`; returns an automatic selection or a zero-based ranked list.
- `POST /api/sessions/{session_id}/confirm`: optional JSON
  `candidate_index`; a review session requires one. This is the only endpoint
  that pins or writes to the chain.
- `GET /api/verify/{fingerprint}`: read-only chain and public-IPFS comparison.
- `GET /api/health`: lightweight configuration check (no external calls, no secrets).

Sessions are stored in an in-memory dictionary for this demo. Uploaded bytes
and the query embedding are retained only until confirmation, then cleared.
All sessions are lost when the process restarts, and multiple worker processes
do not share state.

Production command (one worker is required for process-local sessions and the
wallet nonce lock):

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```
