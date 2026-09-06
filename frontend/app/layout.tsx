import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  applicationName: "ChitraPramaan",
  title: {
    default: "ChitraPramaan | Image Provenance & Verification",
    template: "%s | ChitraPramaan",
  },
  description: "Trace visual evidence, record a provenance claim on Sepolia, and independently re-verify its integrity.",
  manifest: "/site.webmanifest",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/android-chrome-192x192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
    shortcut: "/favicon.ico",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "ChitraPramaan",
  },
  openGraph: {
    type: "website",
    siteName: "ChitraPramaan",
    title: "ChitraPramaan | Image Provenance & Verification",
    description: "Trace visual evidence, record a provenance claim on Sepolia, and independently re-verify its integrity.",
    images: [{ url: "/android-chrome-512x512.png", width: 512, height: 512, alt: "ChitraPramaan logo" }],
  },
  twitter: {
    card: "summary",
    title: "ChitraPramaan | Image Provenance & Verification",
    description: "Trace visual evidence, record a provenance claim on Sepolia, and independently re-verify its integrity.",
    images: ["/android-chrome-512x512.png"],
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf9f6" },
    { media: "(prefers-color-scheme: dark)", color: "#191a18" },
  ],
  colorScheme: "light dark",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
