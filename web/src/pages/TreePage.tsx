import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getLineage, getMetricsConfig } from "../api/queries";
import type { TaxonRef } from "../api/types";
import Breadcrumb from "../components/Breadcrumb";
import RadialTree from "../components/RadialTree";
import RootPicker from "../components/RootPicker";
import TreeOutline from "../components/TreeOutline";
import ViewSwitcher from "../components/ViewSwitcher";
import { useAsync } from "../hooks/useAsync";
import { useTree } from "../hooks/useTree";

/** The interactive radial Tree of Life for one root clade (`/tree/:taxid`). */
export default function TreePage() {
  const { taxid: taxidParam } = useParams();
  const taxid = Number(taxidParam);
  const validId = Number.isInteger(taxid) && taxid > 0;
  const navigate = useNavigate();

  const metrics = useAsync(() => getMetricsConfig(), []);
  const lineage = useAsync(() => getLineage(taxid), [taxid]);
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

  const lin = lineage.data?.lineage;
  const node = lin && lin.length > 0 ? lin[lin.length - 1] : undefined;

  const locate = async (picked: TaxonRef) => {
    setLocateMsg(null);
    if (picked.taxid === taxid) {
      setFocus({ taxid, nonce: Date.now() }); // already the root: recentre it
      return;
    }
    setLocating(true);
    try {
      const target = await getLineage(picked.taxid);
      const idx = target.lineage.findIndex((a) => a.taxid === taxid);
      if (idx === -1) {
        setLocateMsg({
          text: `${picked.name} is not inside ${node?.name ?? "this group"}.`,
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

  if (!validId) return <p className="notice notice--error">Invalid taxon id.</p>;
  if (lineage.error) return <p className="notice notice--error">{lineage.error}</p>;
  if (tree.error) return <p className="notice notice--error">{tree.error}</p>;

  return (
    <section className="tree-page">
      {lineage.data && <Breadcrumb lineage={lineage.data.lineage} currentTaxid={taxid} />}
      {node && <ViewSwitcher taxid={taxid} name={node.name} current="tree" layout="row" />}

      <header className="tree-page__head">
        <div className="tree-page__topline">
          <h1 className="tree-page__title">
            Tree of Life{node ? <> — <em>{node.name}</em></> : null}
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
                  onClick={() => navigate(`/tree/${locateMsg.taxid}`)}
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
          to see its details or open its dashboard. Scroll to zoom and drag to move around.
        </p>
      </header>

      {metrics.data ? (
        <RadialTree
          tree={tree}
          metrics={metrics.data}
          focus={focus}
          onOpen={(t) => navigate(`/clade/${t}`)}
        />
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
