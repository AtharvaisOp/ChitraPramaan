const PLATFORM_LABELS: Array<[RegExp, string]> = [
  [/(^|\.)x\.com$/i, "X"],
  [/(^|\.)twitter\.com$/i, "X"],
  [/(^|\.)instagram\.com$/i, "Instagram"],
  [/(^|\.)facebook\.com$/i, "Facebook"],
  [/(^|\.)linkedin\.com$/i, "LinkedIn"],
  [/(^|\.)reddit\.com$/i, "Reddit"],
  [/(^|\.)tiktok\.com$/i, "TikTok"],
];

export function safeHttpUrl(value: string): URL | null {
  try {
    const parsed = new URL(value);
    return !parsed.username && !parsed.password && (parsed.protocol === "https:" || parsed.protocol === "http:") ? parsed : null;
  } catch {
    return null;
  }
}

export function platformFromUrl(value: string): string {
  const parsed = safeHttpUrl(value);
  if (!parsed) return "Unknown platform";
  const match = PLATFORM_LABELS.find(([pattern]) => pattern.test(parsed.hostname));
  return match?.[1] ?? parsed.hostname;
}

export function ipfsGatewayUrl(value: string): string | null {
  // Extract the same root CID as the read-only backend. No codec-prefix assumptions.
  let cid = value.trim();
  if (cid.startsWith("ipfs://")) cid = cid.slice(7).replace(/^ipfs\//, "");
  else if (cid.includes("/ipfs/")) cid = cid.split("/ipfs/")[1];
  cid = cid.split("/")[0];
  return /^[A-Za-z0-9]+$/.test(cid) ? `https://ipfs.io/ipfs/${encodeURIComponent(cid)}` : null;
}
