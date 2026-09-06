# UI/UX specification

This document is the implementation contract for the Phase 13 frontend. It describes only behavior supported by the Phase 11 FastAPI backend. It does not introduce new API fields, new pipeline decisions, or browser-side access to provider credentials.

## Design read

This is a trust-first research and demonstration tool. The interface should make a consequential workflow understandable, keep irreversible actions explicit, and present evidence without implying that a face resemblance proves identity.

- Design variance: 3/10. Familiar controls and a stable single-column workflow are more valuable than novelty.
- Motion intensity: 2/10. Use motion only to clarify state changes and button feedback.
- Visual density: 5/10. Evidence should be compact enough to compare while remaining readable.
- Primary visual direction: quiet, neutral, utilitarian, and documentation-like.
- Component default: Tailwind CSS v4 with shadcn/ui primitives.
- Typography: Geist for interface text and Geist Mono for hashes, CIDs, URLs, scores, and timestamps.

## Product truth and safety language

The upload screen must show this statement before the user can begin:

> A match means an image resembling this face appears at a URL. It does not confirm identity.

The browser receives no search API key, wallet private key, IPFS pinning key, query embedding, or original image hash. It talks only to the backend URL in `NEXT_PUBLIC_API_BASE_URL`. Search, model inference, IPFS pinning, and chain writes remain server-side.

The frontend must not label a cosine similarity as identity confidence, probability, certainty, or verification. Display it as a similarity score on its native numeric scale, such as `0.834`.

## Backend contract

The frontend must define TypeScript types from these exact response shapes. Unknown response properties may be ignored, but missing required properties are an error.

### Create a session

`POST /api/sessions` uses `multipart/form-data`:

- `photo`: required upload. Accepted backend MIME types are JPEG, PNG, and WebP.
- `consent`: required as `true` by the interface.
- `auto_threshold`: optional number. Phase 13 does not need to expose this control; omitting it uses the backend default.

Maximum upload size is 10 MB, with a 25 megapixel decoded-image limit.

```ts
type Candidate = {
  index: number;
  url: string;
  title: string;
  thumbnail_url: string;
  source: string;
  score: number;
};

type SessionResponse = {
  session_id: string;
  status: "auto_selected" | "review_required";
  selection_method: "auto" | null;
  selected_candidate: Candidate | null;
  candidates: Candidate[];
};
```

`candidates` contains the ranked results for both statuses. For `auto_selected`, `selected_candidate` identifies the recommended candidate to preselect; it does not authorize confirmation. For `review_required`, `selected_candidate` is null.

### Confirm a match and anchor it

`POST /api/sessions/{session_id}/confirm` uses JSON.

- Send `{ "candidate_index": <Candidate.index> }` after the user explicitly confirms a candidate.

```ts
type ConfirmResponse = {
  session_id: string;
  fingerprint: string;
  selection_method: "auto" | "human";
  score: number;
  cid: string;
  tx_hash: string;
  explorer_link: string;
};
```

This endpoint performs the costly, irreversible work: it pins the claim and writes the fingerprint to the registry contract. A successful confirmation is idempotent for that session.

### Verify a fingerprint

`GET /api/verify/{fingerprint}` takes the full hex fingerprint in the path.

```ts
type OnChainRecord = {
  exists: boolean;
  submitter: string;
  timestamp: number;
  uri: string;
};

type VerifyResponse = {
  passed: boolean;
  fingerprint: string;
  fetched_fingerprint: string | null;
  on_chain_record: OnChainRecord;
  message: string;
};
```

This endpoint verifies the on-chain lookup and the claim fetched from IPFS. It does not accept a local claim file and does not return a transaction hash, block number, chain ID, or deployment metadata.

### Error shape

Most backend errors use FastAPI's `detail` property:

```ts
type ApiError = {
  detail: string | Array<unknown>;
};
```

The frontend should normalize a string detail directly. For an array detail, show a concise generic message and preserve the structured value for development logging. Never render raw HTML from an error response.

