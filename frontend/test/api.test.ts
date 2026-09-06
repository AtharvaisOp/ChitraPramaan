import { afterEach, describe, expect, it, vi } from "vitest";
import { createSession, confirmSession, verifyFingerprint } from "@/lib/api";
import { isConfirmResponse } from "@/lib/validation";
import { ipfsGatewayUrl } from "@/lib/platform";

const fingerprint = "a".repeat(64);
const confirmed = { session_id: "session", fingerprint, selection_method: "human", score: .6, cid: "bafkfixture", tx_hash: `0x${"b".repeat(64)}`, explorer_link: `https://sepolia.etherscan.io/tx/0x${"b".repeat(64)}` };
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); });
describe("API trust boundary", () => {
  it("rejects an auto recommendation without the ranked candidate list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ session_id: "session", status: "auto_selected", candidates: [] }))));
    await expect(createSession(new File(["photo"], "a.jpg"))).rejects.toThrow("invalid response");
  });
  it("accepts an auto recommendation contained in the ranked candidate list", async () => {
    const candidate = { index: 0, url: "https://instagram.com/p/fixture", title: "Fixture", thumbnail_url: "https://images.example/fixture.jpg", source: "Instagram", score: .84 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      session_id: "session",
      status: "auto_selected",
      selection_method: "auto",
      selected_candidate: candidate,
      candidates: [candidate],
    }))));
    await expect(createSession(new File(["photo"], "a.jpg"))).resolves.toMatchObject({
      selected_candidate: candidate,
      candidates: [candidate],
    });
  });
  it("accepts bafk CIDs and rejects unsafe explorer links", () => {
    expect(isConfirmResponse(confirmed)).toBe(true);
    expect(isConfirmResponse({ ...confirmed, explorer_link: "javascript:alert(1)" })).toBe(false);
    expect(ipfsGatewayUrl("ipfs://ipfs/bafkfixture")).toBe("https://ipfs.io/ipfs/bafkfixture");
  });
  it("does not trust an internally inconsistent PASS", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ passed: true, fingerprint, fetched_fingerprint: "c".repeat(64), on_chain_record: { exists: true, submitter: "x", timestamp: 1, uri: "bafkfixture" }, message: "PASS" }))));
    await expect(verifyFingerprint(fingerprint)).rejects.toThrow("invalid response");
  });
  it("reports a network failure without raw browser diagnostics", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(confirmSession("session")).rejects.toThrow("backend is unavailable");
  });
  it("times out without resending a confirmation", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))));
    vi.stubGlobal("fetch", fetch);
    const request = expect(confirmSession("session")).rejects.toThrow("may still be running");
    await vi.advanceTimersByTimeAsync(300_000);
    await request;
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("fails clearly when a production deployment has no backend URL", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    await expect(confirmSession("session")).rejects.toThrow(
      "backend URL is not configured",
    );
  });
});
