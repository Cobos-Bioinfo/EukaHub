import { useCallback, useEffect, useReducer, useRef } from "react";

import { getChildren, getTaxon } from "../api/queries";
import type { TaxonNode, TaxonPage } from "../api/types";

// How many children to load per expand / "load more" (matches the API default).
export const PAGE_SIZE = 10;
// Most nodes drawn at once (those under expanded parents), so the SVG stays
// responsive. Collapsing a branch frees room.
export const MAX_VISIBLE_NODES = 600;
// Reveal (search-to-locate): page each level in bigger chunks than a manual
// expand to cut round-trips, but cap the pages per level so locating a node
// buried deep in a huge, species-sorted sibling list can't page forever.
const REVEAL_LIMIT = 100;
const REVEAL_MAX_PAGES = 4;

/** Outcome of {@link Tree.reveal}: the path fully opened to the target, the
 *  target sits too deep in a wide sibling list to reach within the page cap, or
 *  a newer reveal replaced this one. */
export type RevealResult =
  | { status: "ok"; taxid: number }
  | { status: "buried"; reached: number }
  | { status: "superseded" };

/** One loaded node in the tree: its taxon data plus expand/paging bookkeeping. */
export interface TreeNode {
  node: TaxonNode;
  parentId: number | null; // null for the root
  depth: number; // 0 = root
  childIds: number[]; // loaded children, in load (species-sorted) order
  totalChildren: number; // total available (from the API), for "load more"
  nextCursor: string | null; // where the next page of children starts
  expanded: boolean;
  loading: boolean;
  error?: string;
}

export interface TreeState {
  rootId: number | null;
  majorRanks: boolean; // what the tree was loaded with (see useTree)
  nodes: Record<number, TreeNode>;
  visible: number; // nodes drawn: the root and the children of every open node
  atCapacity: boolean; // MAX_VISIBLE_NODES drawn; expanding is blocked until a collapse
  error?: string; // root-level load failure (bad taxid / network)
}

type Action =
  | { type: "reset"; rootId: number; majorRanks: boolean }
  | { type: "seedRoot"; node: TaxonNode }
  | { type: "loadStart"; taxid: number }
  | { type: "childrenLoaded"; taxid: number; page: TaxonPage }
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
    nextCursor: null,
    expanded: false,
    loading: false,
  };
}

function countVisible(nodes: Record<number, TreeNode>, rootId: number | null): number {
  if (rootId == null) return 0;
  let count = 0;
  const stack = [rootId];
  while (stack.length > 0) {
    const n = nodes[stack.pop()!];
    if (!n) continue;
    count++;
    if (n.expanded) stack.push(...n.childIds);
  }
  return count;
}

function withCapacity(state: TreeState): TreeState {
  const visible = countVisible(state.nodes, state.rootId);
  return { ...state, visible, atCapacity: visible >= MAX_VISIBLE_NODES };
}

