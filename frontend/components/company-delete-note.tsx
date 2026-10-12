/** What deleting a company does, in plain words, for every delete dialog (one company or several). */
export function CompanyDeleteNote({ count = 1 }: { count?: number }) {
  const it = count === 1 ? "it" : "them";
  return (
    <div className="space-y-2">
      <p>This removes {count === 1 ? "the company" : `these ${count} companies`} from LeadFinder for everyone:</p>
      <ul className="list-disc space-y-0.5 pl-5">
        <li>{count === 1 ? "its" : "their"} locations, numbers and search history are deleted</li>
        <li>Find Leads won&apos;t add {it} back</li>
        <li>the people found there are kept</li>
      </ul>
      <p className="text-fg">
        Just want {it} out of your list? <span className="font-medium">Archive</span> instead: nothing is lost.
      </p>
    </div>
  );
}
