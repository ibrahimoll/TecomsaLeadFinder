"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

/** Local search text that is committed (e.g. to the URL) 250 ms after typing stops. */
export function useDebouncedSearch(committed: string, commit: (value: string) => void) {
  const [text, setText] = useState(committed);
  useEffect(() => setText(committed), [committed]);
  useEffect(() => {
    if (text === committed) return;
    const t = setTimeout(() => commit(text), 250);
    return () => clearTimeout(t);
  }, [text, committed, commit]);
  return [text, setText] as const;
}

/** Filters stored in the URL query string, so views are shareable and survive reloads. */
export function useUrlState<K extends string>(keys: readonly K[]) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const values = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ""])) as Record<K, string>;

  const set = useCallback(
    (changes: Partial<Record<K, string>>) => {
      const next = new URLSearchParams(params.toString());
      Object.entries(changes).forEach(([key, value]) => {
        if (value) next.set(key, value as string);
        else next.delete(key);
      });
      if (!("page" in changes)) next.delete("page");
      const qs = next.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [params, pathname, router],
  );

  return [values, set] as const;
}
