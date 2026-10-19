import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { getTaxon } from "../api/queries";
import type { TaxonRef } from "../api/types";
import CladeTree from "../components/CladeTree";
import { TaxonError } from "../components/ErrorPage";
import RangeLegend from "../components/RangeLegend";
import RootPicker from "../components/RootPicker";
import { MAX_VISIBLE_NODES, useTree } from "../hooks/useTree";
import { MEASURES, measureOf } from "../lib/measures";
import { MAJOR_RANKS } from "../lib/ranks";
import { useClade } from "./CladeLayout";

/** The Tree of Life view of one group: its tree drawn left to right, opened a
 *  branch at a time. The measure and the ranks live in the address
 *  (`?colour=`, `?ranks=all`), as on the Data map. */
export default function TreePage() {
  const clade = useClade();
  const taxid = clade.taxid;
  const [params, setParams] = useSearchParams();
  const measure = measureOf(params.get("colour"));
  // Below a species every taxon is of a minor rank, so its tree shows them all.
  const unit =
    clade.is_infraspecific || clade.rank === "species" || clade.rank === "informal species";
  const allRanks = unit || params.get("ranks") === "all";
  const tree = useTree(taxid, !allRanks);
  const [panelOpen, setPanelOpen] = useState(true);

  const choose = (key: string, value: string, initial: string) =>
    setParams(
      (p) => {
        const q = new URLSearchParams(p);
        if (value === initial) q.delete(key);
        else q.set(key, value);
        return q;
      },
      { replace: true },
    );

  // A group picked in the search box is opened down to, then marked. One outside
  // the major ranks first switches the tree to all ranks.
  const [found, setFound] = useState<{ taxid: number; nonce: number } | null>(null);
  const [pending, setPending] = useState<{ picked: TaxonRef; note: string } | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    setFound(null);
    setPending(null);
    setStatus(null);
  }, [taxid]);

  const locate = async (picked: TaxonRef, note: string | null = null) => {
    setStatus(null);
    setFound(null);
    if (picked.taxid === taxid) {
      setFound({ taxid, nonce: Date.now() });
      return;
    }
    setStatus("Finding it…");
    try {
      const target = await getTaxon(picked.taxid);
      const idx = target.lineage.findIndex((a) => a.taxid === taxid);
      if (idx === -1) {
        setStatus(`${picked.name} is not inside ${clade.name}.`);
        return;
      }
      if (!allRanks && !MAJOR_RANKS.has(target.rank)) {
        const switched = `${picked.name} is not of a main rank, so the tree now shows every rank.`;
        setPending({ picked, note: switched });
        choose("ranks", "all", "major");
        setStatus(switched);
        return;
      }
      const path = target.lineage
        .slice(idx + 1)
        .filter((a) => allRanks || MAJOR_RANKS.has(a.rank))
        .map((a) => a.taxid);
      const res = await tree.reveal(path);
      if (res.status === "ok") {
        setFound({ taxid: picked.taxid, nonce: Date.now() });
        setStatus(note);
      } else if (res.status === "buried") {
        setStatus(`${picked.name} is among too many groups to open here. Search for it at the top instead.`);
      }
    } catch {
      setStatus(`Could not find ${picked.name}.`);
    }
  };

  // After the switch to all ranks, find the group once the new tree has loaded.
  const ready = allRanks && !tree.majorRanks && tree.rootId === taxid && taxid in tree.nodes;
  useEffect(() => {
    if (pending && ready) {
      setPending(null);
      void locate(pending.picked, pending.note);
    }
  }, [pending, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  if (tree.error) return <TaxonError taxid={String(taxid)} message={tree.error} />;

  return (
    <section className={"ctree" + (panelOpen ? "" : " ctree--bare")}>
      <div className="ctree__panel">
        <div className="ctree__panel-head">
          <h1 className="ctree__title">
            Tree of Life from <em>{clade.name}</em>
          </h1>
          <button
            type="button"
            className="link-btn ctree__hide"
            aria-expanded={panelOpen}
            aria-controls="ctree-options"
            onClick={() => setPanelOpen((v) => !v)}
          >
            {panelOpen ? "Hide options" : "Options"}
          </button>
        </div>
        {panelOpen && (
          <div className="ctree__options" id="ctree-options">
            <p className="ctree__hint">
              Click a group to open its branch; its name opens its Summary. Drag or scroll to
              move around, and hold Ctrl while scrolling, or pinch, to zoom.
            </p>
            {!unit && (
              <div className="ctree__control">
                <label className="control">
                  <span className="control__label">Ranks</span>
                  <select
                    className="control__select"
                    value={allRanks ? "all" : "major"}
                    aria-describedby="ctree-ranks-note"
                    onChange={(e) => choose("ranks", e.target.value, "major")}
                  >
                    <option value="major">Main ranks only</option>
                    <option value="all">Every rank</option>
                  </select>
                </label>
                <p className="ctree__ranks-note" id="ctree-ranks-note">
                  {allRanks
                    ? "Every taxon in the NCBI taxonomy, including the unranked clades."
                    : "Kingdom, phylum, class, order, family, genus and species."}
                </p>
              </div>
            )}
            <label className="control">
              <span className="control__label">Colour by</span>
              <select
                className="control__select"
                value={measure.key}
                onChange={(e) => choose("colour", e.target.value, MEASURES[0].key)}
              >
                {MEASURES.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <RangeLegend title={measure.legend} />
            <RootPicker onPick={locate} placeholder="Find a group in this tree" />
          </div>
        )}
        <p className="ctree__status" role="status">
          {status ??
            (tree.atCapacity
              ? `The tree shows at most ${MAX_VISIBLE_NODES} groups at once. Close a branch to open another.`
              : "")}
        </p>
      </div>

      <CladeTree tree={tree} measure={measure} found={found} />
    </section>
  );
}
