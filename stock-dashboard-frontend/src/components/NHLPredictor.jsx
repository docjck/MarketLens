// NHLPredictor.jsx — NHL model predictions vs market odds

import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";

const API_BASE = "/api";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";
const apiHeaders = (extra = {}) => API_TOKEN ? { "X-API-Token": API_TOKEN, ...extra } : { ...extra };

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

function getPastDates(n = 10) {
  const dates = [];
  for (let i = 1; i <= n; i++) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates;
}

function fmtShortDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
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

      {/* Unit result */}
      {pick.unit_result != null && (
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
          color: pick.unit_result > 0 ? "#00ff88" : "#ef4444", marginLeft: 8,
        }}>
          {pick.unit_result > 0 ? "+" : ""}{pick.unit_result.toFixed(2)}u
        </span>
      )}

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

// ─── P&L Chart ────────────────────────────────────────────────────────────────

function PLChart({ data }) {
  // data: [{ date: "2026-03-20", cumulative: 1.43 }, ...]
  if (!data || data.length < 2) return null;

  const netUnits = data[data.length - 1]?.cumulative ?? 0;
  const color    = netUnits >= 0 ? "#00ff88" : "#ef4444";

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 9,
        color: "#334155", letterSpacing: 2, marginBottom: 8,
      }}>
        CUMULATIVE UNITS P&L
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
          <XAxis
            dataKey="date"
            tick={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fill: "#334155" }}
            axisLine={false} tickLine={false}
            tickFormatter={d => d.slice(5)}
          />
          <YAxis
            tick={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fill: "#334155" }}
            axisLine={false} tickLine={false}
            tickFormatter={v => `${v > 0 ? "+" : ""}${v.toFixed(1)}u`}
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
          <Tooltip
            contentStyle={{
              background: "#0d1424", border: "1px solid rgba(255,255,255,0.10)",
              borderRadius: 8, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
            }}
            labelStyle={{ color: "#475569", fontSize: 10 }}
            formatter={(v) => [`${v > 0 ? "+" : ""}${v.toFixed(2)}u`, "Net units"]}
          />
          <Line
            type="monotone" dataKey="cumulative"
            stroke={color} strokeWidth={2} dot={false}
            activeDot={{ r: 3, fill: color }}
          />
        </LineChart>
      </ResponsiveContainer>
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
          { label: "UNITS RISKED", value: totals.units_risked ?? "—", color: "#e2e8f0" },
          {
            label: "NET UNITS",
            value: totals.net_units != null
              ? `${totals.net_units > 0 ? "+" : ""}${totals.net_units.toFixed(2)}u`
              : "—",
            color: totals.net_units != null
              ? totals.net_units > 0 ? "#00ff88" : totals.net_units < 0 ? "#ef4444" : "#e2e8f0"
              : "#475569",
          },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <div style={{ fontSize: 9, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 600, color }}>{value}</div>
          </div>
        ))}
      </div>

      <PLChart data={data?.cumulative_units} />

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

// ─── Backtest Components ──────────────────────────────────────────────────────

