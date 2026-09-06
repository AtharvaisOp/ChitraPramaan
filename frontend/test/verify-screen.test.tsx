import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VerifyScreen } from "@/components/verify/verify-screen";
import { verifyFingerprint } from "@/lib/api";

vi.mock("@/lib/api", () => ({ verifyFingerprint: vi.fn() }));

const mockedVerifyFingerprint = vi.mocked(verifyFingerprint);
const fingerprint = "c".repeat(64);

describe("re-verification screen", () => {
  beforeEach(() => mockedVerifyFingerprint.mockReset());

  it("renders a successful on-chain and IPFS check", async () => {
    mockedVerifyFingerprint.mockResolvedValue({
      passed: true,
      fingerprint,
      fetched_fingerprint: fingerprint,
      on_chain_record: {
        exists: true,
        submitter: "0xA5544cf76f7629cfB515b0d410B9A3Cd8149e23f",
        timestamp: 1788420600,
        uri: "bafybeigdyrfixturecid",
      },
      message: "On-chain lookup and fetched IPFS fingerprint match.",
    });

    render(<VerifyScreen initialFingerprint={fingerprint} />);

    expect(await screen.findByRole("heading", { name: "Verification passed" })).toBeInTheDocument();
    expect(screen.getByText("0xA5544cf76f7629cfB515b0d410B9A3Cd8149e23f")).toBeInTheDocument();
    expect(screen.getByText("Match")).toBeInTheDocument();
    expect(mockedVerifyFingerprint).toHaveBeenCalledWith(fingerprint, expect.any(AbortSignal));
    expect(mockedVerifyFingerprint).toHaveBeenCalledTimes(1);
  });

  it("starts one logical request when Strict Mode replays the mount effect", async () => {
    mockedVerifyFingerprint.mockResolvedValue({
      passed: true,
      fingerprint,
      fetched_fingerprint: fingerprint,
      on_chain_record: {
        exists: true,
        submitter: "0xA5544cf76f7629cfB515b0d410B9A3Cd8149e23f",
        timestamp: 1788420600,
        uri: "bafybeigdyrfixturecid",
      },
      message: "On-chain lookup and fetched IPFS fingerprint match.",
    });

    render(
      <StrictMode>
        <VerifyScreen initialFingerprint={fingerprint} />
      </StrictMode>,
    );

    expect(await screen.findByRole("heading", { name: "Verification passed" })).toBeInTheDocument();
    expect(mockedVerifyFingerprint).toHaveBeenCalledTimes(1);
  });

  it("releases the obsolete request and starts one request for a new fingerprint", async () => {
    const nextFingerprint = "e".repeat(64);
    let firstSignal: AbortSignal | undefined;
    mockedVerifyFingerprint
      .mockImplementationOnce((_requested, signal) => {
        firstSignal = signal;
        return new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
        });
      })
      .mockResolvedValueOnce({
        passed: false,
        fingerprint: nextFingerprint,
        fetched_fingerprint: null,
        on_chain_record: { exists: false, submitter: "", timestamp: 0, uri: "" },
        message: "No on-chain record exists for this fingerprint.",
      });

    const { rerender } = render(<VerifyScreen initialFingerprint={fingerprint} />);
    await waitFor(() => expect(mockedVerifyFingerprint).toHaveBeenCalledTimes(1));

    rerender(<VerifyScreen initialFingerprint={nextFingerprint} />);

    expect(await screen.findByRole("heading", { name: "No on-chain record was found" })).toBeInTheDocument();
    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    expect(mockedVerifyFingerprint).toHaveBeenCalledTimes(2);
    expect(mockedVerifyFingerprint.mock.calls.map(([requested]) => requested)).toEqual([
      fingerprint,
      nextFingerprint,
    ]);
  });

  it("distinguishes a completed mismatch from a request error", async () => {
    const fetched = "d".repeat(64);
    mockedVerifyFingerprint.mockResolvedValue({
      passed: false,
      fingerprint,
      fetched_fingerprint: fetched,
      on_chain_record: {
        exists: true,
        submitter: "0xA5544cf76f7629cfB515b0d410B9A3Cd8149e23f",
        timestamp: 1788420600,
        uri: "bafybeigdyrfixturecid",
      },
      message: "Fetched IPFS fingerprint does not match the on-chain lookup key.",
    });

    render(<VerifyScreen initialFingerprint={fingerprint} />);

    expect(await screen.findByRole("heading", { name: "Verification failed" })).toBeInTheDocument();
    expect(screen.getByText(fetched)).toBeInTheDocument();
    expect(screen.queryByText("Verification could not be completed")).not.toBeInTheDocument();
  });

  it("retries a transport failure without changing the fingerprint", async () => {
    const user = userEvent.setup();
    mockedVerifyFingerprint
      .mockRejectedValueOnce(new Error("IPFS gateway unavailable"))
      .mockResolvedValueOnce({
        passed: false,
        fingerprint,
        fetched_fingerprint: null,
        on_chain_record: { exists: false, submitter: "", timestamp: 0, uri: "" },
        message: "No on-chain record exists for this fingerprint.",
      });

    render(<VerifyScreen initialFingerprint={fingerprint} />);
    expect(await screen.findByText("IPFS gateway unavailable")).toBeInTheDocument();
    expect(screen.getByText("Verification could not be completed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "No on-chain record was found" })).toBeInTheDocument();
    expect(mockedVerifyFingerprint).toHaveBeenCalledTimes(2);
  });
});
