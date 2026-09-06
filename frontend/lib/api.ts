import type { ConfirmResponse, SessionResponse, VerifyResponse } from "@/lib/types";
import { isConfirmResponse, isSessionResponse, isVerifyResponse } from "@/lib/validation";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export class ApiClientError extends Error {
  readonly errorCode: string | undefined;
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiClientError";
    this.errorCode = deriveErrorCode(status, message);
  }
}

/** True when the error is transient and retrying may succeed. */
export function isRetryable(error: unknown): boolean {
  if (!(error instanceof ApiClientError)) return false;
  // Configuration errors (503 "not configured") are permanent.
  if (error.status === 503 && error.message.includes("not configured")) return false;
  // Auth errors are permanent.
  if (error.status === 502 && error.message.includes("rejected")) return false;
  // Everything else (429, 502 unavailable, timeout, network) may be transient.
  return true;
}

function deriveErrorCode(status: number, message: string): string | undefined {
  if (status === 503 && message.includes("not configured")) return "SEARCH_NOT_CONFIGURED";
  if (status === 502 && message.includes("rejected")) return "SEARCH_AUTH_ERROR";
  if (status === 429) return "SEARCH_RATE_LIMITED";
  if (status === 502 && message.includes("unavailable")) return "SEARCH_PROVIDER_UNAVAILABLE";
  if (status === 502 && message.includes("unexpected")) return "SEARCH_RESPONSE_INVALID";
  if (status === 408) return "REQUEST_TIMEOUT";
  if (status === 0) return "BACKEND_UNREACHABLE";
  return undefined;
}

function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!configured) {
    if (process.env.NODE_ENV === "production") {
      throw new ApiClientError(
        "The backend URL is not configured for this deployment.",
        0,
      );
    }
    return DEFAULT_API_BASE_URL;
  }
  try {
    const parsed = new URL(configured);
    if (
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      (process.env.NODE_ENV === "production" &&
        parsed.protocol !== "https:" &&
        !["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname))
    ) {
      throw new Error("unsafe backend URL");
    }
  } catch {
    throw new ApiClientError(
      "The backend URL is not configured with a valid HTTP(S) URL.",
      0,
    );
  }
  return configured.replace(/\/$/, "");
}

function errorMessage(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) return "The request contained invalid data.";
  return `The server returned an unexpected ${status} response.`;
}

async function requestJson<T>(path: string, init: RequestInit, validate: (value: unknown) => value is T): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(init.signal?.reason);
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) abort();
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 300_000);
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, { ...init, signal: controller.signal, cache: "no-store" });
    const payload = await response.json().catch(() => null);

    if (!response.ok) {
      const detail =
        payload && typeof payload === "object" && "detail" in payload
          ? (payload as { detail: unknown }).detail
          : undefined;
      throw new ApiClientError(errorMessage(response.status, detail), response.status, detail);
    }
    if (!validate(payload)) {
      throw new ApiClientError("The server returned an invalid response.", response.status);
    }
    return payload;
  } catch (error) {
    if (timedOut) throw new ApiClientError("The backend did not respond in time. Work may still be running. Retry this session; do not start another analysis while an anchor may be pending.", 408);
    if (controller.signal.aborted) throw error;
    if (error instanceof TypeError) throw new ApiClientError("The backend is unavailable. Check that the API is running and reachable, then try again.", 0);
    throw error;
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

export async function createSession(
  photo: File,
  options: { autoThreshold?: number; signal?: AbortSignal } = {},
): Promise<SessionResponse> {
  const form = new FormData();
  form.append("photo", photo);
  form.append("consent", "true");
  if (options.autoThreshold !== undefined) {
    form.append("auto_threshold", String(options.autoThreshold));
  }
  return requestJson<SessionResponse>("/api/sessions", {
    method: "POST",
    body: form,
    signal: options.signal,
  }, isSessionResponse);
}

export async function confirmSession(
  sessionId: string,
  candidateIndex?: number,
  signal?: AbortSignal,
): Promise<ConfirmResponse> {
  const body = candidateIndex === undefined ? {} : { candidate_index: candidateIndex };
  return requestJson<ConfirmResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    },
    isConfirmResponse,
  );
}

export async function verifyFingerprint(
  fingerprint: string,
  signal?: AbortSignal,
): Promise<VerifyResponse> {
  const result = await requestJson<VerifyResponse>(
    `/api/verify/${encodeURIComponent(fingerprint)}`,
    { method: "GET", signal },
    isVerifyResponse,
  );
  if (result.fingerprint.replace(/^0x/, "").toLowerCase() !== fingerprint.replace(/^0x/, "").toLowerCase()) {
    throw new ApiClientError("The backend returned a different fingerprint. Verification cannot be trusted.", 502);
  }
  return result;
}
