import type { ReactNode } from "react";
import { Link } from "react-router";

import RootPicker from "./RootPicker";

/** The page for an address the app has no route for. */
export function NotFound() {
  return (
    <ErrorLayout title="Page not found">
      <p>There is no page at this address. Search for an organism or group instead.</p>
    </ErrorLayout>
  );
}

/** What a taxon page shows when its taxon can't be loaded: a missing or invalid
 *  TaxID gets an explanation and a search box, anything else a Retry button. */
export function TaxonError({
  taxid,
  status,
  message,
  retry,
}: {
  taxid: string | undefined;
  status?: number;
  message?: string;
  retry?: () => void;
}) {
  if (status === 404 || status === 422 || message === undefined) {
    return (
      <ErrorLayout title={`No taxon with TaxID ${taxid ?? ""}`.trim()}>
        <p>
          NCBI may have merged this TaxID into another one or removed it, or it is not a eukaryote.
          Search for the organism by name instead.
        </p>
      </ErrorLayout>
    );
  }
  return (
    <section className="errpage">
      <h1 className="errpage__title">This page could not load</h1>
      <p className="errpage__text">{message}</p>
      {retry && (
        <button type="button" className="errpage__retry" onClick={retry}>
          Try again
        </button>
      )}
    </section>
  );
}

function ErrorLayout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="errpage">
      <h1 className="errpage__title">{title}</h1>
      <div className="errpage__text">{children}</div>
      <div className="errpage__search">
        <RootPicker placeholder="Search by name or TaxID, e.g. Primates or 9606" />
      </div>
      <Link to="/" className="errpage__home">
        Go to the start page
      </Link>
    </section>
  );
}
