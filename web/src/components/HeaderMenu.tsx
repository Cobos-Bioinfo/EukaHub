import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { useSiteConfig } from "../hooks/useSiteConfig";

/** The "more" dropdown in the header: feedback, API docs, and the FAQ. */
export default function HeaderMenu() {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  // The deployment's feedback form (by default a Google Form that files a GitHub
  // issue, so no GitHub account is needed).
  const feedbackUrl = useSiteConfig()?.feedback_url;

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
          {feedbackUrl && (
            <li role="none">
              <a
                className="menu__item"
                role="menuitem"
                href={feedbackUrl}
                target="_blank"
                rel="noreferrer"
                onClick={() => setOpen(false)}
              >
                Send feedback ↗
              </a>
            </li>
          )}
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
          <li role="none">
            <Link
              className="menu__item"
              role="menuitem"
              to="/privacy"
              onClick={() => setOpen(false)}
            >
              Privacy
            </Link>
          </li>
        </ul>
      )}
    </div>
  );
}
