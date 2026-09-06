import type { Candidate, ConfirmResponse, SessionResponse, VerifyResponse } from "./types";

type ObjectValue = Record<string, unknown>;
const object = (v: unknown): v is ObjectValue => Boolean(v) && typeof v === "object" && !Array.isArray(v);
const string = (v: unknown): v is string => typeof v === "string";
const nonempty = (v: unknown): v is string => string(v) && v.trim().length > 0;
const score = (v: unknown) => typeof v === "number" && Number.isFinite(v) && v >= -1 && v <= 1;
const fingerprint = (v: unknown): v is string => string(v) && /^(?:0x)?[a-f\d]{64}$/i.test(v);
const sameFingerprint = (a: string, b: string) => a.replace(/^0x/, "").toLowerCase() === b.replace(/^0x/, "").toLowerCase();

function candidate(v: unknown): v is Candidate {
  return object(v) && Number.isInteger(v.index) && Number(v.index) >= 0 &&
    nonempty(v.url) && string(v.title) && string(v.thumbnail_url) && string(v.source) && score(v.score);
}

export function isSessionResponse(v: unknown): v is SessionResponse {
  if (!object(v) || !nonempty(v.session_id) || !Array.isArray(v.candidates) || !v.candidates.every(candidate)) return false;
  const candidateIndexes = new Set(v.candidates.map(c => c.index));
  if (v.candidates.length === 0 || candidateIndexes.size !== v.candidates.length) return false;
  if (v.status === "auto_selected") {
    return v.selection_method === "auto" && candidate(v.selected_candidate) &&
      candidateIndexes.has(v.selected_candidate.index);
  }
  return v.status === "review_required" && v.selection_method === null && v.selected_candidate === null &&
    candidateIndexes.size === v.candidates.length;
}

export function isConfirmResponse(v: unknown): v is ConfirmResponse {
  return object(v) && nonempty(v.session_id) && fingerprint(v.fingerprint) &&
    (v.selection_method === "auto" || v.selection_method === "human") && score(v.score) &&
    nonempty(v.cid) && string(v.tx_hash) && /^0x[a-f\d]{64}$/i.test(v.tx_hash) &&
    v.explorer_link === `https://sepolia.etherscan.io/tx/${v.tx_hash}`;
}

export function isVerifyResponse(v: unknown): v is VerifyResponse {
  if (!object(v) || typeof v.passed !== "boolean" || !fingerprint(v.fingerprint) ||
    !(v.fetched_fingerprint === null || fingerprint(v.fetched_fingerprint)) || !string(v.message)) return false;
  const r = v.on_chain_record;
  if (!object(r) || typeof r.exists !== "boolean" || !string(r.submitter) || !string(r.uri) ||
    !Number.isSafeInteger(r.timestamp) || Number(r.timestamp) < 0 || Number(r.timestamp) > 8_640_000_000_000) return false;
  return v.passed === (r.exists && v.fetched_fingerprint !== null && sameFingerprint(v.fingerprint, v.fetched_fingerprint));
}