function reducer(state: TreeState, action: Action): TreeState {
  switch (action.type) {
    case "reset":
      return {
        rootId: action.rootId,
        majorRanks: action.majorRanks,
        nodes: {},
        visible: 0,
        atCapacity: false,
        error: undefined,
      };

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
      for (const child of action.page.results) {
        if (!(child.taxid in nodes)) {
          nodes[child.taxid] = emptyNode(child, action.taxid, parent.depth + 1);
        }
        if (!childIds.includes(child.taxid)) childIds.push(child.taxid);
      }
      nodes[action.taxid] = {
        ...parent,
        childIds,
        totalChildren: action.page.total,
        nextCursor: action.page.next,
        expanded: true,
        loading: false,
      };
      return withCapacity({ ...state, nodes });
    }

    case "collapse": {
      const n = state.nodes[action.taxid];
      if (!n) return state;
      return withCapacity({ ...state, nodes: { ...state.nodes, [action.taxid]: { ...n, expanded: false } } });
    }

    case "reexpand": {
      const n = state.nodes[action.taxid];
      if (!n) return state;
      return withCapacity({ ...state, nodes: { ...state.nodes, [action.taxid]: { ...n, expanded: true } } });
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
  /** Load the next page of a node's children, or with `all` every one left (as
   *  many as MAX_VISIBLE_NODES leaves room for). */
  loadMore: (taxid: number, all?: boolean) => void;
  /** Open the tree down to a descendant so it can be highlighted. `pathTaxids`
   *  is the chain of taxids from the root's direct child down to the target;
   *  each level is expanded and paged until the next node on the path appears. */
  reveal: (pathTaxids: number[]) => Promise<RevealResult>;
}

/**
 * Load and lazily expand the taxonomy tree rooted at `rootTaxid`: every child of
 * a taxon, or with `majorRanks` its nearest descendants of a major rank. Owns the
 * loaded-hierarchy state and the async child fetches; the rendering layer stays
 * a pure function of the returned state. Changing either argument resets the
 * tree and loads the root plus its first ring of children.
 */
export function useTree(rootTaxid: number, majorRanks: boolean): Tree {
  const [state, dispatch] = useReducer(reducer, {
    rootId: null,
    majorRanks,
    nodes: {},
    visible: 0,
    atCapacity: false,
    error: undefined,
  });
  // Latest state for the stable async callbacks (which read before dispatching).
  const stateRef = useRef(state);
  stateRef.current = state;
  // Bumped on every reset, so an answer for an earlier tree is dropped.
  const generation = useRef(0);

  useEffect(() => {
    const gen = ++generation.current;
    dispatch({ type: "reset", rootId: rootTaxid, majorRanks });
    // Seed the root and its first ring at once.
    Promise.all([
      getTaxon(rootTaxid),
      getChildren(rootTaxid, { limit: PAGE_SIZE, major_ranks: majorRanks }),
    ])
      .then(([taxon, page]) => {
        if (gen !== generation.current) return;
        dispatch({ type: "seedRoot", node: taxon });
        dispatch({ type: "childrenLoaded", taxid: rootTaxid, page });
      })
      .catch((e) => {
        if (gen === generation.current) dispatch({ type: "error", taxid: rootTaxid, error: errMsg(e) });
      });
  }, [rootTaxid, majorRanks]);

  const fetchPage = useCallback(
    (taxid: number, cursor?: string, limit = PAGE_SIZE) => {
      const gen = generation.current;
      dispatch({ type: "loadStart", taxid });
      getChildren(taxid, { limit, cursor, major_ranks: majorRanks })
        .then((page) => {
          if (gen === generation.current) dispatch({ type: "childrenLoaded", taxid, page });
        })
        .catch((e) => {
          if (gen === generation.current) dispatch({ type: "error", taxid, error: errMsg(e) });
        });
    },
    [majorRanks],
  );

  const toggle = useCallback(
    (taxid: number) => {
      const n = stateRef.current.nodes[taxid];
      if (!n || n.loading || !n.node.has_children) return;
      if (n.expanded) {
        dispatch({ type: "collapse", taxid });
      } else if (stateRef.current.atCapacity) {
        return;
      } else if (n.childIds.length > 0) {
        dispatch({ type: "reexpand", taxid });
      } else {
        fetchPage(taxid);
      }
    },
    [fetchPage],
  );

  const loadMore = useCallback(
    (taxid: number, all = false) => {
      const { nodes, visible, atCapacity } = stateRef.current;
      const n = nodes[taxid];
      if (!n || n.loading || atCapacity || !n.nextCursor) return;
      const left = n.totalChildren - n.childIds.length;
      const room = MAX_VISIBLE_NODES - visible;
      fetchPage(taxid, n.nextCursor, all ? Math.max(1, Math.min(left, room)) : PAGE_SIZE);
    },
    [fetchPage],
  );

  // Guards against a stale reveal (a second search started before the first
  // finished paging): each call bumps the token and bails if it's superseded.
  const revealSeq = useRef(0);
  const reveal = useCallback(
    async (pathTaxids: number[]): Promise<RevealResult> => {
      const seq = ++revealSeq.current;
      const gen = generation.current;
      const startId = stateRef.current.rootId;
      if (startId == null) return { status: "buried", reached: -1 };
      let parentId: number = startId;
      for (const step of pathTaxids) {
        const parent: TreeNode | undefined = stateRef.current.nodes[parentId];
        // `loaded` mirrors the reducer's contiguous append, and the parent's cursor
        // says where its next page starts. A node never loaded starts at the top.
        const loaded: number[] = parent ? [...parent.childIds] : [];
        const everLoaded = parent ? parent.expanded || parent.childIds.length > 0 : false;
        let cursor = everLoaded && parent ? parent.nextCursor : undefined;
        let pages = 0;
        while (!loaded.includes(step) && cursor !== null && pages < REVEAL_MAX_PAGES) {
          if (revealSeq.current !== seq) return { status: "superseded" };
          const page = await getChildren(parentId, {
            limit: REVEAL_LIMIT,
            cursor,
            major_ranks: majorRanks,
          });
          if (revealSeq.current !== seq || gen !== generation.current) {
            return { status: "superseded" };
          }
          dispatch({ type: "childrenLoaded", taxid: parentId, page });
          cursor = page.next;
          for (const c of page.results) if (!loaded.includes(c.taxid)) loaded.push(c.taxid);
          pages++;
        }
        if (!loaded.includes(step)) return { status: "buried", reached: parentId };
        parentId = step;
      }
      return { status: "ok", taxid: parentId };
    },
    [majorRanks],
  );

  return { ...state, toggle, loadMore, reveal };
}
