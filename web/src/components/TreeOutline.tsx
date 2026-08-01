import type { Tree } from "../hooks/useTree";
import { fmt, fmtPct } from "../lib/format";

/** Keyboard-accessible text mirror of the radial tree: the same loaded/expanded
 *  hierarchy as a nested list. Clicking a taxon with children expands it here
 *  (and in the radial view) rather than navigating away — the same lazy-expand
 *  the SVG uses, reachable without a pointer. */
export default function TreeOutline({ tree }: { tree: Tree }) {
  if (tree.rootId == null || !tree.nodes[tree.rootId]) return null;
  return (
    <ul className="tree-outline" role="tree" aria-label="Taxonomy outline">
      <OutlineNode id={tree.rootId} tree={tree} />
    </ul>
  );
}

function OutlineNode({ id, tree }: { id: number; tree: Tree }) {
  const tn = tree.nodes[id];
  if (!tn) return null;
  const { node, expanded, childIds, totalChildren, loading } = tn;
  const remaining = totalChildren - childIds.length;

  return (
    <li className="tree-outline__li" role="treeitem" aria-expanded={node.has_children ? expanded : undefined}>
      <div className="tree-outline__row">
        {node.has_children ? (
          <button
            type="button"
            className="tree-outline__toggle"
            aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
            onClick={() => tree.toggle(id)}
          >
            {loading ? "…" : expanded ? "▾" : "▸"}
          </button>
        ) : (
          <span className="tree-outline__leaf" aria-hidden="true">
            ·
          </span>
        )}
        {node.has_children ? (
          <button
            type="button"
            className="tree-outline__name tree-outline__name--btn"
            onClick={() => tree.toggle(id)}
          >
            {node.name}
          </button>
        ) : (
          <span className="tree-outline__name">{node.name}</span>
        )}
        <span className="tree-outline__rank">{node.rank}</span>
        <span className="tree-outline__meta">
          {fmt(node.n_rows)} sp · {fmtPct(node.resources.ass.percent)}% assemblies
        </span>
      </div>

      {expanded && childIds.length > 0 && (
        <ul role="group">
          {childIds.map((cid) => (
            <OutlineNode key={cid} id={cid} tree={tree} />
          ))}
          {remaining > 0 && (
            <li>
              <button
                type="button"
                className="tree-outline__more"
                onClick={() => tree.loadMore(id)}
              >
                Load {remaining} more…
              </button>
            </li>
          )}
        </ul>
      )}
    </li>
  );
}
