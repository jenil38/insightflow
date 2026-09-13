/**
 * Tells the user why the first request is slow, instead of leaving a spinner
 * that looks frozen for a minute.
 *
 * Hidden for the first few seconds: a warm server answers well inside that
 * window, and a notice that flashes up and vanishes on every page load would
 * be noise.
 */
import { useEffect, useState, useSyncExternalStore } from "react";

import { getServerWakeState, subscribeServerWake } from "../../api/serverWake.js";
import { Alert } from "../ui/index.jsx";

const SHOW_AFTER_MS = 2500;

export function useServerWake() {
  return useSyncExternalStore(subscribeServerWake, getServerWakeState, getServerWakeState);
}

export default function ServerWakeNotice({ className }) {
  const { status, startedAt } = useServerWake();
  const [now, setNow] = useState(() => Date.now());

  // Tick only while waiting, so an idle page isn't re-rendering every second.
  useEffect(() => {
    if (status !== "waking") return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [status]);

  if (status === "unreachable") {
    return (
      <div role="status" aria-live="polite" className={className}>
        <Alert tone="warning" title="The analysis server isn't responding">
          It may be restarting. Wait a minute, then try again.
        </Alert>
      </div>
    );
  }

  if (status !== "waking" || !startedAt) return null;

  const elapsed = now - startedAt;
  if (elapsed < SHOW_AFTER_MS) return null;

  return (
    <div role="status" aria-live="polite" className={className}>
      <Alert tone="info" title="Starting the analysis server">
        It pauses when nobody is using it, so the first request can take up to a minute. You can
        keep going - anything you submit will complete once it is up.
        {/* The counter is hidden from assistive technology: inside a live
            region it would be re-announced every second. */}
        <span aria-hidden="true" className="ml-1 font-mono tabular-nums text-subtle">
          ({Math.round(elapsed / 1000)}s)
        </span>
      </Alert>
    </div>
  );
}
