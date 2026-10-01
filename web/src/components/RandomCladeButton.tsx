import { useNavigate, useParams } from "react-router";

import { useSiteConfig } from "../hooks/useSiteConfig";
import { pickRandomTaxid } from "../lib/clades";

/** Jumps to a random curated group's dashboard. Reused as a prominent hero
 *  button and a compact icon in the app bar. Reads the current `:taxid` from the
 *  route (when present) so a re-roll always lands on a different group. Disabled
 *  until the groups have loaded. */
export default function RandomCladeButton({
  className,
  title,
  children,
}: {
  className?: string;
  title?: string;
  children: React.ReactNode;
}) {
  const navigate = useNavigate();
  const { taxid } = useParams();
  const groups = useSiteConfig()?.groups ?? [];
  const current = taxid ? Number(taxid) : undefined;
  return (
    <button
      type="button"
      className={className}
      title={title}
      disabled={groups.length === 0}
      onClick={() => {
        const next = pickRandomTaxid(groups, current);
        if (next !== undefined) navigate(`/clade/${next}`);
      }}
    >
      {children}
    </button>
  );
}
