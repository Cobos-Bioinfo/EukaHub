import { Link, useSearchParams } from "react-router";

import { AnnotationRecords, AssemblyRecords } from "../components/RecordBrowser";
import { cladePath, hasRecords } from "../lib/clade";
import { fmt } from "../lib/format";
import { useClade } from "./CladeLayout";

type Show = "assemblies" | "annotations";

/** The Records view of one group: its genome assemblies or annotations, filtered
 *  and sorted, each with a link to download it, and the list itself as a TSV. */
export default function RecordsPage() {
  const clade = useClade();
  const [params, setParams] = useSearchParams();
  const { assemblies, annotations } = clade.resources;
  const show: Show =
    (params.get("show") === "annotations" && annotations.total > 0) || assemblies.total === 0
      ? "annotations"
      : "assemblies";
  const choose = (value: Show) =>
    // Filters and sorts belong to one kind of record, so they don't carry over.
    setParams(value === "assemblies" ? {} : { show: value }, { replace: true });

  const source = show === "assemblies" ? assemblies : annotations;
  const noun = source.total !== 1 ? show : show === "assemblies" ? "assembly" : "annotation";
  const from = show === "assemblies" ? "NCBI" : "Annotrieve";
  const sub = `${fmt(source.total)} ${noun}, from ${from}.`;

  return (
    <section className="records-page">
      <header className="records-page__head">
        <div className="records-page__titles">
          <h1 className="records-page__title">
            {show === "assemblies" ? "Genome assemblies" : "Annotations"} in {clade.name}
          </h1>
          {hasRecords(clade) && <p className="records-page__sub">{sub}</p>}
        </div>
        {assemblies.total > 0 && annotations.total > 0 && (
          <label className="control">
            <span className="control__label">Show</span>
            <select
              className="control__select"
              value={show}
              onChange={(e) => choose(e.target.value as Show)}
            >
              <option value="assemblies">Assemblies ({fmt(assemblies.total)})</option>
              <option value="annotations">Annotations ({fmt(annotations.total)})</option>
            </select>
          </label>
        )}
      </header>
      {!hasRecords(clade) ? (
        <p className="records-page__sub">
          No genome assemblies or annotations of {clade.name} are in the dataset yet. Its{" "}
          <Link to={cladePath(clade.taxid)}>Summary</Link> links to the sources.
        </p>
      ) : show === "assemblies" ? (
        <AssemblyRecords key={clade.taxid} clade={clade} />
      ) : (
        <AnnotationRecords key={clade.taxid} clade={clade} />
      )}
    </section>
  );
}
