import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

const REPO_URL = "https://github.com/Cobos-Bioinfo/EukaHub";

// A prefilled GitHub issue — no backend needed. GitHub ignores unknown labels,
// so this works even before a "feedback" label exists on the repo.
const FEEDBACK_URL =
  `${REPO_URL}/issues/new?` +
  new URLSearchParams({
    title: "Feedback: ",
    labels: "feedback",
    body: [
      "**Type:** bug / suggestion / question",
      "",
      "**What happened, or what would you like?**",
      "",
      "",
      "**Page or TaxID (if relevant):**",
      "",
      "",
      "_Sent from the EukaHub web app._",
    ].join("\n"),
  }).toString();

/** The "more" dropdown in the header: feedback, API docs, and the FAQ. */
export default function HeaderMenu() {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div className="menu" ref={boxRef}>
      <button
        type="button"
        className="menu__button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More"
        title="More"
        onClick={() => setOpen((v) => !v)}
      >
        ⋯
      </button>
      {open && (
        <ul className="menu__list" role="menu">
          <li role="none">
            <a
              className="menu__item"
              role="menuitem"
              href={FEEDBACK_URL}
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
            >
              Send feedback ↗
            </a>
          </li>
          <li role="none">
            <a
              className="menu__item"
              role="menuitem"
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
            >
              API docs ↗
            </a>
          </li>
          <li role="none">
            <Link className="menu__item" role="menuitem" to="/faq" onClick={() => setOpen(false)}>
              FAQ
            </Link>
          </li>
        </ul>
      )}
    </div>
  );
}
