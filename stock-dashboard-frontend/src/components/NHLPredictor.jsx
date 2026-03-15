// NHLPredictor.jsx — NHL model predictions vs market odds

import { useState, useEffect } from "react";

const API_BASE = "/api";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(v) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function edge(v) {
  if (v == null) return null;
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(1)}%`;
}

function mlDisplay(v) {
  if (v == null) return "—";
  return v > 0 ? `+${v}` : `${v}`;
}

function formatTime(utcStr) {
  if (!utcStr) return "—";
  const d = new Date(utcStr);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
}

// ─── Game Card ────────────────────────────────────────────────────────────────

function GameCard({ game }) {
  const { strong_flag, flagged, home_edge } = game;
  const edgeDir = home_edge != null ? (home_edge > 0 ? "home" : "away") : null;

  const borderColor = strong_flag
    ? "rgba(239,68,68,0.5)"
    : flagged
    ? "rgba(245,158,11,0.4)"
    : "rgba(255,255,255,0.07)";

  const flagBadge = strong_flag
    ? { label: "STRONG EDGE", bg: "rgba(239,68,68,0.15)", color: "#ef4444", border: "rgba(239,68,68,0.3)" }
    : flagged
    ? { label: "EDGE", bg: "rgba(245,158,11,0.12)", color: "#f59e0b", border: "rgba(245,158,11,0.3)" }
    : null;

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)",
      border: `1px solid ${borderColor}`,
      borderRadius: 12,
      padding: "18px 20px",
      display: "flex",
      flexDirection: "column",
      gap: 14,
      transition: "border-color 0.2s",
    }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#334155", letterSpacing: 2 }}>
          {formatTime(game.start_utc)}
        </div>
        {flagBadge && (
          <div style={{
            background: flagBadge.bg, border: `1px solid ${flagBadge.border}`,
            color: flagBadge.color, borderRadius: 4, padding: "2px 8px",
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, letterSpacing: 1.5,
          }}>
            {flagBadge.label}
          </div>
        )}
      </div>

      {/* Teams */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 12, alignItems: "center" }}>
        {/* Away */}
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 15, color: "#e2e8f0" }}>
            {game.away_name}
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#475569", marginTop: 2 }}>
            {game.away_record} &nbsp;·&nbsp; L10: {game.away_l10 ?? "?"} &nbsp;·&nbsp; GF/G: {game.away_gf_pg}
          </div>
        </div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#334155" }}>@</div>
        {/* Home */}
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 15, color: "#e2e8f0" }}>
            {game.home_name}
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#475569", marginTop: 2 }}>
            {game.home_record} &nbsp;·&nbsp; L10: {game.home_l10 ?? "?"} &nbsp;·&nbsp; GF/G: {game.home_gf_pg}
          </div>
        </div>
      </div>

      {/* Probability table */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 0,
        background: "rgba(0,0,0,0.25)",
        borderRadius: 8,
        overflow: "hidden",
        fontFamily: "'IBM Plex Mono', monospace",
      }}>
        {/* Column headers */}
        {["", "AWAY", "HOME"].map((h, i) => (
          <div key={i} style={{
            padding: "6px 12px", fontSize: 9, color: "#334155", letterSpacing: 2,
            borderBottom: "1px solid rgba(255,255,255,0.05)",
            textAlign: i === 0 ? "left" : "center",
          }}>{h}</div>
        ))}

        {/* Model row */}
        <div style={{ padding: "8px 12px", fontSize: 10, color: "#475569", letterSpacing: 1 }}>MODEL</div>
        {[game.model_away_prob, game.model_home_prob].map((v, i) => (
          <div key={i} style={{ padding: "8px 12px", textAlign: "center", fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>
            {pct(v)}
          </div>
        ))}

        {/* Implied row */}
        <div style={{ padding: "8px 12px", fontSize: 10, color: "#475569", letterSpacing: 1 }}>
          IMPLIED {game.home_ml != null ? `(${mlDisplay(game.home_ml)} / ${mlDisplay(game.away_ml)})` : "(no odds)"}
        </div>
        {[game.implied_away_prob, game.implied_home_prob].map((v, i) => (
          <div key={i} style={{ padding: "8px 12px", textAlign: "center", fontSize: 13, color: v != null ? "#94a3b8" : "#334155" }}>
            {pct(v)}
          </div>
        ))}

        {/* Edge row */}
        <div style={{ padding: "8px 12px", fontSize: 10, color: "#475569", letterSpacing: 1, borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          EDGE
        </div>
        {[game.away_edge, game.home_edge].map((v, i) => {
          const isFlag = v != null && Math.abs(v) >= 0.05;
          const isStrong = v != null && Math.abs(v) >= 0.10;
          const color = v == null ? "#334155" : isStrong ? "#ef4444" : isFlag ? "#f59e0b" : "#475569";
          return (
            <div key={i} style={{
              padding: "8px 12px", textAlign: "center", fontSize: 12, fontWeight: 600,
              color, borderTop: "1px solid rgba(255,255,255,0.05)",
            }}>
              {edge(v) ?? "—"}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function NHLPredictor() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/nhl/predictions`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(json => {
        if (json.error) throw new Error(json.error);
        setData(json);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {[1, 2, 3].map(i => (
        <div key={i} className="skeleton" style={{ height: 180, borderRadius: 12 }} />
      ))}
    </div>
  );

  if (error) return (
    <div style={{
      background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
      borderRadius: 12, padding: "20px 24px",
      fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#fca5a5",
    }}>
      ⚠ {error}
    </div>
  );

  const flagged  = data.games.filter(g => g.flagged);
  const rest     = data.games.filter(g => !g.flagged);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Summary bar */}
      <div style={{
        background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: 12, padding: "14px 20px",
        display: "flex", gap: 32, flexWrap: "wrap",
        fontFamily: "'IBM Plex Mono', monospace",
      }}>
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>GAMES TODAY</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: "#e2e8f0" }}>{data.game_count}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>EDGES FLAGGED</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: flagged.length > 0 ? "#f59e0b" : "#e2e8f0" }}>
            {flagged.length}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>ODDS SOURCE</div>
          <div style={{ fontSize: 13, color: data.odds_available ? "#00ff88" : "#475569", marginTop: 4 }}>
            {data.odds_available ? "LIVE (The Odds API)" : "MODEL ONLY — add ODDS_API_KEY"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>EDGE THRESHOLD</div>
          <div style={{ fontSize: 13, color: "#475569", marginTop: 4 }}>≥5% flag &nbsp;·&nbsp; ≥10% strong</div>
        </div>
      </div>

      {data.game_count === 0 && (
        <div style={{
          textAlign: "center", padding: "48px 24px",
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#334155", letterSpacing: 2,
        }}>
          NO NHL GAMES SCHEDULED TODAY
        </div>
      )}

      {/* Flagged games first */}
      {flagged.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#f59e0b", letterSpacing: 2.5, padding: "0 4px" }}>
            FLAGGED EDGES
          </div>
          {flagged.map(g => <GameCard key={g.game_id} game={g} />)}
        </div>
      )}

      {/* Remaining games */}
      {rest.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {flagged.length > 0 && (
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#334155", letterSpacing: 2.5, padding: "0 4px" }}>
              ALL GAMES
            </div>
          )}
          {rest.map(g => <GameCard key={g.game_id} game={g} />)}
        </div>
      )}
    </div>
  );
}
