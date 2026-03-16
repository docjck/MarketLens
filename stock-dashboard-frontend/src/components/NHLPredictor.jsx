// NHLPredictor.jsx — NHL model predictions vs market odds

import { useState, useEffect } from "react";

const API_BASE = "/api";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";
const apiHeaders = () => API_TOKEN ? { "X-API-Token": API_TOKEN } : {};

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

function formatDate(dateStr) {
  if (!dateStr) return "—";
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric", year: "numeric",
  });
}

// ─── Game Card (Today) ─────────────────────────────────────────────────────────

function Badge({ label, bg, color, border }) {
  return (
    <div style={{
      background: bg, border: `1px solid ${border}`, color,
      borderRadius: 4, padding: "2px 8px",
      fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, letterSpacing: 1.5,
      whiteSpace: "nowrap",
    }}>{label}</div>
  );
}

function GameCard({ game }) {
  const { strong_flag, flagged, ou_flagged, ou_strong, ou_edge } = game;

  const anyStrong  = strong_flag || ou_strong;
  const anyFlagged = flagged || ou_flagged;

  const borderColor = anyStrong
    ? "rgba(239,68,68,0.5)"
    : anyFlagged
    ? "rgba(245,158,11,0.4)"
    : "rgba(255,255,255,0.07)";

  const mlBadge = strong_flag
    ? { label: "STRONG EDGE",  bg: "rgba(239,68,68,0.15)",  color: "#ef4444", border: "rgba(239,68,68,0.3)" }
    : flagged
    ? { label: "EDGE",         bg: "rgba(245,158,11,0.12)", color: "#f59e0b", border: "rgba(245,158,11,0.3)" }
    : null;

  const ouDir   = ou_edge != null ? (ou_edge > 0 ? "OVER" : "UNDER") : null;
  const ouBadge = ou_strong
    ? { label: `STRONG ${ouDir} EDGE`, bg: "rgba(239,68,68,0.15)",  color: "#ef4444", border: "rgba(239,68,68,0.3)" }
    : ou_flagged
    ? { label: `${ouDir} EDGE`,        bg: "rgba(245,158,11,0.12)", color: "#f59e0b", border: "rgba(245,158,11,0.3)" }
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
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {mlBadge  && <Badge {...mlBadge} />}
          {ouBadge  && <Badge {...ouBadge} />}
        </div>
      </div>

      {/* Teams */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 12, alignItems: "center" }}>
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 15, color: "#e2e8f0" }}>
            {game.away_name}
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#475569", marginTop: 2 }}>
            {game.away_record} &nbsp;·&nbsp; L10: {game.away_l10 ?? "?"} &nbsp;·&nbsp; GF/G: {game.away_gf_pg}
          </div>
        </div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#334155" }}>@</div>
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
        {["", "AWAY", "HOME"].map((h, i) => (
          <div key={i} style={{
            padding: "6px 12px", fontSize: 9, color: "#334155", letterSpacing: 2,
            borderBottom: "1px solid rgba(255,255,255,0.05)",
            textAlign: i === 0 ? "left" : "center",
          }}>{h}</div>
        ))}
        <div style={{ padding: "8px 12px", fontSize: 10, color: "#475569", letterSpacing: 1 }}>MODEL</div>
        {[game.model_away_prob, game.model_home_prob].map((v, i) => (
          <div key={i} style={{ padding: "8px 12px", textAlign: "center", fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>
            {pct(v)}
          </div>
        ))}
        <div style={{ padding: "8px 12px", fontSize: 10, color: "#475569", letterSpacing: 1 }}>
          IMPLIED {game.home_ml != null ? `(${mlDisplay(game.home_ml)} / ${mlDisplay(game.away_ml)})` : "(no odds)"}
        </div>
        {[game.implied_away_prob, game.implied_home_prob].map((v, i) => (
          <div key={i} style={{ padding: "8px 12px", textAlign: "center", fontSize: 13, color: v != null ? "#94a3b8" : "#334155" }}>
            {pct(v)}
          </div>
        ))}
        <div style={{ padding: "8px 12px", fontSize: 10, color: "#475569", letterSpacing: 1, borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          EDGE
        </div>
        {[game.away_edge, game.home_edge].map((v, i) => {
          const isFlag   = v != null && Math.abs(v) >= 0.05;
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

      {/* Over / Under */}
      {game.ou_line != null && (
        <div style={{
          background: "rgba(0,0,0,0.25)", borderRadius: 8, overflow: "hidden",
          fontFamily: "'IBM Plex Mono', monospace",
        }}>
          {/* Header */}
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr",
            borderBottom: "1px solid rgba(255,255,255,0.05)",
          }}>
            {["OVER / UNDER", "LINE", "MODEL TOTAL", "MODEL P(OVR)", "IMPLIED P(OVR)"].map((h, i) => (
              <div key={i} style={{
                padding: "6px 10px", fontSize: 9, color: "#334155", letterSpacing: 1.5,
                textAlign: i === 0 ? "left" : "center",
              }}>{h}</div>
            ))}
          </div>
          {/* Values row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr" }}>
            {/* Label */}
            <div style={{ padding: "8px 10px", fontSize: 10, color: "#475569", letterSpacing: 1 }}>
              {game.over_ml != null ? `${mlDisplay(game.over_ml)} / ${mlDisplay(game.under_ml)}` : "no odds"}
            </div>
            {/* Line */}
            <div style={{ padding: "8px 10px", textAlign: "center", fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>
              {game.ou_line}
            </div>
            {/* Model expected */}
            <div style={{ padding: "8px 10px", textAlign: "center", fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>
              {game.model_expected ?? "—"}
            </div>
            {/* Model P(over) */}
            <div style={{ padding: "8px 10px", textAlign: "center", fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>
              {pct(game.model_over_prob)}
            </div>
            {/* Implied P(over) */}
            <div style={{ padding: "8px 10px", textAlign: "center", fontSize: 13, color: game.implied_over_prob != null ? "#94a3b8" : "#334155" }}>
              {pct(game.implied_over_prob)}
            </div>
          </div>
          {/* Edge row */}
          {game.ou_edge != null && (
            <div style={{
              display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr",
              borderTop: "1px solid rgba(255,255,255,0.05)",
            }}>
              <div style={{ padding: "8px 10px", fontSize: 10, color: "#475569", letterSpacing: 1 }}>EDGE</div>
              <div style={{ gridColumn: "2 / 5" }} />
              {(() => {
                const isStrong = Math.abs(game.ou_edge) >= 0.10;
                const isFlag   = Math.abs(game.ou_edge) >= 0.05;
                const color    = isStrong ? "#ef4444" : isFlag ? "#f59e0b" : "#475569";
                const dir      = game.ou_edge > 0 ? "OVER" : "UNDER";
                return (
                  <div style={{
                    padding: "8px 10px", textAlign: "center", fontSize: 12, fontWeight: 600, color,
                  }}>
                    {edge(game.ou_edge)} {dir}
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── History Pick Row ──────────────────────────────────────────────────────────

function HistoryPickRow({ pick }) {
  const isWin     = pick.result === "WIN";
  const isLoss    = pick.result === "LOSS";
  const isPending = pick.result === "PENDING";

  const resultBadge = isWin
    ? { label: "WIN",     bg: "rgba(0,255,136,0.10)", color: "#00ff88", border: "rgba(0,255,136,0.25)" }
    : isLoss
    ? { label: "LOSS",    bg: "rgba(239,68,68,0.10)", color: "#ef4444", border: "rgba(239,68,68,0.25)" }
    : { label: "PENDING", bg: "rgba(71,85,105,0.20)", color: "#475569", border: "rgba(71,85,105,0.3)"  };

  const edgeTeamName = pick.edge_team === "home" ? pick.home_name : pick.away_name;
  const edgePct      = `+${(pick.edge_value * 100).toFixed(1)}%`;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "10px 14px",
      background: "rgba(255,255,255,0.015)",
      borderRadius: 8,
      fontFamily: "'IBM Plex Mono', monospace",
    }}>
      {/* Result badge */}
      <div style={{
        flexShrink: 0,
        minWidth: 64,
        textAlign: "center",
        background: resultBadge.bg,
        border: `1px solid ${resultBadge.border}`,
        color: resultBadge.color,
        borderRadius: 4,
        padding: "3px 8px",
        fontSize: 9,
        letterSpacing: 1.5,
        fontWeight: 700,
      }}>
        {resultBadge.label}
      </div>

      {/* Matchup */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "#e2e8f0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {pick.away_name} <span style={{ color: "#334155" }}>@</span> {pick.home_name}
        </div>
        <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
          Pick: <span style={{ color: "#94a3b8" }}>{edgeTeamName}</span>
          {pick.strong_flag ? (
            <span style={{ marginLeft: 8, color: "#ef4444" }}>STRONG</span>
          ) : null}
        </div>
      </div>

      {/* Edge value */}
      <div style={{ flexShrink: 0, textAlign: "right" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#f59e0b" }}>{edgePct}</div>
        <div style={{ fontSize: 9, color: "#334155", marginTop: 2, letterSpacing: 1 }}>EDGE</div>
      </div>

      {/* Time */}
      <div style={{ flexShrink: 0, fontSize: 10, color: "#334155", textAlign: "right", minWidth: 60 }}>
        {formatTime(pick.start_utc)}
      </div>
    </div>
  );
}

// ─── Day Section ──────────────────────────────────────────────────────────────

function DaySection({ day }) {
  const [open, setOpen] = useState(true);

  const winRate = (day.wins + day.losses) > 0
    ? `${Math.round(day.wins / (day.wins + day.losses) * 100)}%`
    : null;

  return (
    <div style={{
      border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 10,
      overflow: "hidden",
    }}>
      {/* Day header — clickable to collapse */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%",
          background: "rgba(255,255,255,0.03)",
          border: "none",
          cursor: "pointer",
          padding: "12px 16px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", letterSpacing: 1.5 }}>
          {open ? "▾" : "▸"}
        </span>
        <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 13, color: "#e2e8f0", flex: 1, textAlign: "left" }}>
          {formatDate(day.date)}
        </span>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", display: "flex", gap: 14 }}>
          <span>{day.picks.length} pick{day.picks.length !== 1 ? "s" : ""}</span>
          {day.wins > 0   && <span style={{ color: "#00ff88" }}>{day.wins}W</span>}
          {day.losses > 0 && <span style={{ color: "#ef4444" }}>{day.losses}L</span>}
          {day.pending > 0 && <span style={{ color: "#475569" }}>{day.pending} pending</span>}
          {winRate && <span style={{ color: "#94a3b8" }}>{winRate}</span>}
        </span>
      </button>

      {/* Picks list */}
      {open && (
        <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
          {day.picks.map(p => <HistoryPickRow key={p.game_id} pick={p} />)}
        </div>
      )}
    </div>
  );
}

// ─── Edge History ─────────────────────────────────────────────────────────────

function EdgeHistory({ data, loading, error }) {
  if (loading) return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {[1, 2, 3].map(i => (
        <div key={i} className="skeleton" style={{ height: 56, borderRadius: 10 }} />
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

  if (!data) return null;

  const { totals, picks_by_date } = data;
  const winRatePct = totals.win_rate != null ? `${(totals.win_rate * 100).toFixed(1)}%` : "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

      {/* Running totals bar */}
      <div style={{
        background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: 12, padding: "14px 20px",
        display: "flex", gap: 28, flexWrap: "wrap",
        fontFamily: "'IBM Plex Mono', monospace",
      }}>
        {[
          { label: "TOTAL PICKS", value: totals.total,   color: "#e2e8f0" },
          { label: "WINS",        value: totals.wins,    color: totals.wins > 0    ? "#00ff88" : "#e2e8f0" },
          { label: "LOSSES",      value: totals.losses,  color: totals.losses > 0  ? "#ef4444" : "#e2e8f0" },
          { label: "PENDING",     value: totals.pending, color: "#475569" },
          { label: "WIN RATE",    value: winRatePct,     color: totals.win_rate != null
              ? totals.win_rate >= 0.6 ? "#00ff88" : totals.win_rate >= 0.45 ? "#f59e0b" : "#ef4444"
              : "#475569" },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <div style={{ fontSize: 9, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 600, color }}>{value}</div>
          </div>
        ))}
      </div>

      {picks_by_date.length === 0 ? (
        <div style={{
          textAlign: "center", padding: "48px 24px",
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#334155", letterSpacing: 2,
        }}>
          NO EDGE PICKS RECORDED YET — CHECK BACK AFTER TODAY'S GAMES
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {picks_by_date.map(day => <DaySection key={day.date} day={day} />)}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function NHLPredictor() {
  const [tab, setTab]           = useState("today");
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [histData, setHistData]   = useState(null);
  const [histLoading, setHistLoading] = useState(true);
  const [histError, setHistError]   = useState(null);

  useEffect(() => {
    // Fetch today's predictions
    setLoading(true);
    fetch(`${API_BASE}/nhl/predictions`, { headers: apiHeaders() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(json => { if (json.error) throw new Error(json.error); setData(json); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));

    // Fetch edge history
    setHistLoading(true);
    fetch(`${API_BASE}/nhl/edge-history`, { headers: apiHeaders() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(json => setHistData(json))
      .catch(e => setHistError(e.message))
      .finally(() => setHistLoading(false));
  }, []);

  // ── Tab bar ──
  const tabs = [
    { key: "today",   label: "TODAY" },
    { key: "history", label: "EDGE HISTORY" + (histData?.totals?.total > 0 ? ` (${histData.totals.total})` : "") },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>

      {/* Tab selector */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid rgba(255,255,255,0.07)", paddingBottom: 0 }}>
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              background: "none",
              border: "none",
              borderBottom: tab === t.key ? "2px solid #00ff88" : "2px solid transparent",
              cursor: "pointer",
              padding: "8px 14px",
              marginBottom: -1,
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 10,
              letterSpacing: 2,
              color: tab === t.key ? "#00ff88" : "#475569",
              transition: "color 0.15s",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Today tab */}
      {tab === "today" && (
        <>
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[1, 2, 3].map(i => (
                <div key={i} className="skeleton" style={{ height: 180, borderRadius: 12 }} />
              ))}
            </div>
          ) : error ? (
            <div style={{
              background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
              borderRadius: 12, padding: "20px 24px",
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#fca5a5",
            }}>
              ⚠ {error}
            </div>
          ) : (
            <>
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
                  <div style={{ fontSize: 20, fontWeight: 600, color: data.games.filter(g => g.flagged || g.ou_flagged).length > 0 ? "#f59e0b" : "#e2e8f0" }}>
                    {data.games.filter(g => g.flagged || g.ou_flagged).length}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>ML ODDS</div>
                  <div style={{ fontSize: 13, color: data.odds_available ? "#00ff88" : "#475569", marginTop: 4 }}>
                    {data.odds_available ? "LIVE" : "NO KEY"}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>O/U ODDS</div>
                  <div style={{ fontSize: 13, color: data.ou_available ? "#00ff88" : "#ef4444", marginTop: 4 }}>
                    {data.ou_available ? "LIVE" : "NOT RECEIVED"}
                  </div>
                </div>
                {data.odds_error && (
                  <div style={{ flex: "1 1 100%", fontSize: 10, color: "#ef4444", fontFamily: "'IBM Plex Mono', monospace", marginTop: 4 }}>
                    ⚠ {data.odds_error}
                  </div>
                )}
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

              {(() => {
                const flagged = data.games.filter(g => g.flagged || g.ou_flagged);
                const rest    = data.games.filter(g => !g.flagged && !g.ou_flagged);
                return (
                  <>
                    {flagged.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#f59e0b", letterSpacing: 2.5, padding: "0 4px" }}>
                          FLAGGED EDGES
                        </div>
                        {flagged.map(g => <GameCard key={g.game_id} game={g} />)}
                      </div>
                    )}
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
                  </>
                );
              })()}
            </>
          )}
        </>
      )}

      {/* History tab */}
      {tab === "history" && (
        <EdgeHistory data={histData} loading={histLoading} error={histError} />
      )}
    </div>
  );
}