## Workflow and routing

Use two routes:

- `/`: the upload, processing, review, and result workflow.
- `/verify/[fingerprint]`: the independently addressable re-verification screen.

The main route is a client-side state machine:

| Current state | Event | Next state | Network action |
| --- | --- | --- | --- |
| Upload | Analyze | Processing | Create session |
| Processing | Session succeeds | Match review | None |
| Match review | Confirm candidate | Match review, confirming | Confirm selected index |
| Match review, confirming | Confirm succeeds | Result | None |
| Match review | Cancel | Upload | None |
| Any request state | Request fails | Screen-specific error | None |

Always render Match review when the session succeeds. A sufficiently similar result is a recommendation that may be preselected, never permission to call the confirm endpoint automatically.

The backend keeps pending session state in process memory. It does not provide a `GET` endpoint to restore a session. Therefore:

- A page refresh during processing or review returns to Upload with a notice that the unfinished session could not be restored.
- Cancel clears client state and returns to Upload. It prevents the frontend from confirming or anchoring, but there is no backend delete endpoint, so the pending in-memory session remains until the server discards it or restarts.
- Do not persist the uploaded photo, query data, or ranked candidates in local storage.
- The final `ConfirmResponse` may be kept in `sessionStorage` to survive an accidental refresh in the same tab. Clear it when the user starts a new analysis.

Use `AbortController` for navigation cleanup and explicit retry replacement. Be accurate in UI copy: aborting a browser request does not guarantee that already-started backend computation stopped.

## Shared shell and visual system

Use a centered application shell with a maximum content width of approximately 1160 px. Candidate review may expand to 1120 px on large screens. Use generous page padding and a single primary content column.

The header contains:

- Product label: `ChitraPramaan`.
- A restrained subtitle: `Image provenance & verification`.
- A text link to the verifier route if a fingerprint is available. Do not show a disabled navigation item when none is available.

Visual tokens:

- Neutral palette: warm off-white surfaces in light mode and charcoal in dark mode.
- One restrained teal accent for primary actions, focus rings, and links.
- Green, red, and amber are reserved for success, failure, and caution states.
- Respect the operating system light or dark preference. Both themes must preserve readable contrast.
- Use a consistent 8 px corner radius.
- Prefer thin borders and surface changes over large shadows.
- Do not use gradients, glass effects, neon glows, decorative illustrations, animated backgrounds, or marketing-style hero treatments.
- Use one icon family, preferably Phosphor Icons. Do not use emoji as interface icons.

Motion is limited to 150 to 200 ms opacity or small transform transitions for state replacement, button feedback, and disclosure. Disable nonessential transitions under `prefers-reduced-motion`. Do not use fake progress bars, progress percentages, marquees, or looping decorative animation.

## Shared behavior

- Put persistent labels above inputs. Placeholder text is not a label.
- Give every interactive element a visible keyboard focus indicator.
- Use native buttons, inputs, links, checkboxes, and radio controls through accessible primitives.
- Announce asynchronous state text with `aria-live="polite"` and errors with `role="alert"`.
- Disable duplicate submission while a request is in flight.
- Preserve entered or selected data when a retryable request fails.
- Copy buttons must write the full value, change their accessible label to confirm success, and announce `Copied` without relying on color alone.
- External links open in a new tab with `rel="noopener noreferrer"` and include an external-link icon or text indication.
- All full fingerprints, CIDs, addresses, transaction hashes, and URLs use monospace text and allow safe line wrapping or horizontal scrolling. Never truncate the only visible copy of a value.
- Do not expose a face bounding box, crop preview, image hash, embedding, detector internals, or raw uploaded image. Those fields are not in the API response.

## Screen 1: Upload

### Purpose

Collect one supported image and explicit consent, explain the scope of the result, and start the server-side analysis.

### Key elements

