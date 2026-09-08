import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import PairCard from "./components/PairCard.jsx";
import ModeToggle from "./components/ModeToggle.jsx";
import PendingOrders from "./components/PendingOrders.jsx";

const POLL_MS = 5000;

export default function App() {
  const [status, setStatus] = useState(null);
  const [signals, setSignals] = useState([]);
  const [pending, setPending] = useState([]);
  const [orders, setOrders] = useState([]);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const timer = useRef(null);

  const load = useCallback(async () => {
    try {
      const [st, sig, pend, all] = await Promise.all([
        api.status(),
        api.signals(),
        api.orders("PENDING"),
        api.orders(),
      ]);
      setStatus(st);
      setSignals(sig.signals || []);
      setPending(pend.orders || []);
      setOrders(all.orders || []);
      setError("");
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
    timer.current = setInterval(load, POLL_MS);
    return () => clearInterval(timer.current);
  }, [load]);

  const handleMode = async (mode) => {
    await api.setMode(mode);
    await load();
  };

  const handleThreshold = async (threshold) => {
    await api.setThreshold(threshold);
    await load();
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refresh();
      await load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setRefreshing(false);
    }
  };

  const decide = async (id, action) => {
    try {
      if (action === "approve") await api.approve(id);
      else await api.reject(id);
      await load();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>⚡ Hybrid Algo-Trading</h1>
          <p className="subtitle">Moteur déterministe + Agent LLM — Kraken spot · Paper trading</p>
        </div>
        <div className="topbar-right">
          <span className={`pill ${status?.ws_connected ? "ok" : "warn"}`}>
            {status?.ws_connected ? "● Kraken WS live" : "○ Kraken WS…"}
          </span>
          <span className="pill">
            LLM : {status?.llm_provider}/{status?.llm_model}
            {status?.llm_configured ? "" : " (clé manquante)"}
          </span>
          <button className="btn" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? "Analyse…" : "↻ Analyser"}
          </button>
        </div>
      </header>

      {error && <div className="alert">⚠️ {error}</div>}

      <ModeToggle status={status} onMode={handleMode} onThreshold={handleThreshold} />

      {status?.mode === "HITM" && (
        <PendingOrders orders={pending} onDecide={decide} />
      )}

      <section className="grid">
        {signals.map((s) => (
          <PairCard key={s.pair} state={s} />
        ))}
        {signals.length === 0 && !error && (
          <p className="muted">En attente du premier cycle d'analyse…</p>
        )}
      </section>

      <section className="panel">
        <h2>Ordres paper trading (virtuels)</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Heure</th>
                <th>Paire</th>
                <th>Side</th>
                <th>Prix</th>
                <th>LLM</th>
                <th>Score</th>
                <th>Statut</th>
                <th>Décidé par</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>{new Date(o.time).toLocaleTimeString()}</td>
                  <td>{o.pair}</td>
                  <td>
                    <span className={`badge ${o.side}`}>{o.side}</span>
                  </td>
                  <td>{Number(o.price).toLocaleString()}</td>
                  <td className="justify" title={o.llm_justification}>
                    {(o.llm_justification || "").slice(0, 80)}
                    {(o.llm_justification || "").length > 80 ? "…" : ""}
                  </td>
                  <td>{o.llm_score}</td>
                  <td>
                    <span className={`badge ${o.status}`}>{o.status}</span>
                  </td>
                  <td>{o.decided_by}</td>
                </tr>
              ))}
              {orders.length === 0 && (
                <tr>
                  <td colSpan="8" className="muted">
                    Aucun ordre pour le moment.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="footer muted">
        Dernier cycle : {status?.last_cycle_at ? new Date(status.last_cycle_at).toLocaleString() : "—"}
        {" · "}Cycles : {status?.cycles_count ?? 0}
        {" · "}Seuil : {status?.threshold} · Actualisation toutes les 5 s.
      </footer>
    </div>
  );
}
