import { RANGE_LABELS, rangeStyle } from "../lib/ranges";

/** The key to the colour ranges: what is measured, then one swatch per range. */
export default function RangeLegend({ title }: { title: string }) {
  return (
    <div className="ranges">
      <span className="ranges__title">{title}</span>
      <ul className="ranges__list">
        {RANGE_LABELS.map((label, i) => (
          <li key={label} className="ranges__item">
            <span className="ranges__swatch" style={{ background: rangeStyle(i).background }} />
            {label}
          </li>
        ))}
      </ul>
      <span className="ranges__hint">Lighter is less data, darker is more.</span>
    </div>
  );
}