1. Page heading: `Analyze a photo`.
2. Plain-language proof limitation statement shown prominently but not as an alarming error.
3. File input labeled `Photo` with helper text: `JPEG, PNG, or WebP, up to 10 MB.`
4. Selected-file summary containing only the local filename and size. A local preview is optional, must use an object URL, and must be revoked when replaced or unmounted.
5. Required consent checkbox with this label: `I confirm that I have the right to search the web for the person in this photo.`
6. Supporting action notice: `You will review any usable matches before choosing what to pin to IPFS and record on Sepolia.`
7. Primary button: `Analyze`.

### States

- Empty: no file, unchecked consent, disabled Analyze button.
- File selected: show filename and size; Analyze remains disabled until consent is checked.
- Invalid file: show an inline error under the file input and keep Analyze disabled. Validate MIME type and size in the browser for fast feedback, while treating the backend as authoritative.
- Ready: supported file selected, size at or below 10 MB, consent checked, Analyze enabled.
- Submitting: transition immediately to Processing after submission begins. Prevent a second request.
- Error after create request: return to Upload with the file selection and consent state preserved when the browser still has them, plus a retryable error alert.
- Success: handled by the Processing transition rather than rendered on this screen.

### API field mapping

| UI value | API source or destination |
| --- | --- |
| Selected file | `photo` multipart field |
| Consent checkbox | `consent=true` multipart field |
| Optional configured threshold | `auto_threshold`; omit when the UI does not expose it |
| Error alert | HTTP status plus normalized `detail` |

## Screen 2: Processing

### Purpose

Give honest feedback while the backend detects, crops, searches, and ranks.

### Key elements

1. Heading: `Analyzing photo`.
2. Small indeterminate spinner with text. The spinner is a supplement, not the only status indicator.
3. Initial status: `Detecting a face and searching for matching social results. This may take a moment.`
4. Secondary note: `No progress percentage is available.`

Do not invent named step completion, elapsed predictions, percentages, result counts, or background-job polling. `POST /api/sessions` is a single request from the frontend's perspective.

### States

- Loading analysis: create-session request is in flight.
- Slow request: after a reasonable delay, keep the same indeterminate state and add `The server is still working.` Do not imply failure.
- Create error: show an error alert and `Back to upload` action. If the local file is still available, a `Try again` action may repeat the create request after explicit user activation.
- Success: navigate within the workflow to Match review.

### API field mapping

| UI decision or value | API field |
| --- | --- |
| Recommended candidate | `selected_candidate` when `status` is `auto_selected` |
| Ranked choices | `candidates` |
| Session used for explicit confirmation | `session_id` |
| Error alert | HTTP status plus normalized `detail` |

## Screen 3: Match review

### Purpose

Let the user compare the ranked candidates and explicitly choose which result will be placed in the claim. This screen appears for every successful session response.

### Key elements

1. Heading: `Review possible matches`.
2. If `selected_candidate` is present, mark it `Recommended` and preselect it. The user may choose another candidate.
3. Ranked candidate list using a radio group. Each row is one selectable result, not a nested collection of competing buttons.
4. Each candidate shows:
   - rank derived from list order, displayed as `1`, `2`, and so on;
   - thumbnail from `thumbnail_url`;
   - title from `title`, with a fallback such as `Untitled result`;
   - platform derived from the hostname of `url`;
   - normalized URL from `url` as a safe external link;
   - similarity score from `score`, formatted to three decimal places;
   - optional provider/source label from `source`, clearly called `Source` rather than `Platform`.
5. Primary button: `Confirm & Anchor`, disabled until a candidate is selected and guarded against duplicate submission.
6. Secondary button: `Cancel`.

Platform derivation is presentation-only:

| Hostname | Label |
| --- | --- |
| `x.com`, `twitter.com` and subdomains | X |
| `instagram.com` and subdomains | Instagram |
| `facebook.com` and subdomains | Facebook |
| `linkedin.com` and subdomains | LinkedIn |
| `reddit.com` and subdomains | Reddit |
| `tiktok.com` and subdomains | TikTok |
| Any other valid hostname | Display hostname |