function BacktestGameCard({ game, picks, setPicks, scored }) {
  const gid  = String(game.game_id);
  const pick = picks[gid];
  const scoreData = scored?.find(s => s.game_id === game.game_id);

  const isStrong = game.confidence >= 0.20;
  const isLean   = game.confidence >= 0.10;
  const fav      = game.model_home_prob >= 0.5 ? game.home_name : game.away_name;

  const leanBadge = isStrong
    ? { label: "STRONG LEAN", color: "#ef4444", border: "rgba(239,68,68,0.3)",  bg: "rgba(239,68,68,0.12)"  }
    : isLean
    ? { label: "LEAN",        color: "#f59e0b", border: "rgba(245,158,11,0.3)", bg: "rgba(245,158,11,0.10)" }
    : null;

  const isWin  = scoreData?.result === "WIN";
  const isLoss = scoreData?.result === "LOSS";

  const togglePick = (side) => {
    if (scoreData) return;
    setPicks(prev => {
      const next = { ...prev };
      if (next[gid]?.side === side) {
        delete next[gid];
      } else {
        next[gid] = { side, home_ml: game.home_ml ?? null, away_ml: game.away_ml ?? null };
      }
      return next;
    });
  };

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)",
      border: `1px solid ${pick ? "rgba(0,255,136,0.2)" : "rgba(255,255,255,0.07)"}`,
      borderRadius: 12, padding: "16px 18px",
      display: "flex", flexDirection: "column", gap: 12,
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#334155", letterSpacing: 2 }}>
          {formatTime(game.start_utc)}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {leanBadge && (
            <div style={{
              background: leanBadge.bg, border: `1px solid ${leanBadge.border}`,
              color: leanBadge.color, borderRadius: 4, padding: "2px 8px",
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, letterSpacing: 1.5,
            }}>
              {leanBadge.label} — {fav}
            </div>
          )}
          {scoreData && (
            <div style={{
              background: isWin ? "rgba(0,255,136,0.12)" : isLoss ? "rgba(239,68,68,0.12)" : "rgba(71,85,105,0.2)",
              border: `1px solid ${isWin ? "rgba(0,255,136,0.3)" : isLoss ? "rgba(239,68,68,0.3)" : "rgba(71,85,105,0.3)"}`,
              color: isWin ? "#00ff88" : isLoss ? "#ef4444" : "#475569",
              borderRadius: 4, padding: "2px 10px",
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, letterSpacing: 1.5, fontWeight: 700,
            }}>
              {scoreData.result}
            </div>
          )}
        </div>
      </div>

      {/* Teams */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 8, alignItems: "center" }}>
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 14, color: "#e2e8f0" }}>{game.away_name}</div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", marginTop: 2 }}>{game.away_record}</div>
          {scoreData && (
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 22, fontWeight: 700, marginTop: 6,
              color: scoreData.actual_winner === "away" ? "#00ff88" : "#475569" }}>
              {scoreData.away_score ?? "—"}
            </div>
          )}
        </div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: "#334155" }}>@</div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 14, color: "#e2e8f0" }}>{game.home_name}</div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", marginTop: 2 }}>{game.home_record}</div>
          {scoreData && (
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 22, fontWeight: 700, marginTop: 6,
              color: scoreData.actual_winner === "home" ? "#00ff88" : "#475569" }}>
              {scoreData.home_score ?? "—"}
            </div>
          )}
        </div>
      </div>

      {/* Model prob bar */}
      <div style={{ display: "grid", gridTemplateColumns: "44px 1fr 44px", gap: 8, alignItems: "center" }}>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#475569", textAlign: "right" }}>
          {pct(game.model_away_prob)}
        </div>
        <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden", display: "flex" }}>
          <div style={{ width: `${game.model_away_prob * 100}%`, background: "rgba(99,102,241,0.55)" }} />
          <div style={{ flex: 1, background: "rgba(59,130,246,0.55)" }} />
        </div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#475569" }}>
          {pct(game.model_home_prob)}
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#334155", letterSpacing: 1, marginTop: -8 }}>
        <span>{game.away_abbrev} AWAY</span>
        <span>HOME {game.home_abbrev}</span>
      </div>

      {/* Pick buttons — hidden after scoring */}
      {!scoreData && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {(["away", "home"]).map(side => {
            const selected = pick?.side === side;
            const abbrev   = side === "away" ? game.away_abbrev : game.home_abbrev;
            return (
              <button key={side} onClick={() => togglePick(side)} style={{
                background: selected ? "rgba(0,255,136,0.10)" : "rgba(255,255,255,0.03)",
                border: `1px solid ${selected ? "rgba(0,255,136,0.35)" : "rgba(255,255,255,0.09)"}`,
                color: selected ? "#00ff88" : "#475569",
                borderRadius: 6, padding: "8px 12px", cursor: "pointer",
                fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: 1.5,
                transition: "all 0.15s", textAlign: "center",
              }}>
                {side === "away" ? `← ${abbrev}` : `${abbrev} →`}
              </button>
            );
          })}
        </div>
      )}

      {/* After scoring: show which team was picked */}
      {scoreData && pick && (
        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569" }}>
          <span>PICKED: <span style={{ color: "#94a3b8" }}>{pick?.side === "home" ? game.home_name : game.away_name}</span></span>
          <span style={{ color: "#334155" }}>MODEL {pct(pick?.side === "home" ? game.model_home_prob : game.model_away_prob)}</span>
        </div>
      )}
    </div>
  );
}

