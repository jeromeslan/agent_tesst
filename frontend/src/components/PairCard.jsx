function fmt(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function SignalBadge({ value }) {
  return <span className={`badge ${value}`}>{value}</span>;
}

function ScoreBar({ value }) {
  return (
    <div className="scorebar">
      <div className="scorebar-fill" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      <span>{value}</span>
    </div>
  );
}

export default function PairCard({ state }) {
  const det = state.deterministic || {};
  const llm = state.llm || {};
  const perTf = det.per_timeframe || {};
  const tfs = Object.keys(perTf).sort();

  return (
    <article className="card">
      <div className="card-head">
        <h2>{state.pair}</h2>
        <div className="price">
          {fmt(det.last_price, 4)}
          <small>USD</small>
        </div>
      </div>

      <div className="card-row two">
        <div className="verdict">
          <h3>🧮 Déterministe</h3>
          <div className="verdict-line">
            <SignalBadge value={det.signal} />
            <ScoreBar value={det.confidence} />
          </div>
          <p className="muted small">score {det.score} / ±100</p>
        </div>
        <div className="verdict">
          <h3>🤖 Agent LLM {llm.fallback && <em className="warn-text">(repli)</em>}</h3>
          <div className="verdict-line">
            <SignalBadge value={llm.signal} />
            <ScoreBar value={llm.confidence} />
          </div>
          <p className="justify">{llm.justification}</p>
          <p className="muted small">
            {llm.provider}/{llm.model} · {llm.latency_ms} ms
          </p>
        </div>
      </div>

      <div className="volume-line">
        📊 Volume M1 : <strong>{fmt(det.last_volume, 4)}</strong>
        <span className="muted"> — {det.volume_analysis}</span>
      </div>

      <div className="tf-table-wrap">
        <table className="tf-table">
          <thead>
            <tr>
              <th>TF</th>
              <th>Signal</th>
              <th>RSI</th>
              <th>%B</th>
              <th>ADX</th>
              <th>+DI/−DI</th>
              <th>EMA9/21</th>
              <th>Vol x</th>
            </tr>
          </thead>
          <tbody>
            {tfs.map((tf) => {
              const a = perTf[tf];
              return (
                <tr key={tf}>
                  <td>M{tf}</td>
                  <td>
                    <SignalBadge value={a.signal} />{" "}
                    <small className="muted">{a.score > 0 ? "+" : ""}{a.score}</small>
                  </td>
                  <td>{fmt(a.rsi, 1)}</td>
                  <td>{fmt(a.bb_percent_b, 2)}</td>
                  <td>{fmt(a.adx, 1)}</td>
                  <td>
                    {fmt(a.plus_di, 1)}/{fmt(a.minus_di, 1)}
                  </td>
                  <td className={a.ema_fast >= a.ema_slow ? "up" : "down"}>
                    {a.ema_fast >= a.ema_slow ? "▲" : "▼"}
                  </td>
                  <td>{fmt(a.volume_ratio, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {state.order && (
        <div className="order-line">
          📝 Ordre {state.order.side} @ {fmt(state.order.price, 4)} —{" "}
          <span className={`badge ${state.order.status}`}>{state.order.status}</span>
        </div>
      )}
      <p className="muted small">MAJ : {new Date(state.updated_at).toLocaleTimeString()}</p>
    </article>
  );
}
