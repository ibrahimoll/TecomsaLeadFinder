import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "TECOMSA LeadFinder AI",
  description: "Internal B2B prospecting platform for TECOMSA",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
