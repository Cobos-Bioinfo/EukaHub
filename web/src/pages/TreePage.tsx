import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { getTaxon, getMetricsConfig } from "../api/queries";
import type { TaxonRef } from "../api/types";
import { TaxonError } from "../components/ErrorPage";
import RadialTree from "../components/RadialTree";
import RootPicker from "../components/RootPicker";
import TreeOutline from "../components/TreeOutline";
import { useAsync } from "../hooks/useAsync";
import { useTree } from "../hooks/useTree";
import { cladePath } from "../lib/clade";
import { useClade } from "./CladeLayout";

/** The Tree of Life view of one group: an interactive radial tree rooted at it. */
export default function TreePage() {
  const node = useClade();
  const taxid = node.taxid;
  const navigate = useNavigate();

  const metrics = useAsync(() => getMetricsConfig(), []);
  const tree = useTree(taxid);

  // Search-to-locate: pan/highlight a taxon within the current tree, expanding
  // the path to it first. `focus` is the located node handed to RadialTree.
  const [focus, setFocus] = useState<{ taxid: number; nonce: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locateMsg, setLocateMsg] = useState<{ text: string; taxid: number } | null>(null);
  // A fresh root is a fresh tree: drop any stale locate state.
  useEffect(() => {
    setFocus(null);
    setLocateMsg(null);
  }, [taxid]);

  const locate = async (picked: TaxonRef) => {
    setLocateMsg(null);
    if (picked.taxid === taxid) {
      setFocus({ taxid, nonce: Date.now() }); // already the root: recentre it
      return;
    }
    setLocating(true);
    try {
      const target = await getTaxon(picked.taxid);
      const idx = target.lineage.findIndex((a) => a.taxid === taxid);
      if (idx === -1) {
        setLocateMsg({
          text: `${picked.name} is not inside ${node.name}.`,
          taxid: picked.taxid,
        });
        return;
      }
      const path = target.lineage.slice(idx + 1).map((a) => a.taxid);
      const res = await tree.reveal(path);
      if (res.status === "ok") setFocus({ taxid: picked.taxid, nonce: Date.now() });
      else if (res.status === "buried")
        setLocateMsg({
          text: `${picked.name} sits deep under a very large group and is hard to reach here.`,
          taxid: picked.taxid,
        });
      // "superseded" → a newer search took over; leave its result to win.
    } catch {
      setLocateMsg({ text: `Could not locate ${picked.name}.`, taxid: picked.taxid });
    } finally {
      setLocating(false);
    }
  };

  if (tree.error) return <TaxonError taxid={String(taxid)} message={tree.error} />;

  return (
    <section className="tree-page">
      <header className="tree-page__head">
        <div className="tree-page__topline">
          <h1 className="tree-page__title">
            Tree of Life from <em>{node.name}</em>
          </h1>
          <div className="tree-search">
            <RootPicker onPick={locate} placeholder="Find a group in this tree" />
            {locating && <span className="tree-search__status">Locating…</span>}
            {locateMsg && (
              <span className="tree-search__status tree-search__status--warn">
                {locateMsg.text}{" "}
                <button
                  type="button"
                  className="tree-search__jump"
                  onClick={() => navigate(cladePath(locateMsg.taxid, "tree"))}
                >
                  Open its own tree
                </button>
              </span>
            )}
          </div>
        </div>
        <p className="tree-page__sub">
          Browse the tree of life starting from this group. Bigger circles hold more species, and
          you can colour the tree by a data type to see where data is rich or sparse. Click a circle
          to see its details or open its summary. Scroll to zoom and drag to move around.
        </p>
      </header>

      {metrics.data ? (
        <RadialTree
          tree={tree}
          metrics={metrics.data}
          focus={focus}
          onOpen={(t) => navigate(cladePath(t))}
        />
      ) : metrics.error ? (
        <p className="notice notice--error" role="alert">
          Could not load the tree: {metrics.error}{" "}
          <button type="button" className="link-btn" onClick={metrics.reload}>
            Try again
          </button>
        </p>
      ) : (
        <p className="notice">Loading…</p>
      )}

      <details className="tree-details">
        <summary>Text outline (accessible view)</summary>
        <TreeOutline tree={tree} />
      </details>
    </section>
  );
}
