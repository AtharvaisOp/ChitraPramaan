import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import nextConfig from "../next.config";
import { UploadScreen } from "@/components/workflow/upload-screen";

function renderUploadScreen() {
  render(
    <UploadScreen
      file={null}
      consent={false}
      fileError={null}
      requestError={null}
      recoveryNotice={null}
      onFileChange={vi.fn()}
      onConsentChange={vi.fn()}
      onAnalyze={vi.fn()}
    />,
  );
}

function installCamera(getUserMedia: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: undefined,
  });
});

describe("camera capture", () => {
  it("allows same-origin camera access while keeping unrelated permissions disabled", async () => {
    if (!nextConfig.headers) throw new Error("security headers are not configured");
    const routes = await nextConfig.headers();
    const policy = routes
      .flatMap((route) => route.headers)
      .find((header) => header.key === "Permissions-Policy")?.value;

    expect(policy).toContain("camera=(self)");
    expect(policy).toContain("microphone=()");
    expect(policy).toContain("geolocation=()");
  });

  it("requests camera access only after the user presses Open camera", async () => {
    const stop = vi.fn();
    const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    installCamera(getUserMedia);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderUploadScreen();
    await user.click(screen.getByRole("tab", { name: "Use camera" }));
    expect(getUserMedia).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Open camera" }));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    expect(getUserMedia).toHaveBeenCalledWith({
      video: {
        facingMode: "user",
        width: { ideal: 1280 },
        height: { ideal: 960 },
      },
      audio: false,
    });
    expect(await screen.findByRole("button", { name: "Capture photo" })).toBeEnabled();
  });

  it("explains a remembered denial and lets the user retry", async () => {
    const getUserMedia = vi
      .fn()
      .mockRejectedValue(new DOMException("Permission denied", "NotAllowedError"));
    installCamera(getUserMedia);
    Object.defineProperty(navigator, "permissions", {
      configurable: true,
      value: { query: vi.fn().mockResolvedValue({ state: "denied" }) },
    });
    const user = userEvent.setup();

    renderUploadScreen();
    await user.click(screen.getByRole("tab", { name: "Use camera" }));
    await user.click(screen.getByRole("button", { name: "Open camera" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Open the site controls beside the address bar",
    );
    await user.click(screen.getByRole("button", { name: "Try camera again" }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
  });
});
