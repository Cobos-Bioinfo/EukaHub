import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { Link } from "react-router";

import type { CladeSummary } from "../api/types";
import { MAX_VISIBLE_NODES, PAGE_SIZE, type Tree, type TreeState } from "../hooks/useTree";
import { cladePath } from "../lib/clade";
import { fmt, fmtPct } from "../lib/format";
import type { Measure } from "../lib/measures";
import { rangeOf, rangeStyle } from "../lib/ranges";
import { ChevronIcon } from "./icons";

// Card size and spacing in px: one column per level, one row per card.
const CARD_W = 300;
const CARD_H = 52;
const COL_GAP = 48;
const ROW_GAP = 10;
const PAD = 24;
const COL = CARD_W + COL_GAP;
const ROW = CARD_H + ROW_GAP;
// Zoom: its bounds, and the factor one press of a button applies.
const ZOOM_MIN = 0.3;
const ZOOM_MAX = 1.5;
const ZOOM_STEP = 1.25;
const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

interface Point {
  x: number;
  y: number;
}
interface Layout {
  cards: Map<number, Point>;
  more: Map<number, Point>; // a parent's "Show more" button, by the parent's taxid
  links: [Point, Point][];
  width: number;
  height: number;
}

/** Where each visible card goes: a column per level and a row per card without
 *  open children, each open card centred on its children, so branches never
 *  cross. A parent with more children to load gets a "Show more" row last. */
function layout({ nodes, rootId }: Pick<TreeState, "nodes" | "rootId">): Layout {
  const cards = new Map<number, Point>();
  const more = new Map<number, Point>();
  const links: [Point, Point][] = [];
  let rows = 0;
  let depthMax = 0;
  const place = (id: number, depth: number): number => {
    const tn = nodes[id];
    depthMax = Math.max(depthMax, depth);
    const kids = tn.expanded ? tn.childIds.filter((c) => nodes[c]) : [];
    const ys = kids.map((c) => place(c, depth + 1));
    if (tn.expanded && tn.totalChildren > tn.childIds.length) {
      const y = PAD + rows++ * ROW;
      more.set(id, { x: PAD + (depth + 1) * COL, y });
      ys.push(y);
    }
    const at = {
      x: PAD + depth * COL,
      y: ys.length > 0 ? (ys[0] + ys[ys.length - 1]) / 2 : PAD + rows++ * ROW,
    };
    cards.set(id, at);
    for (const y of ys) links.push([at, { x: at.x + COL, y }]);
    return at.y;
  };
  if (rootId != null && nodes[rootId]) place(rootId, 0);
  return {
    cards,
    more,
    links,
    width: PAD * 2 + depthMax * COL + CARD_W,
    height: PAD * 2 + Math.max(rows, 1) * ROW - ROW_GAP,
  };
}

const linkPath = ([a, b]: [Point, Point]) => {
  const x0 = a.x + CARD_W;
  const y0 = a.y + CARD_H / 2;
  const y1 = b.y + CARD_H / 2;
  const mid = x0 + COL_GAP / 2;
  return `M${x0},${y0} C${mid},${y0} ${mid},${y1} ${b.x},${y1}`;
};

const upperFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** The line under a name: what the share is of, then the share, its word read
 *  out to screen readers only; for a single species, whether it has data. */
function Note({ n, measure }: { n: CladeSummary; measure: Measure }) {
  const share = measure.share(n);
  const unit = n.is_infraspecific || n.rank === "species" || n.rank === "informal species";
  if (unit && measure.whole === "Species") {
    return <>{share ? upperFirst(measure.word) : "None yet"}</>;
  }
  if (share === null) return <>No assemblies</>;
  return (
    <>
      {fmt(measure.count(n).whole)} {measure.whole.toLowerCase()} ·{" "}
      {share > 0 ? (
        <>
          {fmtPct(share)}%<span className="sr-only"> {measure.word}</span>
        </>
      ) : (
        "none yet"
      )}
    </>
  );
}

const smooth = (): ScrollBehavior =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

/** The scroll offset that shows [start, end] moving least from `at`, its start
 *  first when it does not fit in `size`. */
const fit = (start: number, end: number, at: number, size: number) =>
  start - PAD < at
    ? start - PAD
    : end + PAD > at + size
      ? Math.min(start - PAD, end + PAD - size)
      : at;

