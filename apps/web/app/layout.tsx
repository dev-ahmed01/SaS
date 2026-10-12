import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sponsor a Salah | Emlen Foundation",
  description: "Internal charity operations workspace for Emlen Foundation.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
