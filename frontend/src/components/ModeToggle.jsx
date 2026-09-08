export default function ModeToggle({ status, onMode, onThreshold }) {
  const mode = status?.mode || "HITM";
  return (
    <section className="panel mode-panel">
      <div>
        <h2>Mode d'exécution</h2>
        <p className="muted small">
          {mode === "FULL_AUTO"
            ? "FULL_AUTO : les ordres dont le score LLM ≥ seuil sont exécutés (paper) automatiquement."
            : "HITM : chaque signal est mis en attente de votre validation ci-dessous."}
        </p>
      </div>
      <div className="mode-controls">
        <div className="toggle">
          <button
            className={mode === "FULL_AUTO" ? "active auto" : ""}
            onClick={() => onMode("FULL_AUTO")}
          >
            FULL_AUTO
          </button>
          <button
            className={mode === "HITM" ? "active hitm" : ""}
            onClick={() => onMode("HITM")}
          >
            HITM
          </button>
        </div>
        <label className="threshold">
          Seuil confiance : <strong>{status?.threshold ?? "—"}</strong>
          <input
            type="range"
            min="0"
            max="100"
            value={status?.threshold ?? 70}
            onChange={(e) => onThreshold(Number(e.target.value))}
          />
        </label>
      </div>
    </section>
  );
}
