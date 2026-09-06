import { VerifyScreen } from "@/components/verify/verify-screen";

export default async function VerifyPage({
  params,
}: {
  params: Promise<{ fingerprint: string }>;
}) {
  const { fingerprint } = await params;
  // Next.js already decodes route params. Remount when the lookup key changes
  // so the previous claim's PASS state cannot appear under a new fingerprint.
  return <VerifyScreen key={fingerprint} initialFingerprint={fingerprint} />;
}
