"use client";

import { useCallback, useEffect, useState } from "react";
import { verifyChain, type ChainEntry, type VerifyOutcome } from "@/lib/verifyChain";

/**
 * Recompute the chain here, in the reader's browser, and let them break it.
 *
 * The page used to state that the chain verified, which is a claim about a
 * check somebody else ran. This runs the check in front of them against the
 * committed export, and the tamper control edits one verdict in memory so the
 * break can be watched appearing at that row -- and every row after it
 * inheriting a prev_hash that no longer matches.
 *
 * Nothing here writes anything. The tamper is a local edit to a copy of the
 * data for the duration of one recomputation.
 */
export default function ChainVerifier({ entries }: { entries: ChainEntry[] }) {
  const [result, setResult] = useState<VerifyOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [tamperIdx, setTamperIdx] = useState<number | null>(null);

  // A row in the middle, so the reader can see the break has rows after it.
  const demoIdx = entries.length > 8 ? entries[Math.floor(entries.length / 2)].idx : 1;

  const run = useCallback(
    async (tamper: number | null) => {
      setBusy(true);
      setTamperIdx(tamper);
      try {
        setResult(await verifyChain(entries, { tamperIdx: tamper }));
      } catch (e) {
        setResult({
          ok: false,
          checked: 0,
          brokenAt: null,
          reason: `could not run in this browser: ${(e as Error).message}`,
        });
      } finally {
        setBusy(false);
      }
    },
    [entries],
  );

  useEffect(() => {
    void run(null);
  }, [run]);

  const broken = result && !result.ok;

  return (
    <section
      className={`mb-6 overflow-hidden rounded-2xl border ${
        broken ? "border-clay/40 bg-clay-soft/25" : "border-rule bg-paper-raised"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4 px-6 py-5 sm:px-8">
        <div className="min-w-0">
          <p className="eyebrow mb-2">Verify it yourself</p>
          <p className="text-[14px] leading-relaxed text-ink-soft">
            {busy ? (
              "Recomputing every row…"
            ) : result?.ok ? (
              <>
                <strong className="font-semibold text-ink">
                  {result.checked} rows recomputed in this browser and matched.
                </strong>{" "}
                Not a stored flag — the HMAC chain was rebuilt from the exported
                payloads just now, on this device.
              </>
            ) : result ? (
              <>
                <strong className="font-semibold text-clay-ink">
                  Chain broken at row {result.brokenAt}.
                </strong>{" "}
                {result.reason}
              </>
            ) : (
              "…"
            )}
          </p>

          {tamperIdx !== null && broken && (
            <p className="mt-2.5 text-[13px] leading-relaxed text-ink-soft">
              One verdict on row {tamperIdx} was edited in memory. The break is
              reported at the first row that fails, and every row after it
              carries a <span className="font-mono text-[12px]">prev_hash</span>{" "}
              that no longer matches — which is the whole property. Editing a
              historical row means rewriting everything that followed it, and
              without the key that cannot be done at all.
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            onClick={() => void run(null)}
            disabled={busy}
            className="rounded-lg border border-rule px-3 py-1.5 text-[12.5px] transition-colors hover:border-ink-faint disabled:opacity-50"
          >
            Verify chain
          </button>
          <button
            onClick={() => void run(tamperIdx === null ? demoIdx : null)}
            disabled={busy}
            aria-pressed={tamperIdx !== null}
            className={`rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors disabled:opacity-50 ${
              tamperIdx !== null
                ? "border-clay bg-clay text-paper"
                : "border-rule hover:border-ink-faint"
            }`}
          >
            {tamperIdx !== null ? "Undo tamper" : `Tamper with row ${demoIdx}`}
          </button>
        </div>
      </div>
    </section>
  );
}
