"use client";

import { useCallback, useEffect, useState } from "react";

type TgWebApp = {
  ready: () => void;
  expand: () => void;
  close: () => void;
  MainButton: {
    setText: (t: string) => void;
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
    showProgress: (leaveActive?: boolean) => void;
    hideProgress: () => void;
  };
  initDataUnsafe?: { user?: { id?: number } };
  themeParams?: Record<string, string>;
};

declare global {
  interface Window {
    Telegram?: { WebApp: TgWebApp };
  }
}

type BookResponse = {
  status: "confirm" | "booked" | "error" | "need_email";
  message: string;
  proposed_slot?: string | null;
};

type SlotItem = { start: string; label: string };

type Appointment = {
  start: string;
  status: string;
  email_masked: string;
};

const WEEKDAYS = [
  { value: "monday", label: "Monday" },
  { value: "tuesday", label: "Tuesday" },
  { value: "wednesday", label: "Wednesday" },
  { value: "thursday", label: "Thursday" },
  { value: "friday", label: "Friday" },
];

export default function TelegramMiniAppPage() {
  const [chatId, setChatId] = useState<string | null>(null);
  const [weekday, setWeekday] = useState("monday");
  const [time, setTime] = useState("14:00");
  const [email, setEmail] = useState("tamarubopal@gmail.com");
  const [step, setStep] = useState<"form" | "confirm" | "done" | "history">("form");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [inTelegram, setInTelegram] = useState(false);
  const [tg, setTg] = useState<TgWebApp | null>(null);
  const [slots, setSlots] = useState<SlotItem[]>([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [appointments, setAppointments] = useState<Appointment[]>([]);

  useEffect(() => {
    let cancelled = false;
    const init = () => {
      const webApp = window.Telegram?.WebApp;
      if (!webApp) return false;
      webApp.ready();
      webApp.expand();
      if (!cancelled) {
        setTg(webApp);
        setInTelegram(true);
        const id = webApp.initDataUnsafe?.user?.id;
        if (id) setChatId(String(id));
        const tp = webApp.themeParams;
        if (tp?.button_color) {
          document.documentElement.style.setProperty(
            "--brand",
            tp.button_color
          );
        }
      }
      return true;
    };
    if (init()) return;
    const timer = window.setInterval(() => {
      if (init()) window.clearInterval(timer);
    }, 100);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const loadSlots = useCallback(async (day: string) => {
    setSlotsLoading(true);
    try {
      const res = await fetch(`/api/telegram/slots?weekday=${day}`);
      if (!res.ok) throw new Error("Failed to load slots");
      const data = (await res.json()) as { slots: SlotItem[] };
      setSlots(data.slots);
      if (data.slots.length > 0) {
        const hhmm = data.slots[0].start.slice(11, 16);
        setTime(hhmm);
      }
    } catch {
      setSlots([]);
    } finally {
      setSlotsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSlots(weekday);
  }, [weekday, loadSlots]);

  const loadAppointments = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/telegram/appointments?chat_id=${encodeURIComponent(id)}`);
      if (!res.ok) return;
      const data = (await res.json()) as { appointments: Appointment[] };
      setAppointments(data.appointments);
    } catch {
      setAppointments([]);
    }
  }, []);

  useEffect(() => {
    if (chatId) void loadAppointments(chatId);
  }, [chatId, loadAppointments]);

  const postBook = useCallback(
    async (body: Record<string, unknown>): Promise<BookResponse> => {
      const res = await fetch("/api/telegram/book", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `Request failed (${res.status})`);
      }
      return res.json() as Promise<BookResponse>;
    },
    []
  );

  const submitRequest = useCallback(async () => {
    if (!chatId) {
      setMessage("Open this page from the BrightCare Telegram bot.");
      return;
    }
    if (!email.trim()) {
      setMessage("Please enter your email.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const data = await postBook({
        chat_id: chatId,
        action: "request",
        weekday,
        time,
        email: email.trim(),
      });
      setMessage(data.message);
      if (data.status === "confirm") {
        setStep("confirm");
      } else if (data.status === "booked") {
        setStep("done");
        void loadAppointments(chatId);
        tg?.close();
      } else if (data.status === "error") {
        setStep("form");
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }, [chatId, weekday, time, email, postBook, tg, loadAppointments]);

  const submitConfirm = useCallback(async () => {
    if (!chatId) return;
    setLoading(true);
    try {
      const data = await postBook({ chat_id: chatId, action: "confirm" });
      setMessage(data.message);
      if (data.status === "booked") {
        setStep("done");
        void loadAppointments(chatId);
        setTimeout(() => tg?.close(), 1500);
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Confirm failed.");
    } finally {
      setLoading(false);
    }
  }, [chatId, postBook, tg, loadAppointments]);

  useEffect(() => {
    if (!tg) return;
    const onMain = () => {
      if (step === "form") void submitRequest();
      else if (step === "confirm") void submitConfirm();
    };
    tg.MainButton.onClick(onMain);
    if (step === "form") {
      tg.MainButton.setText("Check availability");
      tg.MainButton.show();
    } else if (step === "confirm") {
      tg.MainButton.setText("Confirm booking");
      tg.MainButton.show();
    } else {
      tg.MainButton.hide();
    }
    return () => tg.MainButton.offClick(onMain);
  }, [tg, step, submitRequest, submitConfirm]);

  useEffect(() => {
    if (!tg) return;
    if (loading) tg.MainButton.showProgress();
    else tg.MainButton.hideProgress();
  }, [loading, tg]);

  const pickSlot = (slot: SlotItem) => {
    setTime(slot.start.slice(11, 16));
  };

  return (
    <main className="mx-auto max-w-md px-4 py-6">
      <h1 className="text-xl font-semibold text-[var(--brand-deep)]">
        BrightCare Clinic
      </h1>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Book a 30-minute appointment · Mon–Fri 09:00–18:00
      </p>

      <div className="mt-3 flex gap-2 text-sm">
        <button
          type="button"
          className={`rounded-md px-3 py-1 ${step === "form" || step === "confirm" || step === "done" ? "bg-[var(--brand)] text-white" : "border border-[var(--line)]"}`}
          onClick={() => setStep("form")}
        >
          Book
        </button>
        <button
          type="button"
          className={`rounded-md px-3 py-1 ${step === "history" ? "bg-[var(--brand)] text-white" : "border border-[var(--line)]"}`}
          onClick={() => setStep("history")}
        >
          My appointments
        </button>
      </div>

      {!inTelegram && (
        <p className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Open this page from the BrightCare Telegram bot menu (Open App) to
          book.
        </p>
      )}

      {step === "history" && (
        <div className="mt-6 space-y-3">
          {appointments.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No appointments yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {appointments.map((a, i) => (
                <li
                  key={`${a.start}-${i}`}
                  className="rounded-md border border-[var(--line)] bg-white p-3"
                >
                  <div>{a.start}</div>
                  <div className="text-[var(--muted)]">
                    {a.status} · {a.email_masked}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {step === "form" && (
        <div className="mt-6 space-y-4">
          <label className="block">
            <span className="text-sm font-medium">Day</span>
            <select
              className="mt-1 w-full rounded-md border border-[var(--line)] bg-white px-3 py-2"
              value={weekday}
              onChange={(e) => setWeekday(e.target.value)}
            >
              {WEEKDAYS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>

          <div>
            <span className="text-sm font-medium">Available times</span>
            {slotsLoading ? (
              <p className="mt-2 text-sm text-[var(--muted)]">Loading slots…</p>
            ) : slots.length === 0 ? (
              <p className="mt-2 text-sm text-[var(--muted)]">No slots free this day.</p>
            ) : (
              <div className="mt-2 grid grid-cols-3 gap-2">
                {slots.map((s) => {
                  const hhmm = s.start.slice(11, 16);
                  const selected = time === hhmm;
                  return (
                    <button
                      key={s.start}
                      type="button"
                      onClick={() => pickSlot(s)}
                      className="min-h-[44px] rounded-md border px-2 py-2 text-sm"
                      style={{
                        borderColor: selected ? "var(--brand)" : "var(--line)",
                        background: selected ? "var(--bg-accent)" : "white",
                        fontWeight: selected ? 600 : 400,
                      }}
                    >
                      {s.label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <label className="block">
            <span className="text-sm font-medium">Email</span>
            <input
              type="email"
              className="mt-1 w-full rounded-md border border-[var(--line)] bg-white px-3 py-2"
              placeholder="tamarubopal@gmail.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={loading}
            onClick={() => void submitRequest()}
            className="w-full rounded-md bg-[var(--brand)] py-3 text-sm font-semibold text-white disabled:opacity-60"
          >
            {loading ? "Checking…" : "Check availability"}
          </button>
        </div>
      )}

      {step === "confirm" && (
        <div className="mt-6 space-y-4">
          <p className="rounded-md border border-[var(--line)] bg-white p-4 text-sm leading-relaxed">
            {message}
          </p>
          <button
            type="button"
            disabled={loading}
            onClick={() => void submitConfirm()}
            className="w-full rounded-md bg-[var(--brand)] py-3 text-sm font-semibold text-white"
          >
            {loading ? "Booking…" : "Yes, book it"}
          </button>
          <button
            type="button"
            className="w-full rounded-md border border-[var(--line)] py-3 text-sm"
            onClick={() => {
              setStep("form");
              setMessage("");
            }}
          >
            Pick another time
          </button>
        </div>
      )}

      {step === "done" && (
        <div className="mt-6 rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-900">
          {message}
        </div>
      )}

      {message && step === "form" && (
        <p className="mt-4 text-sm text-[var(--muted)]">{message}</p>
      )}

      <p className="mt-8 text-xs text-[var(--muted)]">
        12 Orchard Rd · Appointment only · Parking on-site
      </p>
    </main>
  );
}
