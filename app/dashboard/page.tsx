"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type StatusPayload = {
  clinic_timezone: string;
  clinic_name: string;
  bot: { running: boolean; mode: string; username: string | null };
  integrations: {
    calendar: boolean;
    email: boolean;
    openai: boolean;
    telegram: boolean;
  };
  active_sessions: number;
  sessions: Array<{
    chat_id: string;
    state: string;
    has_email: boolean;
    proposed_slot: string | null;
    updated_at: string | null;
  }>;
  recent_events: Array<{
    ts: string;
    chat_id: string;
    intent: string | null;
    state: string | null;
    email_status: string | null;
    message: string | null;
  }>;
  recent_bookings?: Array<{
    id: number;
    event_id: string;
    start: string;
    status: string;
    email_masked: string;
  }>;
  integration_details?: Record<
    string,
    { ok: boolean; detail: string }
  >;
};

const PIPELINE = [
  "idle",
  "awaiting_email",
  "awaiting_slot_confirm",
  "awaiting_alt_confirm",
  "awaiting_cancel_confirm",
  "awaiting_reschedule",
  "booked",
] as const;

function Chip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm"
      style={{
        borderColor: ok ? "#86efac" : "#fca5a5",
        background: ok ? "#f0fdf4" : "#fef2f2",
        color: ok ? "var(--ok)" : "var(--bad)",
      }}
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: ok ? "var(--ok)" : "var(--bad)" }}
      />
      {label}
    </span>
  );
}

export default function DashboardPage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch("/api/status", { headers });
      if (!res.ok) {
        setError(`Status ${res.status}`);
        return;
      }
      setStatus(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load status");
    }
  }, [getToken]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    void load();
    const id = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(id);
  }, [isLoaded, isSignedIn, load]);

  const activeState =
    status?.sessions.find((s) => s.state !== "idle")?.state ?? "idle";
  const botUsername =
    status?.bot.username ||
    process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME ||
    "";

  return (
    <main className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <Link href="/" className="text-lg font-semibold text-[var(--brand-deep)]">
          BrightCare Clinic
        </Link>
        <div className="flex items-center gap-3">
          <Link
            href="/notes"
            className="rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm"
          >
            Notes
          </Link>
          <UserButton />
        </div>
      </header>

      <section className="mx-auto max-w-5xl px-6 pb-16">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold text-[var(--brand-deep)]">
              Current Status
            </h1>
            <p className="mt-1 text-sm text-[var(--muted)]">
              Live pipeline for the Telegram booking agent
              {status ? ` · ${status.clinic_timezone}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm"
          >
            Refresh
          </button>
        </div>

        {error && (
          <p className="mt-4 text-sm text-[var(--bad)]">{error}</p>
        )}

        <div className="mt-6 flex flex-wrap gap-2">
          <Chip ok={!!status?.bot.running} label="Bot" />
          <Chip ok={!!status?.integrations.calendar} label="Calendar" />
          <Chip ok={!!status?.integrations.email} label="Email" />
          <Chip ok={!!status?.integrations.openai} label="OpenAI" />
          <Chip ok={!!status?.integrations.telegram} label="Telegram" />
        </div>

        {status?.integration_details && (
          <ul className="mt-3 space-y-1 text-xs text-[var(--muted)]">
            {Object.entries(status.integration_details)
              .filter(([k]) => k !== "all_ok")
              .map(([name, probe]) => (
                <li key={name}>
                  <span className={probe.ok ? "text-[var(--ok)]" : "text-[var(--bad)]"}>
                    {name}
                  </span>
                  {": "}
                  {probe.detail}
                </li>
              ))}
          </ul>
        )}

        <div className="mt-8 border border-[var(--line)] bg-white p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Booking pipeline
          </h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {PIPELINE.map((step) => {
              const on = activeState === step;
              return (
                <span
                  key={step}
                  className="rounded-md px-3 py-2 text-xs font-medium"
                  style={{
                    background: on ? "var(--brand)" : "var(--bg-accent)",
                    color: on ? "#fff" : "var(--muted)",
                  }}
                >
                  {step.replaceAll("_", " ")}
                </span>
              );
            })}
          </div>
          <p className="mt-3 text-sm text-[var(--muted)]">
            Active conversations: {status?.active_sessions ?? "—"}
          </p>
        </div>

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <div className="border border-[var(--line)] bg-white p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
              Active conversations
            </h2>
            <ul className="mt-3 space-y-2 text-sm">
              {(status?.sessions ?? []).length === 0 && (
                <li className="text-[var(--muted)]">No sessions yet.</li>
              )}
              {(status?.sessions ?? []).map((s) => (
                <li
                  key={s.chat_id + s.state}
                  className="flex justify-between gap-2 border-b border-[var(--line)] py-2"
                >
                  <span>{s.chat_id}</span>
                  <span className="text-[var(--muted)]">{s.state}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="border border-[var(--line)] bg-white p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
              Recent activity
            </h2>
            <ul className="mt-3 space-y-2 text-sm">
              {(status?.recent_events ?? []).length === 0 && (
                <li className="text-[var(--muted)]">No events yet.</li>
              )}
              {(status?.recent_events ?? []).map((e, i) => (
                <li
                  key={`${e.ts}-${i}`}
                  className="border-b border-[var(--line)] py-2 text-[var(--muted)]"
                >
                  <span className="text-[var(--ink)]">{e.intent ?? "—"}</span>
                  {" · "}
                  {e.state ?? "—"}
                  {e.email_status ? ` · email ${e.email_status}` : ""}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-6 border border-[var(--line)] bg-white p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Recent bookings
          </h2>
          <ul className="mt-3 space-y-2 text-sm">
            {(status?.recent_bookings ?? []).length === 0 && (
              <li className="text-[var(--muted)]">No bookings yet.</li>
            )}
            {(status?.recent_bookings ?? []).map((b) => (
              <li
                key={b.id}
                className="flex justify-between gap-2 border-b border-[var(--line)] py-2"
              >
                <span>{b.start}</span>
                <span className="text-[var(--muted)]">{b.status}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-6 border border-[var(--line)] bg-white p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            How patients book
          </h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Message the Telegram bot
            {botUsername ? (
              <>
                {" "}
                <a
                  className="font-medium text-[var(--brand)]"
                  href={`https://t.me/${botUsername.replace(/^@/, "")}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  @{botUsername.replace(/^@/, "")}
                </a>
              </>
            ) : (
              " (set NEXT_PUBLIC_TELEGRAM_BOT_USERNAME)"
            )}
            . Example: “Can I book Monday at 2pm?”
          </p>
        </div>
      </section>
    </main>
  );
}