Parse URLs with the browser `URL` API. If a URL is invalid, show `Unknown platform`, display the raw value as text, and do not create a clickable link. Do not use `source` as a substitute for the normalized URL's platform.

### States

- Empty: this should not normally occur. If `review_required` arrives with no candidates, show `No review candidates were returned.` and a `Start over` action. Do not allow confirmation.
- Ready, no selection: candidates visible; Confirm disabled.
- Ready, selected: selected row has a border, radio state, and text cue; Confirm enabled.
- Thumbnail loading: reserve a stable square area and use a neutral skeleton.
- Thumbnail failed: replace it with an icon and `Thumbnail unavailable`; candidate remains selectable.
- Confirming: retain the list and selected row, disable selection and both actions, and show `Pinning and anchoring selected match` on the primary button or adjacent status.
- Confirm error: keep the selection, show a clear alert, and offer retry. No result screen is shown.
- Cancel: return to Upload after a lightweight confirmation only if a candidate was selected. Cancel performs no API request and no chain write.
- Success: show Result using the confirm response.

### API field mapping

| UI value | API field |
| --- | --- |
| Candidate identity sent to confirm | `Candidate.index` as `candidate_index` |
| Rank | Position in `candidates`, not `Candidate.index + 1` |
| Thumbnail | `thumbnail_url` |
| Result title | `title` |
| Platform and external destination | `url` |
| Source label | `source` |
| Similarity score | `score` |
| Confirm endpoint path | `session_id` |

The frontend must send the backend-provided `Candidate.index`, not the visual list position. This prevents the wrong candidate from being confirmed if presentation filtering or reordering is added later.

## Screen 4: Result

### Purpose

Present the completed proof record, provide copyable identifiers and authoritative outbound links, and offer immediate re-verification.

### Key elements

1. Success heading: `Claim anchored`.
2. Compact status line containing selection method and similarity score, for example `Recommended match confirmed - similarity 0.834` or `Selected by you - similarity 0.612`.
3. Fingerprint section:
   - short form for scanning, using the first 10 and last 8 characters separated by `...`;
   - full `fingerprint` visible in a monospace, wrapping block;
   - `Copy fingerprint` button that copies the full value.
4. IPFS section:
   - full `cid`;
   - copy button;
   - gateway link constructed as `https://ipfs.io/ipfs/{encodeURIComponent(cid)}` and labeled `Open pinned claim`.
5. Transaction section:
   - full `tx_hash`;
   - copy button;
   - `View transaction` link using `explorer_link` exactly as returned by the backend.
6. Primary action: `Re-verify`, navigating to `/verify/{fingerprint}`.
7. Secondary action: `Analyze another photo`, which clears current workflow state and returns to Upload.

Do not call the verify endpoint automatically on entry. Anchoring succeeded if this screen was reached. Verification is a distinct user action and should remain understandable as a separate read operation.

### States

- Empty: not routable directly on `/` without a completed response. If result state is absent after refresh and no valid `sessionStorage` value exists, return to Upload with `The previous result is no longer available in this tab.`
- Success: all confirm response fields visible.
- Copy success: temporary accessible `Copied` feedback local to the relevant value.
- Malformed external link: display the value but disable the outbound link and show `Link unavailable`.
- Re-verify navigation: button remains an ordinary link-style navigation action; verification loading belongs to the next screen.
- Error: confirm errors stay on Processing or Match review, so Result has no network error state of its own.

### API field mapping

| UI value | `ConfirmResponse` field |
| --- | --- |
| Fingerprint, short and full | `fingerprint` |
| Selection label | `selection_method` |
| Similarity value | `score` |
| IPFS identifier | `cid` |
| Transaction identifier | `tx_hash` |
| Testnet explorer destination | `explorer_link` |
| Internal consistency check | `session_id` may be retained but need not be displayed |

## Screen 5: Re-verify

### Purpose

Read the public record and confirm that the fingerprint resolved on-chain matches the fingerprint recomputed from the IPFS claim returned by that record.

### Entry and key elements

