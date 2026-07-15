"use client";

import Script from "next/script";

export function TelegramWebAppScript() {
  return (
    <Script
      src="https://telegram.org/js/telegram-web-app.js"
      strategy="afterInteractive"
    />
  );
}