function BacktestHistoryRow({ pick }) {
  const isWin  = pick.result === "WIN";
  const isLoss = pick.result === "LOSS";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
      background: "rgba(255,255,255,0.015)", borderRadius: 8,
      fontFamily: "'IBM Plex Mono', monospace",
    }}>
      <div style={{
        flexShrink: 0, minWidth: 60, textAlign: "center",
        background: isWin ? "rgba(0,255,136,0.10)" : isLoss ? "rgba(239,68,68,0.10)" : "rgba(71,85,105,0.20)",
        border: `1px solid ${isWin ? "rgba(0,255,136,0.25)" : isLoss ? "rgba(239,68,68,0.25)" : "rgba(71,85,105,0.3)"}`,
        color: isWin ? "#00ff88" : isLoss ? "#ef4444" : "#475569",
        borderRadius: 4, padding: "3px 8px", fontSize: 9, letterSpacing: 1.5, fontWeight: 700,
      }}>
        {pick.result}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "#e2e8f0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {pick.away_name} <span style={{ color: "#334155" }}>@</span> {pick.home_name}
        </div>
        <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
          Pick: <span style={{ color: "#94a3b8" }}>{pick.picked_team === "home" ? pick.home_name : pick.away_name}</span>
        </div>
      </div>
      <div style={{ flexShrink: 0, textAlign: "right" }}>
        <div style={{ fontSize: 12, color: "#94a3b8" }}>
          {pick.home_score != null ? `${pick.away_score} – ${pick.home_score}` : "—"}
        </div>
        <div style={{ fontSize: 9, color: "#334155", marginTop: 2, letterSpacing: 1 }}>
          MODEL {pct(pick.picked_team === "home" ? pick.model_h_prob : pick.model_a_prob)}
        </div>
        {pick.unit_result != null && (
          <div style={{
            fontSize: 10, marginTop: 1, letterSpacing: 0.5,
            fontFamily: "'IBM Plex Mono', monospace",
            color: pick.unit_result > 0 ? "#00ff88" : "#ef4444",
          }}>
            {pick.unit_result > 0 ? "+" : ""}{pick.unit_result.toFixed(2)}u
          </div>
        )}
      </div>
    </div>
  );
}

function BacktestHistorySession({ session }) {
  const [open, setOpen] = useState(true);
  const winRate = (session.wins + session.losses) > 0
    ? `${Math.round(session.wins / (session.wins + session.losses) * 100)}%`
    : null;
  return (
    <div style={{ border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, overflow: "hidden" }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: "100%", background: "rgba(255,255,255,0.03)", border: "none", cursor: "pointer",
        padding: "12px 16px", display: "flex", alignItems: "center", gap: 12,
      }}>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", letterSpacing: 1.5 }}>{open ? "▾" : "▸"}</span>
        <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 13, color: "#e2e8f0", flex: 1, textAlign: "left" }}>
          {fmtShortDate(session.date)}
        </span>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", display: "flex", gap: 14 }}>
          <span>{session.picks.length} pick{session.picks.length !== 1 ? "s" : ""}</span>
          {session.wins   > 0 && <span style={{ color: "#00ff88" }}>{session.wins}W</span>}
          {session.losses > 0 && <span style={{ color: "#ef4444" }}>{session.losses}L</span>}
          {session.pending > 0 && <span style={{ color: "#475569" }}>{session.pending} pending</span>}
          {winRate && <span style={{ color: "#94a3b8" }}>{winRate}</span>}
          {session.net_units != null && (
            <span style={{ color: session.net_units >= 0 ? "#00ff88" : "#ef4444" }}>
              {session.net_units > 0 ? "+" : ""}{session.net_units.toFixed(2)}u
            </span>
          )}
        </span>
      </button>
      {open && (
        <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
          {session.picks.map(p => <BacktestHistoryRow key={p.id} pick={p} />)}
        </div>
      )}
    </div>
  );
}

