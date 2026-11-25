import type { SimpleLayer } from "@/lib/api";

// The "explain simply" layer: plain words, an everyday analogy, and the jargon defined.
// Used on the concept card (Simple tab) and after a wrong answer.
export default function SimpleExplanation({ layer, compact = false }: { layer: SimpleLayer; compact?: boolean }) {
  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {layer.explanation && (
        <p className={`${compact ? "" : "text-lg"} font-semibold leading-relaxed`}>{layer.explanation}</p>
      )}
      {layer.analogy && (
        <p className="sticker-flat flex gap-2.5 bg-sky-soft px-3 py-2 font-semibold">
          <span aria-hidden>💡</span>
          <span>
            <b>Think of it like this:</b> {layer.analogy}
          </span>
        </p>
      )}
      {layer.glossary.length > 0 && (
        <div>
          <p className="font-display text-lg font-extrabold">Words to know</p>
          <dl className="mt-1 space-y-1.5">
            {layer.glossary.map((g) => (
              <div key={g.term} className="sticker-flat bg-white px-3 py-1.5">
                <dt className="inline font-extrabold">{g.term}</dt>
                <dd className="inline font-semibold text-ink-soft">: {g.meaning}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
