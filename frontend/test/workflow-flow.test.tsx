import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workflow } from "@/components/workflow/workflow";
import { ApiClientError, confirmSession, createSession, isRetryable } from "@/lib/api";
import type { Candidate, ConfirmResponse } from "@/lib/types";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createSession: vi.fn(),
    confirmSession: vi.fn(),
  };
});

const mockedCreateSession = vi.mocked(createSession);
const mockedConfirmSession = vi.mocked(confirmSession);

const candidateA: Candidate = {
  index: 0,
  url: "https://instagram.com/p/result-a",
  title: "Result A",
  thumbnail_url: "https://images.example.com/result-a.jpg",
  source: "reverse-search",
  score: 0.84,
};

const candidateB: Candidate = {
  index: 1,
  url: "https://reddit.com/r/photos/result-b",
  title: "Result B",
  thumbnail_url: "https://images.example.com/result-b.jpg",
  source: "reverse-search",
  score: 0.61,
};

function finalized(selectionMethod: "auto" | "human", score: number): ConfirmResponse {
  return {
    session_id: `${selectionMethod}-session`,
    fingerprint: "a".repeat(64),
    selection_method: selectionMethod,
    score,
    cid: "bafybeigdyrfixturecid",
    tx_hash: `0x${"b".repeat(64)}`,
    explorer_link: `https://sepolia.etherscan.io/tx/0x${"b".repeat(64)}`,
  };
}

async function uploadAndConsent() {
  const user = userEvent.setup();
  render(<Workflow />);
  await screen.findByRole("heading", { name: "Analyze a photo" });
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("photo input was not rendered");
  const photo = new File([new Uint8Array([255, 216, 255])], "sample.jpg", { type: "image/jpeg" });
  await user.upload(input, photo);
  await user.click(screen.getByRole("checkbox"));
  return { user, photo };
}

