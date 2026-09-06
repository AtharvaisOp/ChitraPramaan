# ChitraPramaan production-readiness review

Date: 2026-09-06

The existing pipeline, claim format, Registry contract, candidate review flow,
and explicit confirmation behavior were preserved. The review added only
bounded production hardening and deployment guidance.

## Validation record

- `python -m pytest -m "not integration" -q`: 135 passed, 2 deselected.
- `cd frontend; npm test`: 24 passed in 3 files.
- `cd frontend; npm run lint`: passed.
- `cd frontend; npm run build`: passed with Next.js 16.3.4.
- `npm run contract:test`: 3 passed.
- `npm run contract:compile`: passed.
- `python -c "import backend.main"`: passed.
- `python -m scripts.check_config`: format checks passed without printing secrets.
- `python -m pip check`: no broken requirements.
- `npm audit --omit=dev --audit-level=high` (root and frontend): 0 vulnerabilities.

Paid/provider-consuming integration tests were not run.

## Hardening applied

- Added a process-local sliding-window limiter with clean `429` responses and
  documented edge-limiter requirements for public or multi-instance deployment.
- Rejected wildcard/path/credential CORS origins; exact HTTPS origins are
  required outside localhost.
- Capped streamed IPFS claim responses at 1 MiB before JSON parsing.
- Validated Pinata CID-shaped responses before anchoring.
- Added production API URL validation, security headers, Node 24 metadata, a
  non-root one-worker backend Dockerfile, and a secret-safe config checker.
- Documented one-worker process-local sessions, model-cache behavior, required
  secrets, health checks, rollback, and deployment limitations.

## Findings that remain deployment responsibilities

- The local workspace contains an ignored `.env` with real-looking credentials;
  rotate/revoke those values before deployment and verify they were never
  committed elsewhere. The repository has no `.git` metadata, so commit history
  cannot be audited here.
- Anonymous access is still possible by design. The in-process limiter reduces
  accidental loops but is not authentication or distributed abuse protection;
  place the API behind an edge limiter and access-control policy before public
  exposure.
- Sessions and wallet nonce serialization are process-local. Use one backend
  worker and one replica; a shared store/nonce coordinator is required for
  horizontal scaling.
- DNS rebinding and egress isolation remain infrastructure concerns even though
  application URL validation, redirect checks, and bounded downloads are kept.
- The Sepolia Registry and external providers are demonstrations/best-effort
  services, not audited production trust anchors.