function BacktestHistoryPanel({ data, loading, error }) {
  if (loading) return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 52, borderRadius: 10 }} />)}
    </div>
  );
  if (error) return (
    <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 12, padding: "20px 24px", fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#fca5a5" }}>
      ⚠ {error}
    </div>
  );
  if (!data) return null;
  const { totals, sessions } = data;
  const winRatePct = totals.win_rate != null ? `${(totals.win_rate * 100).toFixed(1)}%` : "—";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{
        background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: 12, padding: "14px 20px", display: "flex", gap: 28, flexWrap: "wrap",
        fontFamily: "'IBM Plex Mono', monospace",
      }}>
        {[
          { label: "TOTAL PICKS", value: totals.total,  color: "#e2e8f0" },
          { label: "WINS",        value: totals.wins,   color: totals.wins   > 0 ? "#00ff88" : "#e2e8f0" },
          { label: "LOSSES",      value: totals.losses, color: totals.losses > 0 ? "#ef4444" : "#e2e8f0" },
          { label: "WIN RATE",    value: winRatePct,    color: totals.win_rate != null
              ? totals.win_rate >= 0.6 ? "#00ff88" : totals.win_rate >= 0.45 ? "#f59e0b" : "#ef4444"
              : "#475569" },
          { label: "UNITS RISKED", value: totals.units_risked ?? "—", color: "#e2e8f0" },
          {
            label: "NET UNITS",
            value: totals.net_units != null
              ? `${totals.net_units > 0 ? "+" : ""}${totals.net_units.toFixed(2)}u`
              : "—",
            color: totals.net_units != null
              ? totals.net_units > 0 ? "#00ff88" : totals.net_units < 0 ? "#ef4444" : "#e2e8f0"
              : "#475569",
          },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <div style={{ fontSize: 9, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 600, color }}>{value}</div>
          </div>
        ))}
      </div>
      <PLChart data={data?.cumulative_units} />
      {sessions.length === 0 ? (
        <div style={{ textAlign: "center", padding: "48px 24px", fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#334155", letterSpacing: 2 }}>
          NO BACKTEST SESSIONS YET
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {sessions.map(s => <BacktestHistorySession key={s.date} session={s} />)}
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

  // Backtest state
  const [btSubTab,     setBtSubTab]     = useState("pick");
  const [btDate,       setBtDate]       = useState(null);
  const [btGames,      setBtGames]      = useState(null);
  const [btLoading,    setBtLoading]    = useState(false);
  const [btError,      setBtError]      = useState(null);
  const [btPicks,      setBtPicks]      = useState({});
  const [btResults,    setBtResults]    = useState(null);
  const [btScoring,    setBtScoring]    = useState(false);
  const [btHistData,   setBtHistData]   = useState(null);
  const [btHistLoad,   setBtHistLoad]   = useState(false);
  const [btHistError,  setBtHistError]  = useState(null);

  const loadBtHistory = async () => {
    setBtHistLoad(true); setBtHistError(null);
    try {
      const r = await fetch(`${API_BASE}/nhl/backtest/history`, { headers: apiHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setBtHistData(await r.json());
    } catch (e) { setBtHistError(e.message); }
    finally { setBtHistLoad(false); }
  };

  const loadBtGames = async (date) => {
    setBtDate(date); setBtGames(null); setBtPicks({}); setBtResults(null);
    setBtLoading(true); setBtError(null);
    try {
      const r = await fetch(`${API_BASE}/nhl/backtest/games/${date}`, { headers: apiHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      if (json.error) throw new Error(json.error);
      setBtGames(json.games);
    } catch (e) { setBtError(e.message); }
    finally { setBtLoading(false); }
  };

  const scoreBtPicks = async () => {
    const picks = Object.entries(btPicks)
      .filter(([, pickData]) => pickData !== undefined)
      .map(([gid, pickData]) => {
        const g = btGames.find(g => g.game_id === parseInt(gid));
        if (!g) return null;
        return {
          game_id:         parseInt(gid),
          picked_team:     pickData.side,
          home_name:       g.home_name,
          away_name:       g.away_name,
          home_abbrev:     g.home_abbrev,
          away_abbrev:     g.away_abbrev,
          model_home_prob: g.model_home_prob,
          model_away_prob: g.model_away_prob,
          home_ml:         pickData.home_ml,
          away_ml:         pickData.away_ml,
        };
      }).filter(Boolean);
    if (!picks.length) return;
    setBtScoring(true); setBtError(null);
    try {
      const r = await fetch(`${API_BASE}/nhl/backtest/score`, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ date: btDate, picks }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      setBtResults(json);
      loadBtHistory();
    } catch (e) { setBtError(e.message); }
    finally { setBtScoring(false); }
  };

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
  useEffect(() => {
    if (tab === "backtest" && btSubTab === "history" && !btHistData && !btHistLoad) {
      loadBtHistory();
    }
  }, [tab, btSubTab]);

  const tabs = [
    { key: "today",    label: "TODAY" },
    { key: "history",  label: "EDGE HISTORY" + (histData?.totals?.total > 0 ? ` (${histData.totals.total})` : "") },
    { key: "backtest", label: "BACKTEST" },
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

      {/* Backtest tab */}
      {tab === "backtest" && (() => {
        const PAST_DATES = getPastDates(10);
        const pickCount  = Object.values(btPicks).filter(Boolean).length;
        const summary    = btResults?.summary;

        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Sub-tab bar */}
            <div style={{ display: "flex", gap: 4, borderBottom: "1px solid rgba(255,255,255,0.07)", paddingBottom: 0 }}>
              {[
                { key: "pick",    label: "PICK GAMES" },
                { key: "history", label: "BACKTEST HISTORY" + (btHistData?.totals?.total > 0 ? ` (${btHistData.totals.total})` : "") },
              ].map(st => (
                <button key={st.key} onClick={() => { setBtSubTab(st.key); if (st.key === "history" && !btHistData) loadBtHistory(); }} style={{
                  background: "none", border: "none",
                  borderBottom: btSubTab === st.key ? "2px solid #00ff88" : "2px solid transparent",
                  cursor: "pointer", padding: "8px 14px", marginBottom: -1,
                  fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: 2,
                  color: btSubTab === st.key ? "#00ff88" : "#475569", transition: "color 0.15s",
                }}>
                  {st.label}
                </button>
              ))}
            </div>

            {/* PICK tab */}
            {btSubTab === "pick" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                {/* Instruction */}
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", letterSpacing: 1.5 }}>
                  SELECT A PAST DATE — PICK GAMES WITHOUT SEEING RESULTS — THEN REVEAL
                </div>

                {/* Date picker */}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {PAST_DATES.map(d => (
                    <button key={d} onClick={() => loadBtGames(d)} style={{
                      background: btDate === d ? "rgba(0,255,136,0.10)" : "rgba(255,255,255,0.03)",
                      border: `1px solid ${btDate === d ? "rgba(0,255,136,0.35)" : "rgba(255,255,255,0.09)"}`,
                      color: btDate === d ? "#00ff88" : "#475569",
                      borderRadius: 6, padding: "6px 12px", cursor: "pointer",
                      fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: 1,
                      transition: "all 0.15s",
                    }}>
                      {fmtShortDate(d)}
                    </button>
                  ))}
                </div>

                {/* Loading */}
                {btLoading && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 160, borderRadius: 12 }} />)}
                  </div>
                )}

                {/* Error */}
                {btError && !btLoading && (
                  <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 12, padding: "16px 20px", fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#fca5a5" }}>
                    ⚠ {btError}
                  </div>
                )}

                {/* Games */}
                {btGames && !btLoading && (
                  <>
                    {btGames.length === 0 ? (
                      <div style={{ textAlign: "center", padding: "40px 24px", fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#334155", letterSpacing: 2 }}>
                        NO REGULAR SEASON GAMES ON THIS DATE
                      </div>
                    ) : (
                      <>
                        {/* Results summary bar (post-reveal) */}
                        {summary && (
                          <div style={{
                            background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)",
                            borderRadius: 12, padding: "14px 20px", display: "flex", gap: 28, flexWrap: "wrap",
                            fontFamily: "'IBM Plex Mono', monospace",
                          }}>
                            {[
                              { label: "PICKED",  value: summary.total,   color: "#e2e8f0" },
                              { label: "CORRECT", value: summary.wins,    color: summary.wins   > 0 ? "#00ff88" : "#e2e8f0" },
                              { label: "WRONG",   value: summary.losses,  color: summary.losses > 0 ? "#ef4444" : "#e2e8f0" },
                              { label: "RATE",    value: (summary.wins + summary.losses) > 0 ? `${Math.round(summary.wins / (summary.wins + summary.losses) * 100)}%` : "—",
                                color: (summary.wins + summary.losses) > 0
                                  ? summary.wins / (summary.wins + summary.losses) >= 0.6 ? "#00ff88"
                                    : summary.wins / (summary.wins + summary.losses) >= 0.45 ? "#f59e0b" : "#ef4444"
                                  : "#475569" },
                            ].map(({ label, value, color }) => (
                              <div key={label}>
                                <div style={{ fontSize: 9, color: "#334155", letterSpacing: 2, marginBottom: 4 }}>{label}</div>
                                <div style={{ fontSize: 20, fontWeight: 600, color }}>{value}</div>
                              </div>
                            ))}
                            <div style={{ display: "flex", alignItems: "flex-end" }}>
                              <button onClick={() => { setBtGames(null); setBtDate(null); setBtPicks({}); setBtResults(null); }} style={{
                                background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
                                color: "#475569", borderRadius: 6, padding: "6px 14px", cursor: "pointer",
                                fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: 1.5,
                              }}>
                                NEW SESSION
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Game cards */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                          {btGames.map(g => (
                            <BacktestGameCard
                              key={g.game_id}
                              game={g}
                              picks={btPicks}
                              setPicks={setBtPicks}
                              scored={btResults?.scored}
                            />
                          ))}
                        </div>

                        {/* Reveal button — only shown before scoring */}
                        {!btResults && (
                          <button
                            onClick={scoreBtPicks}
                            disabled={pickCount === 0 || btScoring}
                            style={{
                              background: pickCount > 0 ? "rgba(0,255,136,0.10)" : "rgba(255,255,255,0.02)",
                              border: `1px solid ${pickCount > 0 ? "rgba(0,255,136,0.35)" : "rgba(255,255,255,0.07)"}`,
                              color: pickCount > 0 ? "#00ff88" : "#334155",
                              borderRadius: 8, padding: "14px 24px", cursor: pickCount > 0 ? "pointer" : "default",
                              fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, letterSpacing: 2,
                              width: "100%", transition: "all 0.2s",
                            }}
                          >
                            {btScoring
                              ? "FETCHING RESULTS..."
                              : pickCount > 0
                              ? `REVEAL RESULTS FOR ${pickCount} PICK${pickCount !== 1 ? "S" : ""}`
                              : "SELECT AT LEAST ONE GAME TO REVEAL"}
                          </button>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            )}

            {/* HISTORY sub-tab */}
            {btSubTab === "history" && (
              <BacktestHistoryPanel data={btHistData} loading={btHistLoad} error={btHistError} />
            )}

          </div>
        );
      })()}
    </div>
  );
}
