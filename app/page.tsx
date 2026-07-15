"use client";

import {
  SignInButton,
  SignedIn,
  SignedOut,
  UserButton,
} from "@clerk/nextjs";
import Link from "next/link";

const pillars = [
  {
    title: "Live appointment booking",
    body: "Patients book over Telegram with real Google Calendar free/busy, same-day alternatives, and .ics email confirmation.",
  },
  {
    title: "Professional summaries",
    body: "Paste consultation notes and generate chart-ready summaries your team can review before filing.",
  },
  {
    title: "Actions & patient emails",
    body: "Clear follow-up action items plus patient-friendly email drafts you can review and send in one click.",
  },
];

function telegramHref(): string | null {
  const raw = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?.trim();
  if (!raw) return null;
  return `https://t.me/${raw.replace(/^@/, "")}`;
}

export default function HomePage() {
  const tg = telegramHref();
  const botLabel = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?.replace(
    /^@/,
    ""
  );

  return (
    <main className="min-h-screen">
      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="font-display text-xl font-semibold tracking-tight text-[var(--brand-deep)]">
          BrightCare Clinic
        </div>
        <div className="flex items-center gap-3">
          {tg && (
            <a
              href={tg}
              target="_blank"
              rel="noreferrer"
              className="hidden rounded-md border border-[var(--brand)] px-4 py-2 text-sm font-medium text-[var(--brand-deep)] sm:inline-flex"
            >
              Book on Telegram
            </a>
          )}
          <SignedOut>
            <SignInButton mode="modal">
              <button
                type="button"
                className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white shadow-sm"
              >
                Staff sign in
              </button>
            </SignInButton>
          </SignedOut>
          <SignedIn>
            <Link
              href="/notes"
              className="rounded-md border border-[var(--line)] bg-white/90 px-3 py-2 text-sm font-medium text-[var(--brand-deep)]"
            >
              Notes
            </Link>
            <Link
              href="/dashboard"
              className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white shadow-sm"
            >
              Status
            </Link>
            <UserButton />
          </SignedIn>
        </div>
      </header>

      <section
        className="relative isolate min-h-[78vh] overflow-hidden"
        style={{
          background:
            "linear-gradient(135deg, #00c2d1 0%, #00a8b5 42%, #2dd4e0 100%)",
        }}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              "radial-gradient(circle at 18% 28%, rgba(255,255,255,0.45) 0%, transparent 42%), radial-gradient(circle at 82% 68%, rgba(255,255,255,0.28) 0%, transparent 48%)",
          }}
        />
        <div className="relative mx-auto flex max-w-6xl flex-col justify-end px-6 pb-16 pt-20 md:min-h-[78vh] md:justify-center md:pb-24 md:pt-12">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-white/90">
            Convenient, hassle-free care
          </p>
          <h1 className="font-display mt-3 max-w-3xl text-5xl font-semibold leading-[1.05] text-white md:text-6xl lg:text-7xl">
            BrightCare Clinic
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-white/95 md:text-xl">
            Book visits on Telegram. Turn consultation notes into summaries,
            action items, and patient emails — in one staff workspace.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            {tg ? (
              <a
                href={tg}
                target="_blank"
                rel="noreferrer"
                className="rounded-md bg-white px-6 py-3.5 text-sm font-semibold text-[var(--brand-deep)] shadow-sm transition hover:bg-[var(--brand-soft)]"
              >
                Message @{botLabel}
              </a>
            ) : (
              <span className="rounded-md bg-white/20 px-5 py-3 text-sm text-white">
                Set NEXT_PUBLIC_TELEGRAM_BOT_USERNAME for booking
              </span>
            )}
            <SignedIn>
              <Link
                href="/notes"
                className="rounded-md border border-white/70 px-6 py-3.5 text-sm font-semibold text-white transition hover:bg-white/15"
              >
                Open notes assistant
              </Link>
            </SignedIn>
            <SignedOut>
              <SignInButton mode="modal">
                <button
                  type="button"
                  className="rounded-md border border-white/70 px-6 py-3.5 text-sm font-semibold text-white transition hover:bg-white/15"
                >
                  Staff: notes & status
                </button>
              </SignInButton>
            </SignedOut>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16">
        <p className="text-sm font-medium uppercase tracking-[0.16em] text-[var(--brand)]">
          How BrightCare works
        </p>
        <h2 className="font-display mt-2 text-3xl font-semibold text-[var(--brand-deep)] md:text-4xl">
          Booking for patients. Notes for clinicians.
        </h2>
        <div className="mt-10 grid gap-10 md:grid-cols-3 md:gap-8">
          {pillars.map((item, i) => (
            <article key={item.title} className="border-t-2 border-[var(--brand-soft)] pt-5">
              <p className="text-xs font-semibold tracking-wide text-[var(--brand)]">
                0{i + 1}
              </p>
              <h3 className="font-display mt-2 text-xl font-semibold text-[var(--brand-deep)]">
                {item.title}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-[var(--muted)]">
                {item.body}
              </p>
            </article>
          ))}
        </div>
        <p className="mt-12 text-sm text-[var(--muted)]">
          Mon–Fri 09:00–18:00 · Appointment only · 12 Orchard Rd
        </p>
      </section>
    </main>
  );
}
