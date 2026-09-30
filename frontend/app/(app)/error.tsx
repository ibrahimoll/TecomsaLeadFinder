"use client";

import { Section, ErrorState } from "@/components/ui";

/** Catches unexpected rendering errors inside the authenticated app. */
export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <Section>
      <ErrorState
        message={`Something unexpected happened while showing this page${error.digest ? ` (reference ${error.digest})` : ""}.`}
        onRetry={reset}
      />
    </Section>
  );
}
