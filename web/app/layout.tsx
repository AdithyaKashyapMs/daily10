import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import Navbar from "@/components/Navbar";
import { RegisterServiceWorker } from "@/components/RegisterServiceWorker";
import "./globals.css";

// Same faces as EventSnap: Baloo 2 for headings, Nunito for text. SIL Open Font License,
// self-hosted so builds need no network access.
const baloo = localFont({ src: "../fonts/baloo2-latin-variable.woff2", weight: "600 800", variable: "--font-baloo", display: "swap" });
const nunito = localFont({ src: "../fonts/nunito-latin-variable.woff2", weight: "400 800", variable: "--font-nunito", display: "swap" });

export const metadata: Metadata = {
  title: "Daily 10 - Ten minutes a day, no exam panic",
  description: "Your syllabus in ten-minute daily sessions, built from your own college notes and past papers.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Daily 10", statusBarStyle: "default" },
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${baloo.variable} ${nunito.variable}`}>
      <body className="min-h-dvh bg-paper text-ink">
        <Navbar />
        <main>{children}</main>
        <RegisterServiceWorker />
      </body>
    </html>
  );
}
