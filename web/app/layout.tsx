import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { TooltipProvider } from "@/components/ui/tooltip";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: {
    default: "IgnitIQ · Fire safety analyst for space habitats",
    template: "%s · IgnitIQ",
  },
  description:
    "Pick a habitat atmosphere, ask a fire safety question, and get an answer computed from real ISS combustion test rows and cited to the NASA PSI investigation.",
  applicationName: "IgnitIQ",
};

export const viewport: Viewport = {
  themeColor: "#0d1017",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${sans.variable} ${mono.variable} flex min-h-dvh flex-col bg-background font-sans antialiased`}
      >
        <TooltipProvider>
          <SiteHeader />
          <main className="bg-grid flex-1">
            <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">{children}</div>
          </main>
          <SiteFooter />
        </TooltipProvider>
      </body>
    </html>
  );
}