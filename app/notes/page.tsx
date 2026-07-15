"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useCallback, useState } from "react";

type NotesResult = {
  summary: string;
  action_items: string[];
  patient_email: { subject: string; body: string };
};

const DEFAULT_PATIENT_EMAIL = "tamarubopal@gmail.com";

export default function NotesPage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [patientName, setPatientName] = useState("");
  const [patientEmail, setPatientEmail] = useState(DEFAULT_PATIENT_EMAIL);
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<NotesResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendMessage, setSendMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const authHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }, [getToken]);

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSendMessage(null);
    try {
      const res = await fetch("/api/notes/generate", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          notes,
          patient_name: patientName.trim() || null,
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Request failed (${res.status})`);
      }
      setResult((await res.json()) as NotesResult);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, notes, patientName]);

  const sendToPatient = useCallback(async () => {
    if (!result) return;
    const email = patientEmail.trim();
    if (!email.includes("@")) {
      setSendMessage("Enter a valid patient email first.");
      return;
    }
    const ok = window.confirm(
      `Send this email to ${email}?\n\nSubject: ${result.patient_email.subject}`
    );
    if (!ok) return;

    setSending(true);
    setSendMessage(null);
    setError(null);
    try {
      const res = await fetch("/api/notes/send", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          patient_email: email,
          subject: result.patient_email.subject,
          body: result.patient_email.body,
        }),
      });
      if (!res.ok) {
        let detail = await res.text();
        try {
          const parsed = JSON.parse(detail) as { detail?: string };
          detail = parsed.detail || detail;
        } catch {
          /* plain text */
        }
        throw new Error(detail || `Send failed (${res.status})`);
      }
      setSendMessage(`Email sent to ${email}.`);
    } catch (e) {
      setSendMessage(
        e instanceof Error ? e.message : "Could not send email."
      );
    } finally {
      setSending(false);
    }
  }, [authHeaders, patientEmail, result]);

  const copyText = async (label: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    window.setTimeout(() => setCopied(null), 1500);
  };

  if (!isLoaded) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-16 text-[var(--muted)]">
        Loading…
      </main>
    );
  }

  if (!isSignedIn) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-16">
        <p className="text-[var(--muted)]">Please sign in to use Notes.</p>
        <Link href="/" className="mt-4 inline-block text-[var(--brand)]">
          Back home
        </Link>
      </main>
    );
  }

  return (
    <main className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-4">
          <Link
            href="/"
            className="font-display text-lg font-semibold text-[var(--brand-deep)]"
          >
            BrightCare Clinic
          </Link>
          <nav className="flex gap-2 text-sm">
            <Link
              href="/notes"
              className="rounded-md bg-[var(--brand)] px-3 py-1.5 font-medium text-white"
            >
              Notes
            </Link>
            <Link
              href="/dashboard"
              className="rounded-md border border-[var(--line)] bg-white px-3 py-1.5 text-[var(--brand-deep)]"
            >
              Status
            </Link>
          </nav>
        </div>
        <UserButton />
      </header>

      <section className="mx-auto max-w-5xl px-6 pb-16">
        <h1 className="font-display text-3xl font-semibold text-[var(--brand-deep)] md:text-4xl">
          Consultation notes
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          Paste your visit notes. BrightCare generates a professional summary,
          clinician action items, and a patient-friendly email draft — review it,
          then send directly to the patient.
        </p>

        <div className="mt-8 grid gap-8 lg:grid-cols-2">
          <div className="space-y-4">
            <label className="block">
              <span className="text-sm font-medium">Patient name (optional)</span>
              <input
                className="mt-1 w-full rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm"
                value={patientName}
                onChange={(e) => setPatientName(e.target.value)}
                placeholder="e.g. Priya S."
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Patient email</span>
              <input
                type="email"
                className="mt-1 w-full rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm"
                value={patientEmail}
                onChange={(e) => setPatientEmail(e.target.value)}
                placeholder={DEFAULT_PATIENT_EMAIL}
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Consultation notes</span>
              <textarea
                className="mt-1 min-h-[280px] w-full rounded-md border border-[var(--line)] bg-white px-3 py-3 text-sm leading-relaxed"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={
                  "Chief complaint…\nHistory…\nExam findings…\nAssessment & plan…"
                }
              />
            </label>
            <button
              type="button"
              disabled={loading || notes.trim().length < 20}
              onClick={() => void generate()}
              className="w-full rounded-md bg-[var(--brand)] py-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              {loading ? "Generating…" : "Generate summary, actions & email"}
            </button>
            {error && <p className="text-sm text-[var(--bad)]">{error}</p>}
          </div>

          <div className="space-y-5">
            {!result && (
              <p className="rounded-md border border-dashed border-[var(--line)] bg-white/60 p-6 text-sm text-[var(--muted)]">
                Results appear here after you generate. Review the draft, then
                approve and send to the patient email above.
              </p>
            )}

            {result && (
              <>
                <OutputBlock
                  title="Professional summary"
                  text={result.summary}
                  copied={copied === "summary"}
                  onCopy={() => void copyText("summary", result.summary)}
                />
                <div className="border border-[var(--line)] bg-white p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
                      Action items
                    </h2>
                    <button
                      type="button"
                      className="text-xs font-medium text-[var(--brand)]"
                      onClick={() =>
                        void copyText(
                          "actions",
                          result.action_items
                            .map((a, i) => `${i + 1}. ${a}`)
                            .join("\n")
                        )
                      }
                    >
                      {copied === "actions" ? "Copied" : "Copy"}
                    </button>
                  </div>
                  <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm">
                    {result.action_items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ol>
                </div>
                <div className="border border-[var(--line)] bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
                      Patient email draft
                    </h2>
                    <div className="flex gap-3">
                      <button
                        type="button"
                        className="text-xs font-medium text-[var(--brand)]"
                        onClick={() =>
                          void copyText(
                            "email",
                            `Subject: ${result.patient_email.subject}\n\n${result.patient_email.body}`
                          )
                        }
                      >
                        {copied === "email" ? "Copied" : "Copy"}
                      </button>
                      <button
                        type="button"
                        disabled={sending || !patientEmail.trim()}
                        onClick={() => void sendToPatient()}
                        className="rounded-md bg-[var(--brand)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                      >
                        {sending ? "Sending…" : "Send to patient"}
                      </button>
                    </div>
                  </div>
                  <p className="mt-3 text-sm font-medium text-[var(--brand-deep)]">
                    {result.patient_email.subject}
                  </p>
                  <pre className="mt-2 whitespace-pre-wrap font-[family-name:var(--font-body)] text-sm leading-relaxed text-[var(--muted)]">
                    {result.patient_email.body}
                  </pre>
                  {sendMessage && (
                    <p
                      className={`mt-3 text-sm ${
                        sendMessage.startsWith("Email sent")
                          ? "text-[var(--ok)]"
                          : "text-[var(--bad)]"
                      }`}
                    >
                      {sendMessage}
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

function OutputBlock({
  title,
  text,
  copied,
  onCopy,
}: {
  title: string;
  text: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="border border-[var(--line)] bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          {title}
        </h2>
        <button
          type="button"
          className="text-xs font-medium text-[var(--brand)]"
          onClick={onCopy}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
    </div>
  );
}
