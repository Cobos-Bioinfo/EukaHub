import { Link } from "react-router";

import RecordBrowser from "../components/RecordBrowser";
import { cladePath, hasRecords } from "../lib/clade";
import { fmt } from "../lib/format";
import { useClade } from "./CladeLayout";

/** The Records view of one group: every assembly and annotation on it or below
 *  it, with links to download each one. */
export default function RecordsPage() {
  const clade = useClade();
  const { ass, ann } = clade.resources;

  return (
    <section className="records-page">
      <header className="records-page__head">
        <h1 className="records-page__title">Records in {clade.name}</h1>
        {hasRecords(clade) ? (
          <p className="records-page__sub">
            {fmt(ass.total)} genome {ass.total === 1 ? "assembly" : "assemblies"} and{" "}
            {fmt(ann.total)} {ann.total === 1 ? "annotation" : "annotations"}, with links to
            download each one.
          </p>
        ) : (
          <p className="records-page__sub">
            No genome assemblies or annotations of {clade.name} are in the dataset yet. Its{" "}
            <Link to={cladePath(clade.taxid)}>Summary</Link> links to the sources.
          </p>
        )}
      </header>
      {hasRecords(clade) && <RecordBrowser key={clade.taxid} taxid={clade.taxid} />}
    </section>
  );
}
