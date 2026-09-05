import type { Metadata, Viewport } from "next";
import { Archivo, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import { batch } from "@/lib/data";
import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  axes: ["wdth"],
});
const instrument = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
});

export const viewport: Viewport = {
  // Matches --color-paper / the dark rail so the mobile browser chrome does not
  // sit against a colour the page never uses.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2efe7" },
    { media: "(prefers-color-scheme: dark)", color: "#f2efe7" },
  ],
};

const TITLE = "Vasooli: bounded subscription recovery";
const DESCRIPTION =
  "Treats subscription retries as a regulated, three-attempt budget, and spends them only on the failures that can actually be recovered. Razorpay AI Buildathon 2026, Track 03.";
const SITE_URL = "https://akshat333-debug.github.io/Vasooli/";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: TITLE,
  description: DESCRIPTION,
  // No image asset -- these still improve how the link renders when shared
  // (Slack, WhatsApp, X all read title/description even without an og:image).
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: "Vasooli",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${archivo.variable} ${instrument.variable} ${mono.variable}`}>
      <body>
        {/* Keyboard users land on the rail first and would otherwise tab through
            every nav item on every page before reaching the content. */}
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <div className="flex min-h-screen flex-col lg:flex-row">
          <Sidebar />
          <main id="main" className="min-w-0 flex-1">
            {/* The provenance of every figure on every page, pinned where it
                cannot be scrolled away from. A reader should never have to
                remember whether the numbers in front of them are real. */}
            <div className="flex justify-end border-b border-rule px-5 py-2 sm:px-8">
              <p className="tnum font-mono text-[10.5px] tracking-wider text-ink-faint uppercase">
                Batch {batch.meta.seed} · Synthetic · n={batch.meta.record_count} ·{" "}
                {batch.meta.batch_reference_time.slice(0, 10)}
              </p>
            </div>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
