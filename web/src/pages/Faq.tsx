/** A short FAQ. Plain language, honest that the numbers are a periodic snapshot. */
export default function Faq() {
  return (
    <section className="faq">
      <h1 className="faq__title">Frequently asked questions</h1>

      <div className="faq__item">
        <h2 className="faq__q">What is EukaHub?</h2>
        <p className="faq__a">
          A way to see how much public genomic data exists for any part of the eukaryotic
          tree of life. Pick a group and you get two answers: how much data there is, and how
          it splits across the groups beneath it.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">Where does the data come from?</h2>
        <p className="faq__a">
          Genome assemblies from NCBI, functional annotations from Annotrieve, and RNA-Seq
          reads (including long-read) from ENA. The taxonomy itself is the NCBI Taxonomy tree.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">What do the coverage percentages mean?</h2>
        <p className="faq__a">
          The share of species in a group that have at least one of a resource. "12%
          assemblies" means 12% of the species in that group have a genome assembly.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">How up to date is it?</h2>
        <p className="faq__a">
          The numbers are a snapshot, rebuilt from the sources on a schedule rather than
          fetched live. For the current, definitive record, follow the links out to NCBI,
          Annotrieve, or ENA.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">How do I find a specific organism?</h2>
        <p className="faq__a">
          Use the search box at the top. Type a name (like "Primates" or "Fungi") or an NCBI
          TaxID (like 9606 for humans).
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">Can I download the data?</h2>
        <p className="faq__a">
          Yes. The breakdown on each dashboard has two downloads: the rows you're looking at,
          and the full breakdown as a TSV file.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">Is there an API?</h2>
        <p className="faq__a">
          Yes — the whole app runs on a public, read-only API.{" "}
          <a href="/api/docs" target="_blank" rel="noreferrer">
            Browse the API docs
          </a>
          .
        </p>
      </div>
    </section>
  );
}
