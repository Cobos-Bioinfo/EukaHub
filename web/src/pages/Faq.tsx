import { useEffect } from "react";
import { useLocation } from "react-router";

/** A short FAQ. Plain language, honest that the numbers are a periodic snapshot. */
export default function Faq() {
  // Support deep links like /faq#subspecies: scroll the anchored item into view
  // on load (React Router doesn't do hash scrolling on client-side navigation).
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" });
  }, [hash]);

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
          assemblies" means 12% of the species in that group have a genome assembly. The
          totals next to them count every record in the group, whichever taxon it is attached
          to.
        </p>
      </div>

      <div className="faq__item" id="subspecies">
        <h2 className="faq__q">Is data on a subspecies counted toward its species?</h2>
        <p className="faq__a">
          Yes. Records that NCBI, Annotrieve or ENA attach to a subspecies, variety or strain
          count toward its species and every group above it, just like the species' own
          records. A subspecies is not counted as an extra species: a species whose genomes
          are all filed under its subspecies counts once, as a species with genomes. A
          species' page shows which records are attached to the species itself and which to
          its subspecies and strains.
        </p>
      </div>

      <div className="faq__item" id="informal-species">
        <h2 className="faq__q">Why are there fewer species than in the NCBI Taxonomy?</h2>
        <p className="faq__a">
          NCBI gives the species rank to many taxa that are not named species: specimens
          identified only to genus ("Homo sp."), environmental and uncultured samples,
          uncertain identifications ("cf.", "aff."), crosses between two species and cultivar
          groups. They are more than half of NCBI's eukaryote species, so counting them would
          make every group look emptier than it is. EukaHub counts only species with a formal
          Latin name. Informal taxa without data are left out. Those with data are kept and
          labelled "informal species": their records count in every total above them, but
          they are not counted as species or in the coverage percentages.
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
          Use the search box at the top. Type a scientific name (like "Primates" or "Fungi"), part
          of one, or an NCBI TaxID (like 9606 for humans). Common names such as "human" are not
          searchable yet. If no name matches, the search suggests the closest spellings.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">Can I download the data?</h2>
        <p className="faq__a">
          Yes. On a group's Data map, the List view's "Download this table (TSV)" saves one row
          per group at the rank shown, with its species count and coverage for each resource.
          Each assembly and annotation on a group's Records links to its files at the source.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">How do I report a problem or suggest something?</h2>
        <p className="faq__a">
          Use the "Send feedback" link in the header menu (the ⋯ button). It opens a short
          form, no GitHub account needed, and your response is filed as an issue on the
          project. If you do have a GitHub account, you can open an issue directly instead.
        </p>
      </div>

      <div className="faq__item">
        <h2 className="faq__q">Is there an API?</h2>
        <p className="faq__a">
          Yes, the whole app runs on a public, read-only API.{" "}
          <a href="/api/docs" target="_blank" rel="noreferrer">
            Browse the API docs
          </a>
          .
        </p>
      </div>
    </section>
  );
}
