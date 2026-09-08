export default function PendingOrders({ orders, onDecide }) {
  return (
    <section className="panel pending">
      <h2>⏳ Signaux en attente de validation ({orders.length})</h2>
      {orders.length === 0 && (
        <p className="muted">Aucun signal en attente. Les prochains signaux LLM ≥ seuil apparaîtront ici.</p>
      )}
      <div className="pending-list">
        {orders.map((o) => (
          <div key={o.id} className="pending-card">
            <div>
              <strong>{o.pair}</strong> <span className={`badge ${o.side}`}>{o.side}</span>{" "}
              <span className="muted small">
                @ {Number(o.price).toLocaleString()} · LLM {o.llm_score} · dét {o.det_signal}({o.det_score})
              </span>
              <p className="justify">{o.llm_justification}</p>
            </div>
            <div className="pending-actions">
              <button className="btn approve" onClick={() => onDecide(o.id, "approve")}>
                ✓ Approuver
              </button>
              <button className="btn reject" onClick={() => onDecide(o.id, "reject")}>
                ✕ Rejeter
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
