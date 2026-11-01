import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import {
  dismissChecklist,
  fetchChecklist,
  formatCountdown,
  type Checklist,
  type ChecklistItem,
} from "./checklistApi";
import { CoachMarkTour, tourAlreadySeen } from "./CoachMarkTour";

const LABELS: Record<string, string> = {
  tailscale: "Tailscale network",
  totp: "TOTP enrolled",
  sub_account: "Sub-account bound",
  api_key: "API key status",
  profile_limits: "Profile limits",
  demo_session: "Demo session",
};
const STATE_TEXT: Record<string, string> = {
  ok: "Done",
  pending: "Pending",
  blocked: "Blocked",
  error: "Error",
  not_applicable: "Not yet available",
};
const ICON: Record<string, string> = {
  ok: "✓",
  pending: "○",
  blocked: "⏸",
  error: "!",
  not_applicable: "–",
};

function Countdown({ unblockAt }: { readonly unblockAt: string }): JSX.Element {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    // Once a minute: polite for screen-reader users.
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  return (
    <span aria-live="polite">
      Available {new Date(unblockAt).toUTCString()} ({formatCountdown(unblockAt, now)} left)
    </span>
  );
}

function Step({
  item,
  onRetry,
}: {
  readonly item: ChecklistItem;
  readonly onRetry: () => void;
}): JSX.Element {
  const label = LABELS[item.key] ?? item.key;
  return (
    <li>
      <span aria-hidden="true">{ICON[item.state]}</span> <strong>{label}</strong>:{" "}
      <span>{STATE_TEXT[item.state]}</span>
      {/* `reason` is free text: never rendered raw, the state word stands (E09-D12 §5.8, §8.3) */}
      {item.state === "blocked" && item.unblock_at ? (
        <>
          {" "}
          <Countdown unblockAt={item.unblock_at} /> Demo exploration is available meanwhile.
        </>
      ) : null}{" "}
      {item.state === "error" ? (
        <button type="button" onClick={onRetry}>
          Retry {label}
        </button>
      ) : item.state !== "ok" && item.action_route ? (
        <a href={item.action_route}>Go to {label}</a>
      ) : null}
    </li>
  );
}

/** SCR-019. Never blocks the workspace: failures render nothing or per-step errors. */
export function SetupChecklistCard(): JSX.Element | null {
  const [data, setData] = useState<Checklist | null>(null);
  const [tour, setTour] = useState(false);
  const tourButton = useRef<HTMLButtonElement>(null);
  const load = useCallback(async () => {
    const d = await fetchChecklist();
    setData(d);
    // Auto-offer once; afterwards only via the explicit button (resume from Help).
    if (d && !d.dismissed && !d.complete && !tourAlreadySeen()) setTour(true);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (!data || data.dismissed) return null;
  if (data.complete) {
    return (
      <section aria-label="Setup checklist">
        <p>Setup complete.</p>
        <button
          type="button"
          onClick={() => {
            void dismissChecklist().then((ok) => {
              if (ok) setData({ ...data, dismissed: true });
            });
          }}
        >
          Dismiss
        </button>
      </section>
    );
  }
  return (
    <section aria-label="Setup checklist">
      <h2>Finish setting up</h2>
      <button ref={tourButton} type="button" onClick={() => setTour(true)}>
        Take the tour
      </button>
      {tour ? <CoachMarkTour onClose={() => setTour(false)} returnFocusTo={tourButton} /> : null}
      <ol>
        {data.items.map((i) => (
          <Step key={i.key} item={i} onRetry={() => void load()} />
        ))}
      </ol>
    </section>
  );
}
