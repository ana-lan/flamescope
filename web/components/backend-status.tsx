"use client";

import { useEffect, useState } from "react";
import { Loader2, ServerCrash, TriangleAlert } from "lucide-react";
import { api, API_URL, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";

type State = "checking" | "waking" | "ok" | "degraded" | "down";

const SLOW_MS = 2_500; // show the banner only if /health is slower than this
const GIVE_UP_MS = 90_000;
const RETRY_MS = 4_000;

export function BackendStatus() {
  const [state, setState] = useState<State>("checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const started = Date.now();
    const slow = setTimeout(() => {
      if (!cancelled) setState((s) => (s === "checking" ? "waking" : s));
    }, SLOW_MS);

    (async () => {
      while (!cancelled) {
        try {
          const h = await api.health({ signal: controller.signal, timeoutMs: GIVE_UP_MS });
          if (!cancelled) setState(h.status === "ok" ? "ok" : "degraded");
          return;
        } catch (e) {
          if (cancelled || (e instanceof ApiError && e.kind === "aborted")) return;
          if (Date.now() - started > GIVE_UP_MS) {
            setState("down");
            return;
          }
          setState("waking");
          await new Promise((r) => setTimeout(r, RETRY_MS));
        }
      }
    })();

    return () => {
      cancelled = true;
      clearTimeout(slow);
      controller.abort();
    };
  }, [attempt]);

  if (state === "checking" || state === "ok") return null;

  if (state === "waking") {
    return (
      <Bar className="border-warning/30 bg-warning/10 text-warning">
        <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
        <span>
          Waking the backend. The free server sleeps when idle, so the first load can take up to a minute.
        </span>
      </Bar>
    );
  }

  if (state === "degraded") {
    return (
      <Bar className="border-warning/30 bg-warning/10 text-warning">
        <TriangleAlert className="size-4 shrink-0" aria-hidden />
        <span>The backend is running with reduced features. Some answers may be slower.</span>
      </Bar>
    );
  }

  return (
    <Bar className="border-destructive/30 bg-destructive/10 text-destructive">
      <ServerCrash className="size-4 shrink-0" aria-hidden />
      <span className="flex-1">
        Can&apos;t reach the IgnitIQ backend at <span className="num">{API_URL}</span>.
      </span>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          setState("checking");
          setAttempt((a) => a + 1);
        }}
      >
        Retry
      </Button>
    </Bar>
  );
}

function Bar({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <div role="status" className={`border-b ${className}`}>
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2 text-sm">{children}</div>
    </div>
  );
}