The route is `/verify/[fingerprint]`. A user may arrive from Result or paste a shareable route directly. On valid entry, call `GET /api/verify/{fingerprint}`.

Show:

1. Heading: `Re-verify claim`.
2. Requested fingerprint from the route, in full and copyable.
3. Indeterminate loading state while the request runs.
4. A pass or fail summary with icon, text, and semantic color.
5. The backend's `message` as the primary explanation. Do not replace it with a stronger claim.
6. Comparison rows:
   - requested or returned lookup fingerprint from `fingerprint`;
   - fetched IPFS fingerprint from `fetched_fingerprint`, or `Not available`;
   - match result from `passed`.
7. On-chain record rows:
   - existence from `on_chain_record.exists`;
   - submitter from `on_chain_record.submitter`, full and copyable;
   - timestamp from `on_chain_record.timestamp`, formatted as UTC with the raw Unix seconds available in secondary text;
   - URI from `on_chain_record.uri`, full and copyable.
8. If `uri` is a bare CID, link to `https://ipfs.io/ipfs/{encodedUri}`. If it begins with `ipfs://`, link its path through the same gateway. If it is a valid `https:` URL, link it directly. Reject other link schemes.
9. Actions: `Verify again` and `Analyze a photo`.

The UI must call this `claim integrity verification` or `record verification`, not identity verification.

### States

- Invalid route value: do not call the API. Show `Enter a valid 64-character hexadecimal fingerprint, optionally prefixed with 0x.` and a link back to Upload. The backend accepts either form and normalizes the value to lowercase without the prefix.
- Loading: show a skeleton for comparison and record rows plus a live status message. Do not retain a previous fingerprint's result while a new request loads.
- Passed: prominent `Verification passed` plus the backend message and full comparison details.
- Failed, mismatch: prominent `Verification failed`; show both available fingerprints so the mismatch is inspectable.
- Failed, unanchored: when `on_chain_record.exists` is false, show `No on-chain record was found` and use `Not available` for fetched fingerprint when null.
- Request error: show `Verification could not be completed` plus normalized backend detail and a `Try again` action. Distinguish this transport or provider failure from a completed verification whose `passed` value is false.
- Empty response or malformed payload: treat it as a request error, not as a failed proof.

### API field mapping

| UI value | `VerifyResponse` field |
| --- | --- |
| Overall status | `passed` |
| Backend explanation | `message` |
| On-chain lookup fingerprint | `fingerprint` |
| Fingerprint recomputed from IPFS data | `fetched_fingerprint` |
| Record existence | `on_chain_record.exists` |
| Submitter | `on_chain_record.submitter` |
| UTC and Unix time | `on_chain_record.timestamp` |
| CID or stored URI | `on_chain_record.uri` |

## Error language and recovery

Prefer specific, non-technical messages and keep the server detail available when it is safe and useful.

| Condition | User-facing heading | Recovery |
| --- | --- | --- |
| Consent rejected | Consent is required | Return to Upload and focus the checkbox |
| Unsupported file type | Unsupported photo format | Choose a JPEG, PNG, or WebP file |
| File too large | Photo is larger than 10 MB | Choose a smaller file |
| No face detected | No face could be detected | Choose another photo |
| Search provider failed | Search could not be completed | Retry or return to Upload |
| Session missing after restart | This session is no longer available | Start over |
| Confirmation already in progress | This claim is already being finalized | Wait briefly, then retry the same session |
| IPFS or chain failure | The claim could not be anchored | Retry the same confirmation |
| Verification provider failure | Verification could not be completed | Retry without changing the fingerprint |

HTTP failure never means `Verification failed` unless the backend successfully returned a `VerifyResponse` with `passed: false`.

## Responsive behavior

- Below 640 px, use one column, full-width primary actions, and vertically stacked candidate content.
- At 640 px and above, candidate rows use a fixed thumbnail column and a flexible evidence column. Keep the radio control at the start edge.
- Long identifiers wrap with `overflow-wrap: anywhere`; tables become definition lists on narrow screens rather than forcing page-level horizontal scrolling.
- Keep primary actions visible after long candidate lists with a non-obscuring sticky action area on small screens. Respect safe-area insets.
- Minimum touch target is 44 by 44 px.

