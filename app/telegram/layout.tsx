import type { Metadata } from "next";

import { TelegramWebAppScript } from "./TelegramWebAppScript";

export const metadata: Metadata = {
  title: "BrightCare — Book appointment",
  description: "Book a BrightCare Clinic appointment",
};

export default function TelegramLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <TelegramWebAppScript />
      <div className="min-h-screen bg-[var(--bg)] text-[var(--ink)]">{children}</div>
    </>
  );
}
