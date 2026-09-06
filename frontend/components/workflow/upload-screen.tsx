import { useEffect, useRef, useState } from "react";
import { FileImage, Camera, ArrowCounterClockwise, LockKey, ShieldCheck, ArrowRight, Scan, GitBranch, Fingerprint } from "@phosphor-icons/react";
import { ApiErrorAlert } from "@/components/shared/api-error-alert";
import { formatFileSize } from "@/lib/format";

type SourceMode = "upload" | "camera";
type CameraStatus = "idle" | "requesting" | "live" | "captured" | "denied" | "unsupported";
type PolicyDocument = Document & {
  permissionsPolicy?: { allowsFeature: (feature: string) => boolean };
  featurePolicy?: { allowsFeature: (feature: string) => boolean };
};

function stopTracks(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

function pageAllowsCamera(): boolean {
  const policyDocument = document as PolicyDocument;
  const policy = policyDocument.permissionsPolicy ?? policyDocument.featurePolicy;
  return policy?.allowsFeature("camera") ?? true;
}

async function cameraPermissionMessage(): Promise<string> {
  if (!pageAllowsCamera()) {
    return "Live camera access is disabled by this page's security policy. Use file upload while the site configuration is corrected.";
  }
  if (window.isSecureContext === false) {
    return "Live camera access requires HTTPS or localhost. Open this site securely, then try again.";
  }
  try {
    const permission = await navigator.permissions?.query({ name: "camera" as PermissionName });
    if (permission?.state === "denied") {
      return "Camera permission is blocked for this site. Open the site controls beside the address bar, allow Camera, then try again.";
    }
  } catch {
    // The Permissions API does not expose camera state in every browser.
  }
  return "Camera permission was not granted. Choose Allow in the browser prompt, then try again.";
}

export function UploadScreen({
  file,
  consent,
  fileError,
  requestError,
  requestErrorCode,
  requestRetryable,
  recoveryNotice,
  onFileChange,
  onConsentChange,
  onAnalyze,
}: {
  file: File | null;
  consent: boolean;
  fileError: string | null;
  requestError: string | null;
  requestErrorCode?: string;
  requestRetryable?: boolean;
  recoveryNotice: string | null;
  onFileChange: (file: File | null) => void;
  onConsentChange: (checked: boolean) => void;
  onAnalyze: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [mode, setMode] = useState<SourceMode>("upload");
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>("idle");
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [capturedUrl, setCapturedUrl] = useState<string | null>(null);
  const preview = useRef<HTMLImageElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const nativeCameraRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!file || fileError || !preview.current) return;
    const url = URL.createObjectURL(file);
    preview.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file, fileError, mode]);

  // Request the live camera only after the <video> element is mounted.
  useEffect(() => {
    if (cameraStatus !== "requesting") return;
    let cancelled = false;
    async function requestCamera() {
      if (!navigator.mediaDevices?.getUserMedia) {
        if (!cancelled) {
          setCameraStatus("unsupported");
          setCameraError(
            window.isSecureContext === false
              ? "Live camera access requires HTTPS or localhost. Open this site securely, then try again."
              : "This browser cannot open a live camera. Use file upload or device capture instead.",
          );
        }
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
          audio: false,
        });
        if (cancelled) {
          stopTracks(stream);
          return;
        }
        stopTracks(streamRef.current);
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
        setCameraStatus("live");
        setCameraError(null);
      } catch (error) {
        if (cancelled) return;
        const name = error instanceof DOMException ? error.name : "";
        if (name === "NotAllowedError" || name === "SecurityError") {
          const message = await cameraPermissionMessage();
          if (cancelled) return;
          setCameraStatus("denied");
          setCameraError(message);
        } else if (name === "NotFoundError" || name === "OverconstrainedError") {
          setCameraStatus("denied");
          setCameraError("No usable camera was found. Try file upload or take a photo instead.");
        } else {
          setCameraStatus("denied");
          setCameraError("The camera could not be opened. Try again, or use file upload instead.");
        }
      }
    }
    void requestCamera();
    return () => {
      cancelled = true;
    };
  }, [cameraStatus]);

  // Always release the camera on unmount.
  useEffect(() => () => {
    stopTracks(streamRef.current);
    streamRef.current = null;
  }, []);

  // Revoke the captured still preview when it is replaced or the component unmounts.
  useEffect(() => () => {
    if (capturedUrl) URL.revokeObjectURL(capturedUrl);
  }, [capturedUrl]);

  function switchMode(next: SourceMode) {
    setMode(next);
    if (next === "upload") {
      stopTracks(streamRef.current);
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      if (cameraStatus === "requesting" || cameraStatus === "live") setCameraStatus("idle");
      setCameraError(null);
    }
  }

  function openCamera() {
    if (capturedUrl) URL.revokeObjectURL(capturedUrl);
    setCapturedUrl(null);
    setCameraError(null);
    setCameraStatus("requesting");
  }

  function capturePhoto() {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) {
      setCameraError("The camera preview is not ready yet. Wait a moment and try again.");
      return;
    }
    const maxSide = 1600;
    const scale = Math.min(1, maxSide / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const context = canvas.getContext("2d");
    if (!context) {
      setCameraError("This browser could not capture the photo. Try file upload instead.");
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setCameraError("This browser could not capture the photo. Try file upload instead.");
          return;
        }
        const captured = new File([blob], "camera-photo.jpg", { type: "image/jpeg" });
        onFileChange(captured);
        if (capturedUrl) URL.revokeObjectURL(capturedUrl);
        setCapturedUrl(URL.createObjectURL(blob));
        stopTracks(streamRef.current);
        streamRef.current = null;
        if (videoRef.current) videoRef.current.srcObject = null;
        setCameraStatus("captured");
        setCameraError(null);
      },
      "image/jpeg",
      0.92,
    );
  }

  function retakePhoto() {
    if (capturedUrl) URL.revokeObjectURL(capturedUrl);
    setCapturedUrl(null);
    setCameraError(null);
    setCameraStatus("requesting");
  }

  const ready = Boolean(file && consent && !fileError);
  const cameraActive = cameraStatus === "live" || cameraStatus === "requesting";

  return (
    <section aria-labelledby="upload-heading" className="upload-layout">
      <div className="upload-intro">
        <p className="intro-eyebrow" data-intro>Curiosity, backed by evidence.</p>
        <h1 id="upload-heading" className="upload-title max-w-5xl" data-intro>
          Analyze a photo
        </h1>
        <p className="upload-title-follow" data-intro>Follow its story.</p>
        <p className="intro-description" data-intro>
          Discover where a similar image appears online. Choose the source that fits, then create a record anyone can check.
        </p>
        <div className="photo-composition" aria-hidden="true" data-intro>
          <div className="composition-orbit" />
          <div className="art-photo art-photo-back"><div className="abstract-scene" /></div>
          <div className="art-photo art-photo-front"><div className="abstract-scene"><span className="art-sun" /><span className="art-hill hill-back" /><span className="art-hill hill-front" /><span className="scan-corner corner-one" /><span className="scan-corner corner-two" /></div><span className="art-caption">Every image leaves a trace.<Fingerprint size={16} /></span></div>
          <span className="composition-note">An image. A source. A record.</span>
        </div>
        <p className="source-strip"><span>Across public sources</span><span>Instagram</span><span>Facebook</span><span>X</span><span>+ more</span></p>
      </div>

      <div className="upload-panel" data-intro>
        <div className="panel-heading"><div><h2>Start with your photo</h2><p>A clear face makes a better starting point.</p></div><span className="panel-icon"><FileImage size={22} weight="light" /></span></div>
        <div className="space-y-5">
          {recoveryNotice ? (
            <div className="rounded-lg border border-warning/30 bg-warning-soft p-4 text-sm text-ink" role="status">
              {recoveryNotice}
            </div>
          ) : null}
          {requestError ? (
            <ApiErrorAlert
              title="Analysis could not be completed"
              message={requestError}
              errorCode={requestErrorCode}
              onRetry={requestRetryable && ready ? onAnalyze : undefined}
            />
          ) : null}

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-4">
              <span className="text-sm font-semibold">Photo</span>
              <span className="text-xs text-muted">One image per analysis</span>
            </div>
            <div className="source-tabs" role="tablist" aria-label="Photo source">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "upload"}
                data-active={mode === "upload"}
                className="source-tab"
                onClick={() => switchMode("upload")}
              >
                <FileImage aria-hidden size={16} weight="light" /> Upload file
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "camera"}
                data-active={mode === "camera"}
                className="source-tab"
                onClick={() => switchMode("camera")}
              >
                <Camera aria-hidden size={16} weight="light" /> Use camera
              </button>
            </div>
            {mode === "upload" ? (
              <div className="drop-zone" data-dragging={dragging}
                onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => { event.preventDefault(); setDragging(false); onFileChange(event.dataTransfer.files?.[0] ?? null); }}>
                {file && !fileError ? (
                  // Local blob preview; no image data leaves the browser until consented analysis.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img ref={preview} alt="Selected photo preview" className="preview-image" />
                ) : <FileImage aria-hidden size={38} weight="light" className="shrink-0 text-accent" />}
                <div><span className="block font-semibold">{file ? "Replace photo" : "Drop your photo here"}</span>
                  <span className="mt-2 block text-sm text-muted">or <span className="font-medium text-accent underline underline-offset-4">choose a file</span> from your device</span></div>
                <input id="photo" name="photo" type="file" accept="image/jpeg,image/png,image/webp"
                  aria-describedby={`photo-help${fileError ? " photo-error" : ""}`} aria-invalid={Boolean(fileError)}
                  onChange={(event) => { const selected = event.target.files?.[0]; if (selected) onFileChange(selected); event.target.value = ""; }} />
              </div>
            ) : (
              <div className="camera-frame" data-status={cameraStatus}>
                {cameraStatus === "live" || cameraStatus === "requesting" ? (
                  <>
                    <div className="camera-viewfinder">
                      <video ref={videoRef} autoPlay playsInline muted aria-label="Live camera preview" />
                      <span className="scan-corner corner-one" aria-hidden="true" />
                      <span className="scan-corner corner-two" aria-hidden="true" />
                      {cameraStatus === "requesting" ? <span className="camera-loading" role="status">Opening camera…</span> : null}
                    </div>
                    <div className="camera-actions">
                      <button type="button" className="camera-capture" onClick={capturePhoto} disabled={cameraStatus !== "live"}>
                        <Camera aria-hidden size={17} weight="bold" /> Capture photo
                      </button>
                    </div>
                  </>
                ) : cameraStatus === "captured" ? (
                  <>
                    <div className="camera-viewfinder">
                      {capturedUrl ? (
                        // Local captured still; same privacy rule as file preview.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={capturedUrl} alt="Captured photo preview" className="camera-still" />
                      ) : null}
                    </div>
                    <div className="camera-actions">
                      <button type="button" className="camera-secondary" onClick={retakePhoto}>
                        <ArrowCounterClockwise aria-hidden size={16} /> Retake
                      </button>
                      <button type="button" className="camera-capture" onClick={() => switchMode("upload")}>
                        Use this photo
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <Camera aria-hidden size={38} weight="light" className="shrink-0 text-accent camera-idle-icon" />
                    <div>
                      <span className="block font-semibold">Take a photo with your camera</span>
                      <span className="mt-2 block text-sm text-muted">Position one face in good light, then capture.</span>
                    </div>
                    <div className="camera-actions">
                      <button type="button" className="camera-capture" onClick={openCamera}>
                        <Camera aria-hidden size={17} weight="bold" /> Open camera
                      </button>
                      <button type="button" className="camera-secondary" onClick={() => nativeCameraRef.current?.click()}>
                        Take photo
                      </button>
                    </div>
                    <input
                      ref={nativeCameraRef}
                      type="file"
                      accept="image/*"
                      capture="environment"
                      className="sr-only"
                      tabIndex={-1}
                      aria-label="Take a photo with the device camera"
                      onChange={(event) => { const selected = event.target.files?.[0]; if (selected) onFileChange(selected); event.target.value = ""; }}
                    />
                  </>
                )}
                {cameraError ? <p role="alert" className="camera-error">{cameraError}</p> : null}
                {(cameraStatus === "denied" || cameraStatus === "unsupported") ? (
                  <div className="camera-actions">
                    {cameraStatus === "denied" ? (
                      <button type="button" className="camera-capture" onClick={openCamera}>
                        <Camera aria-hidden size={17} weight="bold" /> Try camera again
                      </button>
                    ) : null}
                    <button type="button" className="camera-secondary" onClick={() => nativeCameraRef.current?.click()}>
                      Use device capture
                    </button>
                    <button type="button" className="camera-secondary" onClick={() => switchMode("upload")}>
                      Back to file upload
                    </button>
                  </div>
                ) : null}
              </div>
            )}
            <p id="photo-help" className="text-xs leading-5 text-muted">JPEG, PNG or WebP · Up to 10 MB and 25 megapixels. Use a clear photo with one visible face.</p>
            {file ? <div className="flex min-w-0 items-center gap-3 text-sm">
              <span className="min-w-0 flex-1 truncate">{file.name}</span><span className="shrink-0 font-mono text-xs text-muted">{formatFileSize(file.size)}</span>
              <button type="button" onClick={() => onFileChange(null)} className="px-2 text-xs font-medium text-accent" aria-label="Remove photo">Remove</button>
            </div> : null}
            {fileError ? <p id="photo-error" role="alert" className="text-sm font-medium text-danger">{fileError}</p> : null}
            {mode === "camera" && cameraActive ? (
              <p className="text-xs leading-5 text-muted">Camera stays on this device. Nothing is uploaded until you press Analyze.</p>
            ) : null}
          </div>

          <label className="consent-field flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => onConsentChange(event.target.checked)}
              className="mt-0.5 size-5 shrink-0 accent-[var(--accent)]"
            />
            <span className="text-sm leading-6">
              I confirm that I have the right to search the web for the person in this photo.
            </span>
          </label>

          <button
            type="button"
            disabled={!ready}
            onClick={onAnalyze}
            className="primary-analyze inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-5 py-3 font-semibold text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45 dark:text-zinc-950"
          >
            <ShieldCheck aria-hidden size={20} weight="bold" />
            Analyze <ArrowRight aria-hidden size={18} />
          </button>
          <p className="upload-privacy"><LockKey aria-hidden size={15} /><span>Your face crop is sent to a search provider. You review the matches before anything is recorded publicly.</span></p>
        </div>
      </div>

      <aside className="upload-aside" aria-label="What happens next">
        <div className="how-heading" data-scroll-reveal><h2>A little context.<br /><span>A clearer picture.</span></h2><p>From a photo to a verifiable record,<br />with you in control at every step.</p></div>
        <ol className="how-grid text-sm leading-6 text-muted">
          <li data-scroll-reveal><Scan aria-hidden size={23} /><span className="block font-semibold text-ink">Find the trail</span>We look for visually similar images across supported public sources.</li>
          <li data-scroll-reveal><GitBranch aria-hidden size={23} /><span className="block font-semibold text-ink">Make the choice</span>Compare the matches. Keep the recommendation or choose another source. You always confirm.</li>
          <li data-scroll-reveal><Fingerprint aria-hidden size={23} /><span className="block font-semibold text-ink">Keep the evidence</span>Your chosen claim is pinned to IPFS and recorded on Sepolia, ready for an independent check.</li>
        </ol>
        <div className="evidence-note mt-9 text-xs leading-6 text-muted"><p className="font-semibold text-ink">What this establishes</p>A match means an image resembling this face appears at a URL. It does not confirm identity.</div>
        <details className="mt-6 border-t border-line text-xs leading-6 text-muted"><summary className="font-medium text-ink">Privacy & subject selection</summary><p>Choose a single-face photo. If several faces are present, the backend selects one using its deterministic area-and-detection-score policy. Raw face embeddings are never included in the claim. Pending review sessions expire after 30 minutes.</p></details>
      </aside>
    </section>
  );
}