## Suggested Phase 13 structure

```text
frontend/
  app/
    page.tsx
    verify/[fingerprint]/page.tsx
  components/
    workflow/upload-screen.tsx
    workflow/processing-screen.tsx
    workflow/match-review-screen.tsx
    workflow/result-screen.tsx
    verify/verification-result.tsx
    shared/copy-value.tsx
    shared/api-error-alert.tsx
    ui/...
  lib/
    api.ts
    types.ts
    platform.ts
    format.ts
```

`page.tsx` should own a reducer or explicit state machine and pass data down. Keep HTTP calls in `lib/api.ts`, response types in `lib/types.ts`, hostname labeling in `lib/platform.ts`, and identifier/date formatting in `lib/format.ts`. Presentational components must not read environment variables directly.

Use shadcn/ui Button, Checkbox, Alert, RadioGroup, Separator, Skeleton, and Tooltip where they add accessible behavior. Do not turn every section into a floating card. Use spacing and separators for most hierarchy.

## Deployment and integration notes

- Frontend environment: only `NEXT_PUBLIC_API_BASE_URL`.
- Never add search, wallet, RPC, contract deployment, or pinning secrets to a `NEXT_PUBLIC_` variable.
- If frontend and backend use different origins during development, the backend must allow the configured frontend origin through CORS. This is an integration requirement, not a change to endpoint payloads.
- Prefer same-origin deployment or an explicit allowlist. Do not use wildcard CORS with credentials.
- External thumbnails may require Next.js image-host configuration. Because candidate hosts are dynamic, a plain `<img>` with fixed dimensions, safe referrer policy, lazy loading, and failure fallback is acceptable for this demo.

## Phase 13 acceptance checklist

- Upload accepts only a valid supported image at or below 10 MB.
- Analyze cannot be activated until consent is checked.
- Processing uses indeterminate, truthful status with no percentage.
- Both session statuses render every returned candidate and confirm using `Candidate.index`.
- `auto_selected` only marks and preselects the recommendation; it never triggers confirmation.
- No IPFS or chain action is initiated by the frontend before a specific match exists.
- Result shows and copies the full fingerprint, CID, and transaction hash.
- Result uses the backend-provided explorer link.
- Re-verify is directly addressable by fingerprint and distinguishes fail from request error.
- Pass and fail states show the on-chain submitter and UTC timestamp when returned.
- Similarity is never presented as identity confidence.
- Pending state loss after refresh is explained without inventing session recovery.
- Keyboard navigation, focus order, screen-reader status announcements, contrast, reduced motion, and broken-thumbnail behavior are verified.
- The browser bundle and network requests contain no provider secret or private key.

## Explicit non-goals

Phase 13 should not add authentication, user accounts, server session persistence, polling, background-job progress, face-selection controls, search-provider controls, editable thresholds, local claim upload, contract metadata, or new backend fields. Those require separate product and API decisions.

## Final review implementation notes

The shared shell shows Upload → Analyze → Select → Record → Re-verify without adding navigation routes. Selection includes both automatic and human decisions. A step marker indicates the actual request phase; it does not claim granular backend progress. Result timestamps appear only on the re-verification record because confirmation does not return them.

Upload uses a native, keyboard-accessible file control inside the drop zone and a revocable local blob preview. Changing the file resets consent. Candidates have native radio semantics, 44px selection labels, visible focus, full wrapping source URLs, and a mobile action area. Results place Re-verify ahead of identifiers and show a timeline supported by the successful response. PASS establishes claim integrity only; missing records and gateway errors remain distinct.

Short CSS transitions and a request-only spinner use the existing stack. No animation dependency was added. The reduced-motion media query disables screen entry and spinner animation. API response validators and optional tab storage are shared frontend utilities; no provenance calculation moved to the browser.