describe("guided workflow", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
  });

  it("shows and preselects the recommended candidate without confirming", async () => {
    const response = finalized("auto", candidateA.score);
    mockedCreateSession.mockResolvedValue({
      session_id: response.session_id,
      status: "auto_selected",
      selection_method: "auto",
      selected_candidate: candidateA,
      candidates: [candidateA, candidateB],
    });

    const { user, photo } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByRole("heading", { name: "Review possible matches" })).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Select Result A" })).toBeChecked();
    expect(screen.getByText("Instagram")).toBeInTheDocument();
    expect(screen.getByText("Reddit")).toBeInTheDocument();
    expect(screen.getByText("Result A")).toBeInTheDocument();
    expect(screen.getByText("0.840")).toBeInTheDocument();
    expect(screen.getAllByText("Source: reverse-search")).toHaveLength(2);
    expect(mockedCreateSession).toHaveBeenCalledTimes(1);
    expect(mockedCreateSession).toHaveBeenCalledWith(photo, { signal: expect.any(AbortSignal) });
    expect(mockedConfirmSession).not.toHaveBeenCalled();
  });

  it("allows replacing the recommendation and confirms only the chosen index", async () => {
    const response = finalized("human", candidateB.score);
    mockedCreateSession.mockResolvedValue({
      session_id: response.session_id,
      status: "auto_selected",
      selection_method: "auto",
      selected_candidate: candidateA,
      candidates: [candidateA, candidateB],
    });
    mockedConfirmSession.mockResolvedValue(response);

    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByRole("heading", { name: "Review possible matches" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Select Result B" }));
    expect(screen.getByRole("radio", { name: "Select Result B" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Confirm & Anchor" }));

    expect(await screen.findByRole("heading", { name: "Claim anchored" })).toBeInTheDocument();
    expect(screen.getByText("Selected by you - similarity 0.610")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedConfirmSession).toHaveBeenCalledWith(response.session_id, candidateB.index, expect.any(AbortSignal));
    });
  });

  it("requires a manual selection when no candidate is recommended", async () => {
    mockedCreateSession.mockResolvedValue({
      session_id: "review-session",
      status: "review_required",
      selection_method: null,
      selected_candidate: null,
      candidates: [candidateA, candidateB],
    });

    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByRole("heading", { name: "Review possible matches" })).toBeInTheDocument();
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm & Anchor" })).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Select Result A" }));
    expect(screen.getByRole("button", { name: "Confirm & Anchor" })).toBeEnabled();
    expect(mockedConfirmSession).not.toHaveBeenCalled();
  });

  it("prevents duplicate confirmation submissions", async () => {
    let resolveConfirmation!: (value: ConfirmResponse) => void;
    const response = finalized("auto", candidateA.score);
    mockedCreateSession.mockResolvedValue({
      session_id: response.session_id,
      status: "auto_selected",
      selection_method: "auto",
      selected_candidate: candidateA,
      candidates: [candidateA, candidateB],
    });
    mockedConfirmSession.mockReturnValue(new Promise((resolve) => {
      resolveConfirmation = resolve;
    }));

    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));
    const confirm = await screen.findByRole("button", { name: "Confirm & Anchor" });
    await user.click(confirm);
    await user.click(confirm);

    expect(mockedConfirmSession).toHaveBeenCalledTimes(1);
    expect(mockedConfirmSession).toHaveBeenCalledWith(response.session_id, candidateA.index, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "Pinning and anchoring" })).toBeDisabled();

    resolveConfirmation(response);
    expect(await screen.findByRole("heading", { name: "Claim anchored" })).toBeInTheDocument();
    expect(screen.getByText("Recommended match confirmed - similarity 0.840")).toBeInTheDocument();
  });

  it("shows an anchored result when sessionStorage writes fail", async () => {
    const response = finalized("auto", .9);
    mockedCreateSession.mockResolvedValue({session_id: response.session_id, status: "auto_selected", selection_method: "auto", selected_candidate: candidateA, candidates: [candidateA]});
    mockedConfirmSession.mockResolvedValue(response);
    const { user } = await uploadAndConsent();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Storage blocked", "SecurityError"); });
    await user.click(screen.getByRole("button", { name: "Analyze" }));
    await user.click(await screen.findByRole("button", { name: "Confirm & Anchor" }));
    expect(await screen.findByRole("heading", { name: "Claim anchored" })).toBeInTheDocument();
    expect(mockedConfirmSession).toHaveBeenCalledTimes(1);
  });

  it("cancels review without confirming or anchoring", async () => {
    mockedCreateSession.mockResolvedValue({session_id: "review", status: "review_required", selection_method: null, selected_candidate: null, candidates: [candidateA]});
    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));
    await screen.findByRole("heading", {name: "Review possible matches"});
    await user.click(screen.getByRole("button", {name: "Cancel"}));
    expect(await screen.findByRole("heading", {name: "Analyze a photo"})).toBeInTheDocument();
    expect(mockedConfirmSession).not.toHaveBeenCalled();
  });

  it("shows Try again for transient errors and preserves file/consent", async () => {
    // A 502 "unavailable" error is transient and retryable.
    const error = new ApiClientError("The source-search service is temporarily unavailable.", 502);
    mockedCreateSession.mockRejectedValueOnce(error);

    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));

    // Should return to upload screen with error shown
    expect(await screen.findByRole("heading", { name: "Analyze a photo" })).toBeInTheDocument();
    expect(screen.getByText("Analysis could not be completed")).toBeInTheDocument();
    expect(screen.getByText(/unavailable/)).toBeInTheDocument();

    // Try again button should be visible for transient errors
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();

    // The file and consent should still be intact (no need to re-upload)
    expect(screen.getByText("sample.jpg")).toBeInTheDocument();
  });

  it("shows no retry for config errors (503 not configured)", async () => {
    const error = new ApiClientError("Source search is not configured on this server.", 503);
    mockedCreateSession.mockRejectedValueOnce(error);

    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByRole("heading", { name: "Analyze a photo" })).toBeInTheDocument();
    expect(screen.getByText("Analysis could not be completed")).toBeInTheDocument();
    expect(screen.getByText(/not configured/)).toBeInTheDocument();

    // No retry button for permanent config errors
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it.each([
    "No matching images were found for this photo. Try another photo.",
    "No supported source results were found. Try another photo.",
    "No candidate thumbnails had a usable face. Try another photo.",
  ])("shows the backend's expected search outcome: %s", async (message) => {
    mockedCreateSession.mockRejectedValueOnce(new ApiClientError(message, 422));

    const { user } = await uploadAndConsent();
    await user.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("classifies retryable and non-retryable errors correctly", () => {
    expect(isRetryable(new ApiClientError("unavailable.", 502))).toBe(true);
    expect(isRetryable(new ApiClientError("rate-limited.", 429))).toBe(true);
    expect(isRetryable(new ApiClientError("not configured.", 503))).toBe(false);
    expect(isRetryable(new ApiClientError("rejected credentials.", 502))).toBe(false);
    expect(isRetryable(new Error("not an ApiClientError"))).toBe(false);
    expect(isRetryable(null)).toBe(false);
  });
});
