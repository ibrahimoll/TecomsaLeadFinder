import type { Metadata } from "next";
import { Geist, Geist_Mono, Poppins } from "next/font/google";

import "./globals.css";

// Self-hosted at build time by next/font: no runtime request to Google.
const sans = Geist({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });
// TECOMSA brand typeface, used for headings, figures and the wordmark.
const display = Poppins({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-display", display: "swap" });

export const metadata: Metadata = {
  title: "LeadFinder · Tecomsa",
  description: "Internal B2B prospecting platform for TECOMSA",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
