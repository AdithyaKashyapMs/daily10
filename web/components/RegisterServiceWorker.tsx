"use client";

import { useEffect } from "react";

/** Registers the service worker so the app can be installed and opens offline (shell only). */
export function RegisterServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }, []);
  return null;
}
