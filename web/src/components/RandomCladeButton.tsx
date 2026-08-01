import { useNavigate, useParams } from "react-router-dom";

import { pickRandomCladeTaxid } from "../lib/clades";

/** Jumps to a random featured clade's dashboard. Reused as a prominent hero
 *  button and a compact icon in the app bar. Reads the current `:taxid` from the
 *  route (when present) so a re-roll always lands on a different group. */
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
  const current = taxid ? Number(taxid) : undefined;
  return (
    <button
      type="button"
      className={className}
      title={title}
      onClick={() => navigate(`/clade/${pickRandomCladeTaxid(current)}`)}
    >
      {children}
    </button>
  );
}
