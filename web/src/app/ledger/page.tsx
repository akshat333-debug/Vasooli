import { Suspense } from "react";
import LedgerStream from "@/components/LedgerStream";
import { batch } from "@/lib/data";

export const metadata = { title: "Audit trail · Vasooli" };

export default function LedgerPage() {
  const { ledger } = batch;
  return (
    <div className="mx-auto max-w-[1180px] px-5 py-8 sm:px-8 sm:py-12">
      <header className="mb-8">
        <p className="eyebrow mb-3">Audit trail</p>
        <h1 className="display max-w-2xl text-[28px] leading-tight font-semibold sm:text-[36px]">
          {ledger.rows} rows, each one hashed into the next.
        </h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
          Every decision is written here before it is acted on. The chain rule is{" "}
          <span className="font-mono text-[13.5px]">
            sha256(prev_hash ‖ payload)
          </span>
          , so editing any historical row breaks every hash after it and
          verification reports the first broken index rather than a bare pass or
          fail. A log that can be quietly revised afterwards is not an audit
          trail.
        </p>
      </header>
      <Suspense
        fallback={
          <p className="py-12 text-center text-[14px] text-ink-mute">
            Loading…
          </p>
        }
      >
        <LedgerStream
        entries={ledger.entries}
        verified={ledger.verified}
        detail={ledger.detail}
      />
      </Suspense>
    </div>
  );
}
