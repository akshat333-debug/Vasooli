"use client";

import { useMemo, useState } from "react";
import type { LedgerEntry } from "@/lib/data";

const EVENT_TONE: Record<string, string> = {
  batch_start: "#6f6a60",
  batch_end: "#6f6a60",
  decision: "#8f8fe8",
  attempt: "#1c1b19",
  preflight_refusal: "#d9ac43",
  fuse_trip: "#b5533f",
  razorpay_probe: "#6f6a60",
  razorpay_order_created: "#8fae86",
  razorpay_subscription_created: "#8fae86",
  razorpay_error: "#b5533f",
  razorpay_degraded: "#d9ac43",
};

const PAGE = 60;

export default function LedgerStream({
  entries,
  verified,
  detail,
}: {
  entries: LedgerEntry[];
  verified: boolean;
  detail: string;
}) {
  const [arm, setArm] = useState<string>("all");
  const [event, setEvent] = useState<string>("all");
  const [limit, setLimit] = useState(PAGE);

  const events = useMemo(
    () => [...new Set(entries.map((e) => e.event))].sort(),
    [entries],
  );

  const filtered = useMemo(
    () =>
      entries.filter(
        (e) =>
          (arm === "all" || e.arm === arm) && (event === "all" || e.event === event),
      ),
    [entries, arm, event],
  );

  const visible = filtered.slice(0, limit);

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <Select
          label="Arm"
          value={arm}
          onChange={(v) => {
            setArm(v);
            setLimit(PAGE);
          }}
          options={["all", "baseline", "sequencer", "live"]}
        />
        <Select
          label="Event"
          value={event}
          onChange={(v) => {
            setEvent(v);
            setLimit(PAGE);
          }}
          options={["all", ...events]}
        />
        <span className="ml-auto text-[12.5px] text-ink-faint">
          {filtered.length} rows
        </span>
      </div>

      <div className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
        <div
          className={`flex items-center gap-2.5 border-b px-5 py-3 ${
            verified ? "border-sage/30 bg-sage-soft/30" : "border-clay/30 bg-clay-soft/30"
          }`}
        >
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: verified ? "#8fae86" : "#b5533f" }}
          />
          <p className="verdict !text-ink">
            {verified ? "Chain verified" : "Chain broken"} — {detail}
          </p>
        </div>

        {visible.length === 0 ? (
          <p className="px-5 py-12 text-center text-[14px] text-ink-mute">
            Nothing matches that combination. Widen the arm or event filter.
          </p>
        ) : (
          <ul className="divide-y divide-rule/50">
            {visible.map((e) => (
              <li key={e.idx} className="flex gap-3 px-5 py-2.5 hover:bg-paper-sunk/35">
                <span className="tnum w-10 shrink-0 pt-px font-mono text-[11.5px] text-ink-faint">
                  {e.idx}
                </span>
                <span
                  className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ background: EVENT_TONE[e.event] ?? "#9a9488" }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                    <span className="font-mono text-[11px] tracking-wide text-ink-faint uppercase">
                      {e.event}
                    </span>
                    {e.subscription_id && (
                      <span className="font-mono text-[11.5px] text-ink-mute">
                        {e.subscription_id}
                      </span>
                    )}
                    <span className="font-mono text-[11px] text-ink-faint">{e.arm}</span>
                  </div>
                  <p className="verdict mt-0.5 break-words">{e.verdict}</p>
                </div>
                <span
                  className="hidden shrink-0 self-center font-mono text-[10.5px] text-ink-faint lg:block"
                  title={`hash ${e.hash}`}
                >
                  {e.hash.slice(0, 8)}
                </span>
              </li>
            ))}
          </ul>
        )}

        {limit < filtered.length && (
          <button
            onClick={() => setLimit((l) => l + PAGE * 2)}
            className="w-full border-t border-rule py-3 text-[13px] text-ink-mute transition-colors hover:bg-paper-sunk/50 hover:text-ink"
          >
            Show more — {filtered.length - limit} remaining
          </button>
        )}
      </div>
    </>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="flex items-center gap-2 rounded-lg border border-rule bg-paper-raised px-3 py-1.5">
      <span className="text-[11px] tracking-wider text-ink-faint uppercase">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-[13px] text-ink focus:outline-none"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
