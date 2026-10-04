"use client";

import { useEffect } from "react";

const ONBOARD_KEY = "daily.onboarded";

/** First visit lands on the welcome page. Home-only (a deep link straight to
 * Knowledge or an item is deliberate and never hijacked); the flag is written
 * by the welcome page's "Enter daily". `navigate` is injectable for tests. */
export function WelcomeGate({
  navigate = (url: string) => window.location.replace(url),
}: {
  navigate?: (url: string) => void;
}) {
  useEffect(() => {
    try {
      if (window.localStorage.getItem(ONBOARD_KEY) !== "1") navigate(`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/welcome`);
    } catch {
      // storage unavailable — never redirect-loop the user
    }
  }, [navigate]);
  return null;
}
