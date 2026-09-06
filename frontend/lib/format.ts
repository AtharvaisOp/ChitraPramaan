const FINGERPRINT_PATTERN = /^(?:0x)?[0-9a-fA-F]{64}$/;

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(3) : "Unavailable";
}

export function shortFingerprint(value: string): string {
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-8)}` : value;
}

export function isValidFingerprint(value: string): boolean {
  return FINGERPRINT_PATTERN.test(value.trim());
}

export function formatTimestamp(timestamp: number): string {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "Not available";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "long",
    timeZone: "UTC",
  }).format(new Date(timestamp * 1000));
}
