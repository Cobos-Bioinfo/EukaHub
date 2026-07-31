import { useCallback, useEffect, useReducer, useRef } from "react";

import { getChildren, getSummary } from "../api/queries";
import type { TaxonChildren, TaxonNode } from "../api/types";

// How many children to load per expand / "load more" (matches the API default).
const PAGE_SIZE = 10;
// Soft guardrail: stop auto-growing the loaded tree past this many nodes so the
// SVG stays responsive. The user can still collapse branches to free room.
const MAX_NODES = 600;

/** One loaded node in the tree: its taxon data plus expand/paging bookkeeping. */
export interface TreeNode {
  node: TaxonNode;
  parentId: number | null; // null for the root
  depth: number; // 0 = root
  childIds: number[]; // loaded children, in load (species-sorted) order
  totalChildren: number; // total available (from the API), for "load more"
  expanded: boolean;
  loading: boolean;
  error?: string;
}

export interface TreeState {
  rootId: number | null;
  nodes: Record<number, TreeNode>;
  atCapacity: boolean; // hit MAX_NODES; further expansion is blocked
  error?: string; // root-level load failure (bad taxid / network)
}

type Action =
  | { type: "reset"; rootId: number }
  | { type: "seedRoot"; node: TaxonNode }
  | { type: "loadStart"; taxid: number }
  | { type: "childrenLoaded"; taxid: number; page: TaxonChildren }
  | { type: "collapse"; taxid: number }
  | { type: "reexpand"; taxid: number }
  | { type: "error"; taxid: number; error: string };

function emptyNode(node: TaxonNode, parentId: number | null, depth: number): TreeNode {
  return {
    node,
    parentId,
    depth,
    childIds: [],
    totalChildren: 0,
    expanded: false,
    loading: false,
  };
}

function reducer(state: TreeState, action: Action): TreeState {
  switch (action.type) {
    case "reset":
      return { rootId: action.rootId, nodes: {}, atCapacity: false, error: undefined };

    case "seedRoot":
      return {
        ...state,
        nodes: { [action.node.taxid]: emptyNode(action.node, null, 0) },
      };

    case "loadStart": {
      const n = state.nodes[action.taxid];
      if (!n) return state;
      return { ...state, nodes: { ...state.nodes, [action.taxid]: { ...n, loading: true, error: undefined } } };
    }

    case "childrenLoaded": {
      const parent = state.nodes[action.taxid];
      if (!parent) return state;
      const nodes = { ...state.nodes };
      const childIds = [...parent.childIds];
      for (const child of action.page.items) {
        if (!(child.taxid in nodes)) {
          nodes[child.taxid] = emptyNode(child, action.taxid, parent.depth + 1);
        }
        if (!childIds.includes(child.taxid)) childIds.push(child.taxid);
      }
      nodes[action.taxid] = {
        ...parent,
        childIds,
        totalChildren: action.page.total,
        expanded: true,
        loading: false,
      };
      return { ...state, nodes, atCapacity: Object.keys(nodes).length >= MAX_NODES };
    }

    case "collapse": {
      const n = state.nodes[action.taxid];
      if (!n) return state;
      return { ...state, nodes: { ...state.nodes, [action.taxid]: { ...n, expanded: false } } };
    }

    case "reexpand": {
      const n = state.nodes[action.taxid];
      if (!n) return state;
      return { ...state, nodes: { ...state.nodes, [action.taxid]: { ...n, expanded: true } } };
    }

    case "error": {
      const n = state.nodes[action.taxid];
      // No node yet (root failed before it seeded) → surface a root-level error.
      if (!n) return { ...state, error: action.error };
      return { ...state, nodes: { ...state.nodes, [action.taxid]: { ...n, loading: false, error: action.error } } };
    }
  }
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export interface Tree extends TreeState {
  /** Expand a collapsed node (loading its first page if needed) or collapse it. */
  toggle: (taxid: number) => void;
  /** Load the next page of a node's children (for nodes with more than shown). */
  loadMore: (taxid: number) => void;
}

/**
 * Load and lazily expand the taxonomy tree rooted at `rootTaxid`. Owns the
 * loaded-hierarchy state and the async child fetches; the rendering layer stays
 * a pure function of the returned state. Changing `rootTaxid` resets the tree
 * and auto-loads the root plus its first ring of children.
 */
export function useTree(rootTaxid: number): Tree {
  const [state, dispatch] = useReducer(reducer, {
    rootId: null,
    nodes: {},
    atCapacity: false,
    error: undefined,
  });
  // Latest state for the stable async callbacks (which read before dispatching).
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    let active = true;
    dispatch({ type: "reset", rootId: rootTaxid });
    // Seed the centre node (metrics from the summary) and its first ring at once;
    // has_children is known from whether the children page reports any total.
    Promise.all([getSummary(rootTaxid), getChildren(rootTaxid, { limit: PAGE_SIZE })])
      .then(([summary, page]) => {
        if (!active) return;
        dispatch({ type: "seedRoot", node: { ...summary, has_children: page.total > 0 } });
        dispatch({ type: "childrenLoaded", taxid: rootTaxid, page });
      })
      .catch((e) => active && dispatch({ type: "error", taxid: rootTaxid, error: errMsg(e) }));
    return () => {
      active = false;
    };
  }, [rootTaxid]);

  const fetchPage = useCallback((taxid: number, offset: number) => {
    dispatch({ type: "loadStart", taxid });
    getChildren(taxid, { limit: PAGE_SIZE, offset })
      .then((page) => dispatch({ type: "childrenLoaded", taxid, page }))
      .catch((e) => dispatch({ type: "error", taxid, error: errMsg(e) }));
  }, []);

  const toggle = useCallback(
    (taxid: number) => {
      const n = stateRef.current.nodes[taxid];
      if (!n || n.loading || !n.node.has_children) return;
      if (n.expanded) {
        dispatch({ type: "collapse", taxid });
      } else if (n.childIds.length > 0) {
        dispatch({ type: "reexpand", taxid }); // already loaded — just show
      } else if (!stateRef.current.atCapacity) {
        fetchPage(taxid, 0);
      }
    },
    [fetchPage],
  );

  const loadMore = useCallback(
    (taxid: number) => {
      const n = stateRef.current.nodes[taxid];
      if (!n || n.loading || stateRef.current.atCapacity) return;
      if (n.childIds.length < n.totalChildren) fetchPage(taxid, n.childIds.length);
    },
    [fetchPage],
  );

  return { ...state, toggle, loadMore };
}
