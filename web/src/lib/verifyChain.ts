/**
 * Recompute the ledger's hash chain in the browser.
 *
 * The Audit trail page used to assert that the chain verified. This makes the
 * reader able to check it instead, which is a different and much cheaper thing
 * to believe -- and it lets them break it on purpose and watch the break
 * propagate, which is the only way to show that "tamper-evident" means anything.
 *
 * This must reproduce vasooli/ledger.py byte for byte:
 *
 *   hash = HMAC-SHA256(key, prev_hash || canonical_json(body))
 *   body = {ts, run_id, arm, subscription_id, event, verdict, payload}
 *   canonical_json = json.dumps(sort_keys=True, separators=(",", ":"))
 *
 * Two details of Python's json.dumps are easy to miss and both break the hash:
 * keys are sorted at EVERY level, not just the top; and ensure_ascii defaults
 * to True, so every non-ASCII character is escaped as \uXXXX. The verdicts here
 * are full of em dashes and rupee signs, so getting that wrong would produce a
 * verifier that reports a break on an untouched chain.
 */

/** The published fallback key from ledger.py, used when VASOOLI_LEDGER_KEY is
 *  unset. It is in source control on purpose: an unkeyed chain is
 *  tamper-EVIDENT, not tamper-PROOF, and the ledger page says so. A keyed
 *  export cannot be verified here, and this module reports that rather than
 *  pretending. */
export const UNKEYED = "vasooli-unkeyed-ledger";

/** Python's json.dumps(..., sort_keys=True, separators=(",",":")) with
 *  ensure_ascii=True. */
export function canonical(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(value);
  if (typeof value === "string") return pyStr(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    const keys = Object.keys(o).sort();
    return "{" + keys.map((k) => pyStr(k) + ":" + canonical(o[k])).join(",") + "}";
  }
  return "null";
}

/** A JSON string literal escaped the way Python does it with ensure_ascii. */
function pyStr(s: string): string {
  let out = '"';
  for (const ch of s) {
    const c = ch.codePointAt(0)!;
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (c < 0x20) out += "\\u" + c.toString(16).padStart(4, "0");
    else if (c < 0x7f) out += ch;
    else if (c > 0xffff) {
      // Python emits a surrogate pair for astral characters.
      const v = c - 0x10000;
      const hi = 0xd800 + (v >> 10);
      const lo = 0xdc00 + (v & 0x3ff);
      out += "\\u" + hi.toString(16).padStart(4, "0");
      out += "\\u" + lo.toString(16).padStart(4, "0");
    } else out += "\\u" + c.toString(16).padStart(4, "0");
  }
  return out + '"';
}

export interface ChainEntry {
  idx: number;
  ts: string;
  run_id: string;
  arm: string;
  subscription_id: string | null;
  event: string;
  verdict: string;
  payload?: Record<string, unknown>;
  hash: string;
  prev_hash: string;
}

const GENESIS = "0".repeat(64);

async function hmac(key: CryptoKey, message: string): Promise<string> {
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export interface VerifyOutcome {
  ok: boolean;
  checked: number;
  /** Ledger index of the first row that does not recompute. */
  brokenAt: number | null;
  reason: string;
}

/**
 * Recompute every row. `tamperIdx` rewrites one verdict in memory first, so a
 * reader can see the break appear at that row and every row after it inherit a
 * broken prev_hash -- which is the property a chain is for.
 */
export async function verifyChain(
  entries: ChainEntry[],
  opts: { tamperIdx?: number | null; keyText?: string } = {},
): Promise<VerifyOutcome> {
  if (entries.length === 0) return { ok: true, checked: 0, brokenAt: null, reason: "no rows" };
  if (entries[0].payload === undefined) {
    return {
      ok: false,
      checked: 0,
      brokenAt: null,
      reason: "this export predates payload export and cannot be recomputed here",
    };
  }

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(opts.keyText ?? UNKEYED),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  let prev = GENESIS;
  for (const e of entries) {
    const verdict =
      opts.tamperIdx === e.idx ? e.verdict + " [EDITED AFTER THE FACT]" : e.verdict;
    const body = {
      ts: e.ts,
      run_id: e.run_id,
      arm: e.arm,
      subscription_id: e.subscription_id,
      event: e.event,
      verdict,
      payload: e.payload ?? {},
    };
    if (e.prev_hash !== prev) {
      return {
        ok: false,
        checked: entries.length,
        brokenAt: e.idx,
        reason: `row ${e.idx}: prev_hash does not match the previous row's hash`,
      };
    }
    const got = await hmac(key, prev + canonical(body));
    if (got !== e.hash) {
      return {
        ok: false,
        checked: entries.length,
        brokenAt: e.idx,
        reason: `row ${e.idx}: payload was modified after it was written`,
      };
    }
    prev = e.hash;
  }
  return {
    ok: true,
    checked: entries.length,
    brokenAt: null,
    reason: `all ${entries.length} rows recomputed in this browser and matched`,
  };
}