/** The width the options card covers on the right of the view (the CSS sets it
 *  as the scroll padding). */
const covered = (el: HTMLElement) => parseFloat(getComputedStyle(el).scrollPaddingRight) || 0;

/** Safari's pinch on a trackpad (other browsers send it as a wheel with Ctrl). */
type GestureEvent = UIEvent & { scale: number; clientX: number; clientY: number };

/** The tree drawn left to right: each card a group, coloured by the range its
 *  share of the measure falls in. A click on a card opens or closes its branch
 *  (its arrow is the button for keyboards) and its name links to its Summary.
 *  The cards are nested lists in tree order, so the drawing reads as an outline
 *  too. Scroll or drag the background to move; Ctrl and scroll, a pinch or the
 *  buttons in the corner zoom. */
export default function CladeTree({
  tree,
  measure,
  found,
}: {
  tree: Tree;
  measure: Measure;
  /** A group found from the search box: scrolled to, marked and focused. */
  found: { taxid: number; nonce: number } | null;
}) {
  const { nodes, rootId } = tree;
  const at = useMemo(() => layout({ nodes, rootId }), [nodes, rootId]);
  const scroller = useRef<HTMLDivElement>(null);
  // The card last opened or closed stays where it was on screen; once its
  // children arrive, the view moves the least that shows them.
  const anchor = useRef<{ id: number; dy: number } | null>(null);
  // After "Show more", focus moves to the first group it loaded.
  const focusNext = useRef<{ parent: number; index: number } | null>(null);
  const marked = found?.taxid;

  // The drawing is scaled by `zoom`, so every position below is multiplied by it.
  const [zoom, setZoom] = useState(1);
  const zoomRef = useRef(zoom);
  // Where to scroll once the new zoom is drawn, so the point under the pointer
  // (or the middle of the view) stays put.
  const zoomScroll = useRef<{ left: number; top: number } | null>(null);
  const zoomTo = (next: number, ox?: number, oy?: number) => {
    const el = scroller.current;
    const from = zoomRef.current;
    const to = clampZoom(next);
    if (!el || to === from) return;
    const x = ox ?? (el.clientWidth - covered(el)) / 2;
    const y = oy ?? el.clientHeight / 2;
    const { left, top } = zoomScroll.current ?? { left: el.scrollLeft, top: el.scrollTop };
    zoomScroll.current = {
      left: ((left + x) / from) * to - x,
      top: ((top + y) / from) * to - y,
    };
    zoomRef.current = to;
    setZoom(to);
  };
  const zoomToFit = () => {
    const el = scroller.current;
    if (!el) return;
    const to = clampZoom(
      Math.min(
        (el.clientWidth - covered(el) - 2 * PAD) / at.width,
        (el.clientHeight - 2 * PAD) / at.height,
        1,
      ),
    );
    zoomScroll.current = { left: 0, top: 0 };
    zoomRef.current = to;
    setZoom(to);
  };
  useLayoutEffect(() => {
    const el = scroller.current;
    const s = zoomScroll.current;
    if (!el || !s) return;
    zoomScroll.current = null;
    el.scrollLeft = s.left;
    el.scrollTop = s.top;
  }, [zoom]);

  // Ctrl (or Cmd) and the wheel zooms around the pointer, as does a trackpad pinch;
  // a plain wheel still scrolls. The listeners are not passive, so the page itself
  // does not zoom.
  const zoomToRef = useRef(zoomTo);
  zoomToRef.current = zoomTo;
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const offset = (e: { clientX: number; clientY: number }) => {
      const r = el.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top] as const;
    };
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const step = e.deltaMode === WheelEvent.DOM_DELTA_LINE ? e.deltaY * 16 : e.deltaY;
      zoomToRef.current(zoomRef.current * Math.exp(-step * 0.002), ...offset(e));
    };
    let pinchFrom = 1;
    const onGestureStart = (e: Event) => {
      e.preventDefault();
      pinchFrom = zoomRef.current;
    };
    const onGestureChange = (e: Event) => {
      e.preventDefault();
      const g = e as GestureEvent;
      zoomToRef.current(pinchFrom * g.scale, ...offset(g));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("gesturestart", onGestureStart);
    el.addEventListener("gesturechange", onGestureChange);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("gesturestart", onGestureStart);
      el.removeEventListener("gesturechange", onGestureChange);
    };
  }, []);

  const toggle = (id: number) => {
    const el = scroller.current;
    const p = at.cards.get(id);
    if (el && p) anchor.current = { id, dy: p.y * zoom - el.scrollTop };
    tree.toggle(id);
  };

  useLayoutEffect(() => {
    const el = scroller.current;
    const a = anchor.current;
    const p = a && at.cards.get(a.id);
    if (!el || !a || !p) return;
    const z = zoomRef.current;
    el.scrollTop = p.y * z - a.dy;
    const tn = nodes[a.id];
    if (tn?.loading) return;
    anchor.current = null;
    const first = tn?.expanded ? at.cards.get(tn.childIds[0]) : undefined;
    if (!tn || !first) return;
    const last = at.more.get(a.id) ?? at.cards.get(tn.childIds[tn.childIds.length - 1])!;
    el.scrollTo({
      left: fit(p.x * z, (first.x + CARD_W) * z, el.scrollLeft, el.clientWidth - covered(el)),
      top: fit(first.y * z, (last.y + CARD_H) * z, el.scrollTop, el.clientHeight),
      behavior: smooth(),
    });
  }, [at, nodes]);

  useEffect(() => {
    const next = focusNext.current;
    const tn = next && nodes[next.parent];
    if (!next || !tn || tn.loading) return;
    focusNext.current = null;
    const id = tn.childIds[next.index];
    if (id === undefined) return;
    scroller.current
      ?.querySelector<HTMLElement>(`[data-taxid="${id}"] .ctree__name`)
      ?.focus({ preventScroll: true });
  }, [nodes]);

  const showMore = (id: number, all: boolean) => {
    focusNext.current = { parent: id, index: nodes[id].childIds.length };
    tree.loadMore(id, all);
  };

  useEffect(() => {
    const el = scroller.current;
    const p = found && at.cards.get(found.taxid);
    if (!found || !el || !p) return;
    const z = zoomRef.current;
    el.scrollTo({
      left: (p.x + CARD_W / 2) * z - (el.clientWidth - covered(el)) / 2,
      top: (p.y + CARD_H / 2) * z - el.clientHeight / 2,
      behavior: smooth(),
    });
    el.querySelector<HTMLElement>(`[data-taxid="${found.taxid}"] .ctree__name`)?.focus({
      preventScroll: true,
    });
    // Only a new search moves the view; opening and closing branches after it must not.
  }, [found]); // eslint-disable-line react-hooks/exhaustive-deps

  // Dragging the background with a mouse moves the view; touch scrolls natively.
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    const el = scroller.current;
    if (!el || e.pointerType !== "mouse" || e.button !== 0) return;
    if ((e.target as Element).closest(".ctree__card, .ctree__more")) return;
    drag.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop };
    el.setPointerCapture(e.pointerId);
    el.classList.add("ctree__scroller--drag");
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const el = scroller.current;
    const d = drag.current;
    if (!el || !d) return;
    el.scrollLeft = d.left - (e.clientX - d.x);
    el.scrollTop = d.top - (e.clientY - d.y);
  };
  const endDrag = () => {
    drag.current = null;
    scroller.current?.classList.remove("ctree__scroller--drag");
  };

  const root = rootId != null ? nodes[rootId] : undefined;

  const branch = (id: number) => {
    const tn = nodes[id];
    const p = at.cards.get(id);
    if (!tn || !p) return null;
    const { node, expanded, childIds, loading, error } = tn;
    const range = rangeOf(measure.share(node));
    const morePoint = at.more.get(id);
    const left = tn.totalChildren - childIds.length;
    const blocked = !expanded && tree.atCapacity;
    const opens = node.has_children && !blocked;
    return (
      <li key={id} aria-busy={loading || undefined}>
        <div
          className={
            "ctree__card" +
            (opens ? " ctree__card--opens" : "") +
            (id === rootId ? " ctree__card--root" : "") +
            (id === marked ? " ctree__card--found" : "")
          }
          style={{ left: p.x, top: p.y, width: CARD_W, height: CARD_H }}
          data-taxid={id}
          onClick={(e) => {
            if (opens && !(e.target as Element).closest("a, button")) toggle(id);
          }}
        >
          {node.has_children ? (
            <button
              type="button"
              className={"ctree__toggle" + (expanded ? " ctree__toggle--open" : "")}
              aria-expanded={expanded}
              aria-disabled={blocked || undefined}
              aria-label={`${expanded ? "Close" : "Open"} ${node.name}`}
              title={blocked ? "Close a branch to open another" : undefined}
              onClick={() => !blocked && toggle(id)}
            >
              {loading ? <span className="ctree__spinner" aria-hidden="true" /> : <ChevronIcon />}
            </button>
          ) : (
            <span className="ctree__toggle ctree__toggle--leaf" aria-hidden="true" />
          )}
          <span className="ctree__swatch" style={{ background: rangeStyle(range).background }} />
          <span className="ctree__text">
            <span className="ctree__line">
              <Link className="ctree__name" to={cladePath(id)} title={node.name}>
                {node.name}
              </Link>
              {node.rank !== "no rank" && <span className="ctree__rank">{node.rank}</span>}
            </span>
            {error ? (
              <span className="ctree__note ctree__note--error" role="alert">
                Could not load its groups.{" "}
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => (expanded ? tree.loadMore(id) : toggle(id))}
                >
                  Try again
                </button>
              </span>
            ) : (
              <span className="ctree__note">
                <Note n={node} measure={measure} />
              </span>
            )}
          </span>
        </div>
        {expanded && (childIds.length > 0 || morePoint) && (
          <ul>
            {childIds.map(branch)}
            {morePoint && (
              <li
                className="ctree__more"
                style={{ left: morePoint.x, top: morePoint.y, width: CARD_W, height: CARD_H }}
              >
                {loading ? (
                  <span className="ctree__more-note">Loading…</span>
                ) : (
                  <>
                    <button
                      type="button"
                      className="link-btn"
                      disabled={tree.atCapacity}
                      onClick={() => showMore(id, false)}
                    >
                      Show {fmt(Math.min(left, PAGE_SIZE))} more
                    </button>
                    {left > PAGE_SIZE &&
                      (left <= MAX_VISIBLE_NODES - tree.visible ? (
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => showMore(id, true)}
                        >
                          Show all {fmt(left)}
                        </button>
                      ) : (
                        <span className="ctree__more-note">{fmt(left)} left</span>
                      ))}
                  </>
                )}
              </li>
            )}
          </ul>
        )}
      </li>
    );
  };

  return (
    <>
      <div
        className="ctree__scroller"
        ref={scroller}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {root ? (
          <div className="ctree__sizer" style={{ width: at.width * zoom, height: at.height * zoom }}>
            <div
              className="ctree__plane"
              style={{ width: at.width, height: at.height, transform: `scale(${zoom})` }}
            >
              <svg
                className="ctree__links"
                width={at.width}
                height={at.height}
                aria-hidden="true"
              >
                {at.links.map((l, i) => (
                  <path key={i} d={linkPath(l)} />
                ))}
              </svg>
              <ul className="ctree__list" aria-label={`${root.node.name} and the groups inside it`}>
                {branch(root.node.taxid)}
              </ul>
            </div>
          </div>
        ) : (
          <p className="notice ctree__loading">Loading the tree…</p>
        )}
      </div>
      <div className="ctree__zoom" role="group" aria-label="Zoom">
        <button
          type="button"
          aria-label="Zoom out"
          disabled={zoom <= ZOOM_MIN}
          onClick={() => zoomTo(zoom / ZOOM_STEP)}
        >
          −
        </button>
        <button
          type="button"
          className="ctree__zoom-level"
          aria-label={`Zoom ${Math.round(zoom * 100)}%, back to 100%`}
          onClick={() => zoomTo(1)}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          type="button"
          aria-label="Zoom in"
          disabled={zoom >= ZOOM_MAX}
          onClick={() => zoomTo(zoom * ZOOM_STEP)}
        >
          +
        </button>
        <button type="button" aria-label="Fit the whole tree in view" onClick={zoomToFit}>
          Fit
        </button>
      </div>
    </>
  );
}
