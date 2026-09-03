"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * A filter value that survives a reload and a shared link.
 *
 * The Web Interface Guidelines are blunt about this: if stateful UI uses
 * `useState`, it should sync to the URL. A filtered view someone cannot link to
 * is a view they cannot show anyone else, and on a page whose whole point is
 * "here is the evidence" that matters more than usual. Sending a colleague
 * "look at the seven records that went to human review" should be a URL, not a
 * list of instructions.
 *
 * `router.replace` with `scroll: false` so filtering does not create a back-
 * button trap or jump the page to the top on every keystroke.
 */
export function useUrlState(
  key: string,
  fallback: string,
): [string, (v: string) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const value = params.get(key) ?? fallback;

  const set = useCallback(
    (next: string) => {
      const p = new URLSearchParams(params.toString());
      if (!next || next === fallback) {
        p.delete(key);
      } else {
        p.set(key, next);
      }
      const qs = p.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [key, fallback, params, pathname, router],
  );

  return [value, set];
}
