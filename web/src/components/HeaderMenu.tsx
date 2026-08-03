import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

// Feedback path: a Google Form that files a labeled GitHub issue via an Apps
// Script server-side, so no GitHub account is needed. Users who have an account
// can open an issue on GitHub directly (with templates); the FAQ says so.
const FEEDBACK_FORM_URL =
  "https://docs.google.com/forms/d/e/1FAIpQLSfEEOn9g8c1G14DLkRr9qlMQldLdibyVO7zotzkIT4PKYgMKQ/viewform";

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
              href={FEEDBACK_FORM_URL}
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
