"use client";

import { useEffect, useRef, useState } from "react";
import { isConfirmResponse } from "@/lib/validation";
import { tabStorage } from "@/lib/storage";
import { ApiClientError, confirmSession, createSession, isRetryable } from "@/lib/api";
import type { ConfirmResponse, SessionResponse } from "@/lib/types";
import { AppShell } from "@/components/shared/app-shell";
import { MatchReviewScreen } from "@/components/workflow/match-review-screen";
import { ProcessingScreen } from "@/components/workflow/processing-screen";
import { ResultScreen } from "@/components/workflow/result-screen";
import { UploadScreen } from "@/components/workflow/upload-screen";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const RESULT_STORAGE_KEY = "provenance-final-result";
const PENDING_STORAGE_KEY = "provenance-pending-session";

type Screen = "upload" | "processing" | "review" | "result";

function messageFrom(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") return "The request was cancelled.";
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function storedResult(): ConfirmResponse | null {
  try {
    const raw = tabStorage.get(RESULT_STORAGE_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    return isConfirmResponse(value) ? value : null;
  } catch {
    return null;
  }
}

export function Workflow() {
  const [restored, setRestored] = useState(false);
  const [screen, setScreen] = useState<Screen>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [requestErrorCode, setRequestErrorCode] = useState<string | undefined>(undefined);
  const [requestRetryable, setRequestRetryable] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [result, setResult] = useState<ConfirmResponse | null>(null);
  const busy = useRef(false);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!restored) return;
    const heading = document.querySelector<HTMLElement>("main h1");
    heading?.setAttribute("tabindex", "-1");
    heading?.focus();
  }, [screen, restored]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const previous = storedResult();
      if (previous) {
        setResult(previous);
        setScreen("result");
      } else if (tabStorage.get(PENDING_STORAGE_KEY)) {
        setRecoveryNotice("The unfinished session could not be restored after the page reload. Start a new analysis.");
        tabStorage.remove(PENDING_STORAGE_KEY);
      }
      setRestored(true);
    });
    return () => {
      active = false;
      activeRequest.current?.abort();
    };
  }, []);

  function selectFile(nextFile: File | null) {
    setFile(nextFile);
    setConsent(false);
    setRequestError(null);
    if (!nextFile) {
      setFileError(null);
    } else if (!ALLOWED_TYPES.has(nextFile.type)) {
      setFileError("Choose a JPEG, PNG, or WebP file.");
    } else if (nextFile.size === 0) {
      setFileError("This file is empty. Choose another photo.");
    } else if (nextFile.size > MAX_UPLOAD_BYTES) {
      setFileError("Choose a photo smaller than 10 MB.");
    } else {
      setFileError(null);
    }
  }

  function newController(): AbortController {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    return controller;
  }

  function saveResult(nextResult: ConfirmResponse) {
    tabStorage.remove(PENDING_STORAGE_KEY);
    tabStorage.set(RESULT_STORAGE_KEY, JSON.stringify(nextResult));
    setResult(nextResult);
    setScreen("result");
  }

  async function analyze() {
    if (!file || !consent || fileError || busy.current) return;
    busy.current = true;
    setRequestError(null);
    setScreen("processing");
    tabStorage.remove(RESULT_STORAGE_KEY);
    tabStorage.set(PENDING_STORAGE_KEY, "true");
    try {
      const controller = newController();
      const nextSession = await createSession(file, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setSession(nextSession);
      setSelectedIndex(nextSession.selected_candidate?.index ?? null);
      setReviewError(null);
      setScreen("review");
    } catch (error) {
      tabStorage.remove(PENDING_STORAGE_KEY);
      setRequestError(messageFrom(error));
      setRequestErrorCode(error instanceof ApiClientError ? error.errorCode : undefined);
      setRequestRetryable(isRetryable(error));
      setScreen("upload");
    } finally { busy.current = false; }
  }

  async function confirmReview() {
    if (!session || selectedIndex === null || busy.current) return;
    busy.current = true;
    setConfirming(true);
    setReviewError(null);
    try {
      const controller = newController();
      const nextResult = await confirmSession(session.session_id, selectedIndex, controller.signal);
      if (!controller.signal.aborted) saveResult(nextResult);
    } catch (error) {
      setReviewError(messageFrom(error));
    } finally {
      busy.current = false;
      setConfirming(false);
    }
  }

  function startOver() {
    activeRequest.current?.abort();
    busy.current = false;
    tabStorage.remove(PENDING_STORAGE_KEY);
    tabStorage.remove(RESULT_STORAGE_KEY);
    setScreen("upload");
    setFile(null);
    setConsent(false);
    setFileError(null);
    setRequestError(null);
    setRecoveryNotice(null);
    setSession(null);
    setSelectedIndex(null);
    setReviewError(null);
    setResult(null);
  }

  if (!restored) {
    return (
      <AppShell>
        <div className="py-16" role="status" aria-live="polite">
          <p className="text-sm text-muted">Restoring this tab</p>
        </div>
      </AppShell>
    );
  }

  const wide = screen === "review";
  return (
    <AppShell fingerprint={result?.fingerprint} wide={wide} stage={confirming ? "anchoring" : screen}>
      {screen === "upload" ? (
        <UploadScreen
          file={file}
          consent={consent}
          fileError={fileError}
          requestError={requestError}
          requestErrorCode={requestErrorCode}
          requestRetryable={requestRetryable}
          recoveryNotice={recoveryNotice}
          onFileChange={selectFile}
          onConsentChange={setConsent}
          onAnalyze={analyze}
        />
      ) : null}
      {screen === "processing" ? (
        <ProcessingScreen />
      ) : null}
      {screen === "review" && session ? (
        <MatchReviewScreen
          candidates={session.candidates}
          recommendedIndex={session.selected_candidate?.index ?? null}
          selectedIndex={selectedIndex}
          confirming={confirming}
          error={reviewError}
          onSelect={setSelectedIndex}
          onConfirm={confirmReview}
          onCancel={startOver}
        />
      ) : null}
      {screen === "result" && result ? <ResultScreen result={result} onStartOver={startOver} /> : null}
    </AppShell>
  );
}
