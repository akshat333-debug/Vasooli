import type { Metadata, Viewport } from "next";
import { Archivo, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import Sidebar from "@/components/Sidebar";
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

export const metadata: Metadata = {
  title: "Vasooli: bounded subscription recovery",
  description:
    "Treats subscription retries as a regulated, three-attempt budget, and spends them only on the failures that can actually be recovered.",
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
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
