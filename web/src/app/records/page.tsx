import RecordExplorer from "@/components/RecordExplorer";
import { batch } from "@/lib/data";

export const metadata = { title: "Records — Vasooli" };

export default function RecordsPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-5 py-8 sm:px-8 sm:py-12">
      <header className="mb-8">
        <p className="eyebrow mb-3">All decisions</p>
        <h1 className="display max-w-2xl text-[28px] leading-tight font-semibold sm:text-[36px]">
          Every record, and the rule that decided it.
        </h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
          Eight stopping rules run in order, cheapest and most certain refusals
          first. Open any record to see which rule fired and why — the same
          verdict string that was written to the audit trail.
        </p>
      </header>
      <RecordExplorer records={batch.records} />
    </div>
  );
}
