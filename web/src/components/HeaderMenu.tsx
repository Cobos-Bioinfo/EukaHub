import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { useSiteConfig } from "../hooks/useSiteConfig";
import { toggleTheme, useTheme } from "../lib/theme";

/** The "more" menu in the top bar: FAQ, API docs, feedback, source code and
 *  privacy, plus Compare and the theme on a phone, where the bar has no room
 *  for them. */
export default function HeaderMenu() {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const site = useSiteConfig();
  const dark = useTheme() === "dark";

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const close = () => setOpen(false);
  return (
    <div
      className="menu"
      ref={boxRef}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          close();
          buttonRef.current?.focus();
        }
      }}
    >
      <button
        type="button"
        ref={buttonRef}
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
          <li role="none" className="menu__phone">
            <Link className="menu__item" role="menuitem" to="/compare" onClick={close}>
              Compare
            </Link>
          </li>
          <li role="none" className="menu__phone">
            <button
              type="button"
              className="menu__item"
              role="menuitem"
              onClick={() => {
                toggleTheme();
                close();
              }}
            >
              {dark ? "Light theme" : "Dark theme"}
            </button>
          </li>
          <li role="none">
            <Link className="menu__item" role="menuitem" to="/faq" onClick={close}>
              FAQ
            </Link>
          </li>
          <li role="none">
            <a
              className="menu__item"
              role="menuitem"
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              onClick={close}
            >
              API docs ↗
            </a>
          </li>
          {site?.feedback_url && (
            <li role="none">
              <a
                className="menu__item"
                role="menuitem"
                href={site.feedback_url}
                target="_blank"
                rel="noreferrer"
                onClick={close}
              >
                Send feedback ↗
              </a>
            </li>
          )}
          {site?.source_code_url && (
            <li role="none">
              <a
                className="menu__item"
                role="menuitem"
                href={site.source_code_url}
                target="_blank"
                rel="noreferrer"
                onClick={close}
              >
                Source code ↗
              </a>
            </li>
          )}
          <li role="none">
            <Link className="menu__item" role="menuitem" to="/privacy" onClick={close}>
              Privacy
            </Link>
          </li>
        </ul>
      )}
    </div>
  );
}
