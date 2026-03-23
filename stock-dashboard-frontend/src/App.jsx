import { useState, useCallback, useEffect, useRef } from "react";
import NHLPredictor from "./components/NHLPredictor";
import {
  ComposedChart, Area, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid, Customized,
} from "recharts";

const API_BASE = "/api";
const WATCHLIST_KEY = "marketlens_watchlist";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";

function apiHeaders(extra = {}) {
  return API_TOKEN ? { "X-API-Token": API_TOKEN, ...extra } : { ...extra };
}

// ─── Utility ─────────────────────────────────────────────────────────────────

function formatPrice(n) {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(n);
}

function formatVolume(n) {
  if (n == null) return "—";
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + "B";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n;
}

function formatDate(dateStr, timeframe) {
  const d = new Date(dateStr);
  if (timeframe === "1d") return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  if (timeframe === "5d") return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  if (timeframe === "6m") return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  if (timeframe === "1y") return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function calcChange(data) {
  if (!data || data.length < 2) return null;
  const first = data[0].close;
  const last = data[data.length - 1].close;
  const pct = ((last - first) / first) * 100;
  return { pct, up: pct >= 0 };
}

// ─── Skeleton Loader ─────────────────────────────────────────────────────────

function SkeletonBar({ width = "100%", height = 14, style = {} }) {
  return <div className="skeleton" style={{ width, height, borderRadius: 4, ...style }} />;
}

function InfoCardSkeleton() {
  return (
    <div className="info-card">
      <div style={{ flex: 1 }}>
        <SkeletonBar width="55%" height={22} style={{ marginBottom: 10 }} />
        <SkeletonBar width="40%" height={12} />
      </div>
      <div style={{ textAlign: "right" }}>
        <SkeletonBar width={120} height={28} style={{ marginBottom: 8 }} />
        <SkeletonBar width={80} height={12} />
      </div>
    </div>
  );
}

function ChartSkeleton() {
  const bars = Array.from({ length: 48 }, (_, i) => ({
    h: 20 + Math.sin(i * 0.4) * 28 + ((i * 17) % 23),
    delay: i * 0.02,
  }));
  return (
    <div style={{ padding: "8px 8px 0", height: 320 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: "100%" }}>
        {bars.map((b, i) => (
          <div key={i} className="skeleton" style={{
            flex: 1, height: `${b.h}%`,
            borderRadius: "2px 2px 0 0",
            animationDelay: `${b.delay}s`,
          }} />
        ))}
      </div>
    </div>
  );
}

// ─── Error Banner ─────────────────────────────────────────────────────────────

function ErrorBanner({ message, onDismiss }) {
  return (
    <div className="error-banner">
      <span>⚠ {message}</span>
      <button className="error-dismiss" onClick={onDismiss}>✕</button>
    </div>
  );
}

// ─── Custom Tooltip ───────────────────────────────────────────────────────────

function CustomTooltip({ active, payload, label, timeframe }) {
  if (!active || !payload?.length) return null;
  const close = payload.find(p => p.dataKey === "close");
  const rawVol = payload[0]?.payload?.volume;
  return (
    <div style={{
      background: "rgba(10,14,20,0.97)",
      border: "1px solid rgba(0,255,136,0.25)",
      borderRadius: 8, padding: "10px 14px",
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 12, color: "#e2e8f0",
      boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
    }}>
      <div style={{ color: "#64748b", marginBottom: 6 }}>{formatDate(label, timeframe)}</div>
      {close && <div style={{ color: "#00ff88" }}>Close: {formatPrice(close.value)}</div>}
      {rawVol != null && <div style={{ color: "#3b82f6", marginTop: 4 }}>Vol: {formatVolume(rawVol)}</div>}
    </div>
  );
}

// ─── Volume at Price ──────────────────────────────────────────────────────────

const VAP_BINS = 40;
// Each bar is 4px tall with a 1px gap. Total track height for 40 bins:
// 40 * (4 + 1) - 1 = 199px. We pad the container to 320px to match chart height.
const BAR_HEIGHT = 4;
const BAR_GAP = 1;

function computeVAP(data) {
  if (!data || data.length === 0) return null;

  const closes = data.map(d => d.close);
  const minPrice = Math.min(...closes);
  const maxPrice = Math.max(...closes);
  const range = maxPrice - minPrice;

  // Avoid division by zero when all closes are identical
  const bucketSize = range === 0 ? 1 : range / VAP_BINS;

  const buckets = Array.from({ length: VAP_BINS }, () => ({ volume: 0, priceLevel: 0 }));

  // Label each bucket by its midpoint price
  for (let i = 0; i < VAP_BINS; i++) {
    buckets[i].priceLevel = minPrice + (i + 0.5) * bucketSize;
  }

  // Accumulate volume into the bucket that contains each bar's close
  for (const bar of data) {
    if (bar.volume == null || bar.close == null) continue;
    let idx = range === 0 ? 0 : Math.floor((bar.close - minPrice) / bucketSize);
    // Clamp: the highest close maps to index VAP_BINS, pull it back
    if (idx >= VAP_BINS) idx = VAP_BINS - 1;
    buckets[idx].volume += bar.volume;
  }

  const maxVol = Math.max(...buckets.map(b => b.volume));

  return { buckets, maxVol, minPrice, maxPrice };
}

function VolumeAtPrice({ data }) {
  if (!data || data.length === 0) return null;

  const vap = computeVAP(data);
  if (!vap) return null;

  const { buckets, maxVol } = vap;
  const orderedBuckets = [...buckets].reverse();

  return (
    <div style={{
      position: "absolute",
      top: 10,       // match Recharts top margin
      bottom: 30,    // leave room for x-axis
      right: 16,     // match Recharts right margin
      width: 80,
      display: "flex",
      flexDirection: "column",
      justifyContent: "space-between",
      pointerEvents: "none",
    }}>
      {orderedBuckets.map((bucket, i) => {
        const isMax = bucket.volume === maxVol && maxVol > 0;
        const widthPct = maxVol === 0 ? 0 : (bucket.volume / maxVol) * 100;
        const barColor = isMax ? "rgba(59,130,246,0.9)" : "rgba(59,130,246,0.45)";

        return (
          <div
            key={i}
            title={`$${bucket.priceLevel.toFixed(2)} — Vol: ${formatVolume(bucket.volume)}`}
            style={{
              height: BAR_HEIGHT,
              flexShrink: 0,
              position: "relative",
              overflow: "hidden",
            }}
          >
            {/* bar grows from RIGHT to LEFT */}
            <div style={{
              position: "absolute",
              right: 0,
              top: 0,
              height: "100%",
              width: `${widthPct}%`,
              background: barColor,
              borderRadius: "1px 0 0 1px",
              transition: "width 0.3s ease",
            }} />
          </div>
        );
      })}
    </div>
  );
}

// ─── Candlestick Series (via Customized) ─────────────────────────────────────

function CandlestickSeries({ data, xAxisMap, yAxisMap }) {
  if (!data || !xAxisMap || !yAxisMap) return null;

  const xAxis = Object.values(xAxisMap)[0];
  const yAxis = Object.values(yAxisMap)[0];
  if (!xAxis?.scale || !yAxis?.scale) return null;

  const xScale = xAxis.scale;
  const yScale = yAxis.scale;
  const bandwidth = xScale.bandwidth ? xScale.bandwidth() : 10;

  return (
    <g>
      {data.map((d, i) => {
        if (d.open == null || d.high == null || d.low == null || d.close == null) return null;

        const x = xScale(d.date);
        if (x == null || isNaN(x)) return null;

        const { open, high, low, close } = d;
        const isUp = close >= open;
        const color = isUp ? "#00ff88" : "#ef4444";

        const bodyTop = yScale(Math.max(open, close));
        const bodyBottom = yScale(Math.min(open, close));
        const bodyHeight = Math.max(1, bodyBottom - bodyTop);
        const candleWidth = Math.max(3, bandwidth * 0.7);
        const candleX = x + (bandwidth - candleWidth) / 2;
        const wickX = x + bandwidth / 2;
        const highY = yScale(high);
        const lowY = yScale(low);

        return (
          <g key={i}>
            <line x1={wickX} y1={highY} x2={wickX} y2={bodyTop} stroke={color} strokeWidth={1} />
            <line x1={wickX} y1={bodyBottom} x2={wickX} y2={lowY} stroke={color} strokeWidth={1} />
            <rect
              x={candleX}
              y={bodyTop}
              width={candleWidth}
              height={bodyHeight}
              fill={color}
              fillOpacity={0.85}
              stroke={color}
              strokeWidth={0.5}
            />
          </g>
        );
      })}
    </g>
  );
}

// ─── Dividend Markers ─────────────────────────────────────────────────────────

function DividendMarkers({ dividends, data, xAxisMap, yAxisMap }) {
  if (!dividends?.length || !data?.length || !xAxisMap || !yAxisMap) return null;

  const xAxis = Object.values(xAxisMap)[0];
  const yAxis = Object.values(yAxisMap)[0];
  if (!xAxis?.scale || !yAxis) return null;

  const xScale    = xAxis.scale;
  const bandwidth = xScale.bandwidth ? xScale.bandwidth() : 0;
  const chartBottom = yAxis.y + yAxis.height;

  const markers = [];
  for (const div of dividends) {
    const divTime = new Date(div.date).getTime();
    let bestIdx = -1, bestDiff = Infinity;
    for (let i = 0; i < data.length; i++) {
      const diff = Math.abs(new Date(data[i].date).getTime() - divTime);
      if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    }
    // Skip if no chart data point within 21 days (weekends, holidays, out of range)
    if (bestIdx < 0 || bestDiff > 21 * 24 * 60 * 60 * 1000) continue;
    const x = xScale(data[bestIdx].date);
    if (x == null || isNaN(x)) continue;
    markers.push({ x: x + bandwidth / 2, amount: div.amount });
  }

  return (
    <g>
      {markers.map((m, i) => (
        <g key={i}>
          <line x1={m.x} y1={chartBottom - 14} x2={m.x} y2={chartBottom - 2}
            stroke="#f59e0b" strokeWidth={1.5} />
          <text x={m.x} y={chartBottom - 17} textAnchor="middle"
            fill="#f59e0b" fontSize={7} fontFamily="'IBM Plex Mono', monospace">
            ${m.amount.toFixed(2)}
          </text>
        </g>
      ))}
    </g>
  );
}

// ─── Chart Panel ─────────────────────────────────────────────────────────────

function ChartPanel({ data, timeframe, ticker, loading, error, chartType, drawMode, drawTool, drawColor, lines, onAddLine, dividends }) {
  const svgRef = useRef(null);
  const [drawing, setDrawing] = useState(null);
  const [channelPhase, setChannelPhase] = useState(0); // 0=idle, 1=base drawn waiting for offset click
  const [channelBase, setChannelBase] = useState(null);

  useEffect(() => { setDrawing(null); setChannelPhase(0); setChannelBase(null); }, [data]);
  useEffect(() => { setDrawing(null); setChannelPhase(0); setChannelBase(null); }, [drawTool]);

  const getRelPos = (e) => {
    const rect = svgRef.current.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };
  const handleMouseDown = (e) => {
    if (!drawMode || !svgRef.current) return;
    const pos = getRelPos(e);
    if (drawTool === "hline") {
      onAddLine({ type: "hline", y: pos.y, color: drawColor });
      return;
    }
    if (drawTool === "channel" && channelPhase === 1) {
      const midY = (channelBase.y1 + channelBase.y2) / 2;
      onAddLine({ type: "channel", ...channelBase, offsetY: pos.y - midY, color: drawColor });
      setChannelPhase(0); setChannelBase(null); setDrawing(null);
      return;
    }
    setDrawing({ x1: pos.x, y1: pos.y, x2: pos.x, y2: pos.y });
  };
  const handleMouseMove = (e) => {
    if (!svgRef.current) return;
    const pos = getRelPos(e);
    if (drawTool === "channel" && channelPhase === 1) {
      setDrawing({ offsetPreviewY: pos.y });
      return;
    }
    if (!drawing) return;
    setDrawing(prev => ({ ...prev, x2: pos.x, y2: pos.y }));
  };
  const handleMouseUp = (e) => {
    if (!drawing || !svgRef.current || drawTool === "hline") return;
    if (drawTool === "channel" && channelPhase === 1) return;
    const pos = getRelPos(e);
    const dx = pos.x - drawing.x1;
    const dy = pos.y - drawing.y1;
    if (Math.sqrt(dx * dx + dy * dy) > 5) {
      if (drawTool === "channel") {
        setChannelBase({ x1: drawing.x1, y1: drawing.y1, x2: pos.x, y2: pos.y });
        setChannelPhase(1);
      } else {
        onAddLine({ type: drawTool || "line", x1: drawing.x1, y1: drawing.y1, x2: pos.x, y2: pos.y, color: drawColor });
      }
    }
    setDrawing(null);
  };

  if (loading) return <ChartSkeleton />;

  if (error) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 320, gap: 12 }}>
      <div style={{ fontSize: 32 }}>📭</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#ef4444" }}>{error}</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#334155" }}>CHECK TICKER OR TRY AGAIN</div>
    </div>
  );

  if (!data?.length) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 320, gap: 10 }}>
      <div style={{ fontSize: 36, opacity: 0.25 }}>📈</div>
      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, letterSpacing: 2, color: "#334155" }}>
        ENTER A TICKER TO BEGIN
      </span>
    </div>
  );

  const minPrice = chartType === "candle"
    ? Math.min(...data.map(d => Math.min(d.low ?? d.close, d.close)))
    : Math.min(...data.map(d => d.close));
  const maxPrice = chartType === "candle"
    ? Math.max(...data.map(d => Math.max(d.high ?? d.close, d.close)))
    : Math.max(...data.map(d => d.close));
  const padding = (maxPrice - minPrice) * 0.08 || 1;
  const maxVol = Math.max(...data.map(d => d.volume));

  const normalized = data.map(d => ({
    ...d,
    volumeScaled: (d.volume / maxVol) * (maxPrice - minPrice) * 0.28 + (minPrice - padding),
  }));

  const step = Math.max(1, Math.floor(data.length / 6));
  const ticks = data.filter((_, i) => i % step === 0).map(d => d.date);

  return (
    <div style={{ position: "relative", overflow: "hidden" }}>
      <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={normalized} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00ff88" stopOpacity={chartType === "candle" ? 0 : 0.18} />
                <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
            <XAxis dataKey="date" ticks={ticks} tickFormatter={d => formatDate(d, timeframe)}
              tick={{ fill: "#475569", fontSize: 11, fontFamily: "'IBM Plex Mono', monospace" }}
              axisLine={false} tickLine={false} />
            <YAxis domain={[minPrice - padding, maxPrice + padding]} tickFormatter={v => `$${v.toFixed(0)}`}
              tick={{ fill: "#475569", fontSize: 11, fontFamily: "'IBM Plex Mono', monospace" }}
              axisLine={false} tickLine={false} width={56} />
            <Tooltip content={<CustomTooltip timeframe={timeframe} />} />
            <Bar dataKey="volumeScaled" fill="rgba(59,130,246,0.22)" radius={[2, 2, 0, 0]} />
            {chartType === "candle" ? (
              <Customized component={<CandlestickSeries data={normalized} />} />
            ) : (
              <Area type="monotone" dataKey="close" stroke="#00ff88" strokeWidth={2}
                fill="url(#areaGrad)" dot={false}
                activeDot={{ r: 4, fill: "#00ff88", stroke: "#000" }} />
            )}
            {dividends?.length > 0 && timeframe !== "1d" && (
              <Customized component={<DividendMarkers dividends={dividends} data={normalized} />} />
            )}
          </ComposedChart>
      </ResponsiveContainer>
      <VolumeAtPrice data={data} />
      <svg
        ref={svgRef}
        style={{
          position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
          pointerEvents: drawMode ? "all" : "none",
          cursor: drawMode ? "crosshair" : "default",
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => { setDrawing(null); }}
      >
        {/* Committed annotations */}
        {(lines || []).map((ann, i) => {
          const c = ann.color || "#f59e0b";
          if (ann.type === "hline") {
            return <line key={i} x1={0} y1={ann.y} x2={9999} y2={ann.y}
              stroke={c} strokeWidth={1.5} opacity={0.85} />;
          }
          if (ann.type === "channel") {
            const o = ann.offsetY;
            return (
              <g key={i}>
                <polygon points={`${ann.x1},${ann.y1} ${ann.x2},${ann.y2} ${ann.x2},${ann.y2+o} ${ann.x1},${ann.y1+o}`}
                  fill={c} fillOpacity={0.08} />
                <line x1={ann.x1} y1={ann.y1} x2={ann.x2} y2={ann.y2} stroke={c} strokeWidth={1.5} strokeLinecap="round" opacity={0.85} />
                <line x1={ann.x1} y1={ann.y1+o} x2={ann.x2} y2={ann.y2+o} stroke={c} strokeWidth={1.5} strokeLinecap="round" opacity={0.85} />
              </g>
            );
          }
          if (ann.type === "fib") {
            const FIB = [
              { r: 0, label: "0%" }, { r: 0.236, label: "23.6%" }, { r: 0.382, label: "38.2%" },
              { r: 0.5, label: "50%" }, { r: 0.618, label: "61.8%" }, { r: 0.786, label: "78.6%" }, { r: 1, label: "100%" },
            ];
            const xMin = Math.min(ann.x1, ann.x2);
            const xMax = Math.max(ann.x1, ann.x2);
            return (
              <g key={i}>
                {FIB.map(({ r, label }, ri) => {
                  const y = ann.y1 + (ann.y2 - ann.y1) * r;
                  const edge = r === 0 || r === 1;
                  return (
                    <g key={ri}>
                      <line x1={xMin} y1={y} x2={xMax} y2={y} stroke={c}
                        strokeWidth={edge ? 1.5 : 1} opacity={edge ? 0.85 : 0.65}
                        strokeDasharray={edge ? undefined : "3 2"} />
                      <text x={xMin + 4} y={y - 3} fill={c} fontSize={9}
                        fontFamily="'IBM Plex Mono', monospace" opacity={0.8}>{label}</text>
                    </g>
                  );
                })}
              </g>
            );
          }
          // default: trendline (type="line" or legacy without type)
          return <line key={i} x1={ann.x1} y1={ann.y1} x2={ann.x2} y2={ann.y2}
            stroke={c} strokeWidth={1.5} strokeLinecap="round" opacity={0.85} />;
        })}

        {/* Active drag preview */}
        {drawing?.x1 != null && drawTool !== "fib" && (
          <line x1={drawing.x1} y1={drawing.y1} x2={drawing.x2} y2={drawing.y2}
            stroke={drawColor} strokeWidth={1.5} strokeLinecap="round" strokeDasharray="4 3" opacity={0.7} />
        )}
        {drawing?.x1 != null && drawTool === "fib" && (() => {
          const FIB_R = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
          const xMin = Math.min(drawing.x1, drawing.x2);
          const xMax = Math.max(drawing.x1, drawing.x2);
          return FIB_R.map((r, ri) => {
            const y = drawing.y1 + (drawing.y2 - drawing.y1) * r;
            return <line key={ri} x1={xMin} y1={y} x2={xMax} y2={y}
              stroke={drawColor} strokeWidth={1} opacity={0.5} strokeDasharray="3 2" />;
          });
        })()}

        {/* Channel phase 2: show base line + offset preview following mouse */}
        {drawTool === "channel" && channelPhase === 1 && channelBase && (() => {
          const o = drawing?.offsetPreviewY != null
            ? drawing.offsetPreviewY - (channelBase.y1 + channelBase.y2) / 2
            : 0;
          return (
            <g>
              <line x1={channelBase.x1} y1={channelBase.y1} x2={channelBase.x2} y2={channelBase.y2}
                stroke={drawColor} strokeWidth={1.5} strokeLinecap="round" opacity={0.85} />
              {drawing?.offsetPreviewY != null && <>
                <polygon points={`${channelBase.x1},${channelBase.y1} ${channelBase.x2},${channelBase.y2} ${channelBase.x2},${channelBase.y2+o} ${channelBase.x1},${channelBase.y1+o}`}
                  fill={drawColor} fillOpacity={0.06} />
                <line x1={channelBase.x1} y1={channelBase.y1+o} x2={channelBase.x2} y2={channelBase.y2+o}
                  stroke={drawColor} strokeWidth={1.5} strokeDasharray="4 3" opacity={0.7} />
              </>}
            </g>
          );
        })()}
      </svg>
    </div>
  );
}

// ─── Markets ──────────────────────────────────────────────────────────────────

const MARKETS = [
  { label: "INDICES", items: [
    { ticker: "^GSPC", label: "S&P 500" },
    { ticker: "^IXIC", label: "Nasdaq" },
    { ticker: "^DJI",  label: "Dow" },
    { ticker: "^RUT",  label: "Russell" },
    { ticker: "^FTSE", label: "FTSE 100" },
    { ticker: "^N225", label: "Nikkei" },
  ]},
  { label: "FUTURES", items: [
    { ticker: "ES=F", label: "S&P Fut" },
    { ticker: "NQ=F", label: "NQ Fut" },
    { ticker: "GC=F", label: "Gold" },
    { ticker: "CL=F", label: "Oil (WTI)" },
    { ticker: "SI=F", label: "Silver" },
    { ticker: "NG=F", label: "Nat Gas" },
  ]},
];

function Markets({ activeTicker, onSelect }) {
  return (
    <div>
      {MARKETS.map(group => (
        <div key={group.label}>
          <div style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 9,
            letterSpacing: "2.5px",
            color: "#334155",
            textTransform: "uppercase",
            margin: "12px 0 4px",
            padding: "0 4px",
          }}>
            {group.label}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {group.items.map(item => (
              <div
                key={item.ticker}
                className={`watchlist-item ${activeTicker === item.ticker ? "watchlist-item-active" : ""}`}
                onClick={() => onSelect(item.ticker)}
              >
                <div style={{ minWidth: 0 }}>
                  <div className="wl-ticker">{item.ticker}</div>
                  <div className="wl-name">{item.label}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      <div style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", marginBottom: 12, paddingBottom: 12, marginTop: 8 }} />
    </div>
  );
}

// ─── Watchlist ────────────────────────────────────────────────────────────────

function Watchlist({ watchlist, activeTicker, onSelect, onRemove }) {
  if (!watchlist.length) return (
    <div className="watchlist-empty">
      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#1e293b", letterSpacing: 1.5 }}>
        WATCHLIST EMPTY
      </span>
    </div>
  );
  return (
    <div className="watchlist">
      {watchlist.map(item => (
        <div key={item.ticker}
          className={`watchlist-item ${activeTicker === item.ticker ? "watchlist-item-active" : ""}`}
          onClick={() => onSelect(item.ticker)}
        >
          <div style={{ minWidth: 0 }}>
            <div className="wl-ticker">{item.ticker}</div>
            <div className="wl-name">{item.name}</div>
          </div>
          <button className="wl-remove" onClick={e => { e.stopPropagation(); onRemove(item.ticker); }} title="Remove">✕</button>
        </div>
      ))}
    </div>
  );
}

// ─── Fundamentals Card ────────────────────────────────────────────────────────

function FundamentalsCard({ data, loading }) {
  const [histOpen, setHistOpen] = useState(false);

  if (loading) return (
    <div style={{
      background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 12, padding: "14px 22px", display: "flex", gap: 32,
    }}>
      {[72, 72, 96, 96, 96, 96].map((w, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <SkeletonBar width={w} height={9} />
          <SkeletonBar width={w * 0.7} height={14} />
        </div>
      ))}
    </div>
  );

  if (!data) return null;

  const hasDividend = data.dividend_yield != null || data.dividend_rate != null;

  function Stat({ label, value, sub }) {
    return (
      <div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#334155", letterSpacing: 2, marginBottom: 5 }}>{label}</div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 15, fontWeight: 600, color: value ? "#e2e8f0" : "#1e293b" }}>{value ?? "—"}</div>
        {sub && <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", marginTop: 3 }}>{sub}</div>}
      </div>
    );
  }

  function fmtDate(str) {
    if (!str) return null;
    return new Date(str + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 12, padding: "14px 22px", display: "flex", flexDirection: "column", gap: 14,
      animation: "fadeIn 0.25s ease",
    }}>
      <div style={{ display: "flex", gap: 28, flexWrap: "wrap", alignItems: "flex-start" }}>

        {/* PE ratios */}
        <Stat label="TRAILING P/E" value={data.trailing_pe != null ? `${data.trailing_pe}x` : null} />
        <Stat label="FORWARD P/E"  value={data.forward_pe  != null ? `${data.forward_pe}x`  : null} />

        {hasDividend && (
          <div style={{ width: 1, background: "rgba(255,255,255,0.06)", alignSelf: "stretch", margin: "0 4px" }} />
        )}

        {/* Dividend stats */}
        {hasDividend && <>
          <Stat label="DIV YIELD"   value={data.dividend_yield != null ? `${data.dividend_yield}%` : null} />
          <Stat label="ANNUAL RATE" value={data.dividend_rate != null ? `$${data.dividend_rate}/sh` : null} />
          <Stat label="EX-DIV DATE" value={fmtDate(data.ex_dividend_date)} />
          <Stat
            label="LAST PAYMENT"
            value={data.last_dividend_value != null ? `$${data.last_dividend_value}` : null}
            sub={fmtDate(data.last_dividend_date)}
          />
        </>}
      </div>

      {/* Dividend history */}
      {hasDividend && data.dividend_history?.length > 0 && (
        <div>
          <button onClick={() => setHistOpen(o => !o)} style={{
            background: "none", border: "none", cursor: "pointer", padding: 0,
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569",
            letterSpacing: 1.5, display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{ fontSize: 8 }}>{histOpen ? "▾" : "▸"}</span>
            DIVIDEND HISTORY ({data.dividend_history.length} payments)
          </button>
          {histOpen && (
            <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {data.dividend_history.map((d, i) => (
                <div key={i} style={{
                  background: "rgba(0,0,0,0.3)", borderRadius: 6, padding: "6px 10px",
                  fontFamily: "'IBM Plex Mono', monospace", textAlign: "center",
                }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#00ff88" }}>${d.amount}</div>
                  <div style={{ fontSize: 9, color: "#334155", marginTop: 3 }}>
                    {new Date(d.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [activeTab, setActiveTab] = useState("stocks");
  const [query, setQuery] = useState("");
  const [ticker, setTicker] = useState(null);
  const [info, setInfo] = useState(null);
  const [chartData, setChartData] = useState({});
  const [timeframe, setTimeframe] = useState("6m");
  const [chartType, setChartType] = useState("line");
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [loadingChart, setLoadingChart] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [chartError, setChartError] = useState(null);
  const [watchlist, setWatchlist] = useState(() => {
    try { return JSON.parse(localStorage.getItem(WATCHLIST_KEY)) || []; }
    catch { return []; }
  });
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loadingSuggest, setLoadingSuggest] = useState(false);
  const [fundamentals, setFundamentals] = useState(null);
  const [loadingFundamentals, setLoadingFundamentals] = useState(false);
  const [drawMode, setDrawMode] = useState(false);
  const [drawTool, setDrawTool] = useState("line");
  const [drawColor, setDrawColor] = useState("#f59e0b");
  const [annotations, setAnnotations] = useState(() => {
    try { return JSON.parse(localStorage.getItem("marketlens_annotations")) || {}; }
    catch { return {}; }
  });

  // Sync localStorage cache whenever watchlist changes
  useEffect(() => {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlist));
  }, [watchlist]);

  useEffect(() => {
    localStorage.setItem("marketlens_annotations", JSON.stringify(annotations));
  }, [annotations]);

  // Load watchlist from backend on mount
  useEffect(() => {
    fetch(`${API_BASE}/watchlist`, { headers: apiHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(json => { if (json?.items?.length) setWatchlist(json.items); })
      .catch(() => { /* keep localStorage fallback */ });
  }, []);

  useEffect(() => {
    if (query.length < 2) { setSuggestions([]); setShowSuggestions(false); return; }
    const timer = setTimeout(async () => {
      setLoadingSuggest(true);
      try {
        const res = await fetch(`${API_BASE}/suggest/${encodeURIComponent(query)}`, { headers: apiHeaders() });
        if (res.ok) {
          const json = await res.json();
          setSuggestions(json.results || []);
          setShowSuggestions(true);
        }
      } catch { /* ignore */ }
      finally { setLoadingSuggest(false); }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const fetchChart = useCallback(async (sym, tf, cache) => {
    if (cache[sym]?.[tf]) return cache;
    setLoadingChart(true);
    setChartError(null);
    try {
      const res = await fetch(`${API_BASE}/chart/${encodeURIComponent(sym)}/${tf}`, { headers: apiHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `No chart data for ${sym} (${tf.toUpperCase()})`);
      }
      const json = await res.json();
      const updated = { ...cache, [sym]: { ...(cache[sym] || {}), [tf]: json.data } };
      setChartData(updated);
      return updated;
    } catch (e) {
      setChartError(e.message);
      return cache;
    } finally {
      setLoadingChart(false);
    }
  }, []);

  const loadTicker = useCallback(async (sym, existingCache = {}) => {
    setLoadingSearch(true);
    setSearchError(null);
    setInfo(null);
    setFundamentals(null);
    setLoadingFundamentals(true);
    try {
      const res = await fetch(`${API_BASE}/search/${encodeURIComponent(sym)}`, { headers: apiHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Ticker "${sym}" not found`);
      }
      const json = await res.json();
      setInfo(json);
      setTicker(sym);
      setTimeframe("6m");
      // Fetch fundamentals in parallel — don't block chart load
      fetch(`${API_BASE}/fundamentals/${encodeURIComponent(sym)}`, { headers: apiHeaders() })
        .then(r => r.ok ? r.json() : null)
        .then(f => setFundamentals(f))
        .catch(() => {})
        .finally(() => setLoadingFundamentals(false));
      await fetchChart(sym, "6m", existingCache);
    } catch (e) {
      setSearchError(e.message);
      setLoadingFundamentals(false);
    } finally {
      setLoadingSearch(false);
    }
  }, [fetchChart]);

  const handleSearch = async () => {
    const sym = query.trim().toUpperCase();
    if (!sym) return;
    setQuery("");
    setShowSuggestions(false);
    setSuggestions([]);
    await loadTicker(sym, chartData);
  };

  const handleSuggestionSelect = (sym) => {
    setQuery("");
    setSuggestions([]);
    setShowSuggestions(false);
    loadTicker(sym, chartData);
  };

  const handleTimeframe = async (tf) => {
    setTimeframe(tf);
    if (ticker) await fetchChart(ticker, tf, chartData);
  };

  const handleWatchlistSelect = async (sym) => {
    if (sym === ticker) return;
    await loadTicker(sym, chartData);
  };

  const handleAddToWatchlist = async () => {
    if (!info || watchlist.find(w => w.ticker === info.ticker)) return;
    const item = { ticker: info.ticker, name: info.name };
    setWatchlist(prev => [...prev, item]);
    try {
      await fetch(`${API_BASE}/watchlist`, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(item),
      });
    } catch { /* localStorage still updated above */ }
  };

  const handleRemoveFromWatchlist = async (sym) => {
    setWatchlist(prev => prev.filter(w => w.ticker !== sym));
    try {
      await fetch(`${API_BASE}/watchlist/${sym}`, { method: "DELETE", headers: apiHeaders() });
    } catch { /* localStorage still updated above */ }
  };

  const currentData = ticker ? (chartData[ticker]?.[timeframe] || []) : [];
  const change = calcChange(currentData);
  const inWatchlist = !!(info && watchlist.find(w => w.ticker === info.ticker));

  const annotationKey = ticker && timeframe ? `${ticker}_${timeframe}` : null;
  const currentLines = annotationKey ? (annotations[annotationKey] || []) : [];
  const handleAddLine = (line) => {
    if (!annotationKey) return;
    setAnnotations(prev => ({ ...prev, [annotationKey]: [...(prev[annotationKey] || []), line] }));
  };
  const handleClearLines = () => {
    if (!annotationKey) return;
    setAnnotations(prev => ({ ...prev, [annotationKey]: [] }));
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Syne:wght@400;600;700;800&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
          background: #050810; color: #e2e8f0; min-height: 100vh;
          font-family: 'Syne', sans-serif;
          background-image:
            radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0,255,136,0.07) 0%, transparent 60%),
            linear-gradient(180deg, #050810 0%, #080d18 100%);
        }
        .layout {
          display: grid; grid-template-columns: 210px 1fr; gap: 28px;
          max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px;
        }
        @media (max-width: 720px) { .layout { grid-template-columns: 1fr; } }
        .sidebar { display: flex; flex-direction: column; }
        .sidebar-header {
          font-family: 'IBM Plex Mono', monospace; font-size: 10px;
          letter-spacing: 2.5px; color: #334155; text-transform: uppercase;
          padding: 0 4px 10px; border-bottom: 1px solid rgba(255,255,255,0.05); margin-bottom: 8px;
        }
        .watchlist { display: flex; flex-direction: column; gap: 4px; }
        .watchlist-empty { padding: 24px 8px; text-align: center; }
        .watchlist-item {
          display: flex; align-items: center; justify-content: space-between;
          padding: 10px 12px; border-radius: 8px; border: 1px solid transparent;
          cursor: pointer; transition: all 0.15s;
        }
        .watchlist-item:hover { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.07); }
        .watchlist-item-active { background: rgba(0,255,136,0.07) !important; border-color: rgba(0,255,136,0.2) !important; }
        .wl-ticker { font-family: 'IBM Plex Mono', monospace; font-size: 13px; font-weight: 600; color: #e2e8f0; }
        .watchlist-item-active .wl-ticker { color: #00ff88; }
        .wl-name { font-size: 11px; color: #475569; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; }
        .wl-remove { background: none; border: none; color: #1e293b; cursor: pointer; font-size: 11px; padding: 2px 4px; border-radius: 3px; transition: color 0.15s; flex-shrink: 0; }
        .wl-remove:hover { color: #ef4444; }
        .main { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
        .header { border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 20px; }
        .logo { font-family: 'Syne', sans-serif; font-weight: 800; font-size: 22px; letter-spacing: -0.5px; color: #fff; }
        .logo span { color: #00ff88; }
        .tagline { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #334155; letter-spacing: 2px; margin-top: 4px; text-transform: uppercase; }
        .search-row { display: flex; gap: 10px; }
        .search-input {
          flex: 1; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
          border-radius: 8px; padding: 12px 18px; font-family: 'IBM Plex Mono', monospace;
          font-size: 15px; font-weight: 600; color: #fff; letter-spacing: 1px; outline: none;
          transition: border-color 0.2s, background 0.2s;
        }
        .search-input::placeholder { color: #334155; letter-spacing: 2px; font-size: 12px; font-weight: 400; }
        .search-input:focus { border-color: rgba(0,255,136,0.4); background: rgba(0,255,136,0.03); }
        .search-btn {
          background: #00ff88; color: #050810; border: none; border-radius: 8px;
          padding: 12px 20px; font-family: 'Syne', sans-serif; font-weight: 700;
          font-size: 13px; letter-spacing: 1px; cursor: pointer;
          transition: opacity 0.15s, transform 0.1s; white-space: nowrap;
        }
        .search-btn:hover { opacity: 0.88; }
        .search-btn:active { transform: scale(0.97); }
        .search-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .error-banner {
          display: flex; align-items: center; justify-content: space-between;
          background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.25);
          border-radius: 8px; padding: 10px 16px;
          font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #fca5a5;
          animation: slideIn 0.2s ease;
        }
        .error-dismiss { background: none; border: none; color: #ef4444; cursor: pointer; font-size: 13px; padding: 2px 6px; border-radius: 4px; transition: background 0.15s; }
        .error-dismiss:hover { background: rgba(239,68,68,0.15); }
        .info-card {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
          border-radius: 12px; padding: 18px 22px;
          display: flex; align-items: flex-start; justify-content: space-between;
          gap: 24px; flex-wrap: wrap; animation: fadeIn 0.25s ease;
        }
        .company-name { font-size: 19px; font-weight: 700; color: #fff; margin-bottom: 4px; }
        .company-meta { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #475569; letter-spacing: 1px; }
        .info-right { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
        .current-price { font-family: 'IBM Plex Mono', monospace; font-size: 26px; font-weight: 600; color: #fff; }
        .price-change { font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
        .up { color: #00ff88; } .down { color: #ef4444; }
        .add-btn {
          background: rgba(0,255,136,0.1); border: 1px solid rgba(0,255,136,0.2);
          color: #00ff88; border-radius: 6px; padding: 5px 12px;
          font-family: 'IBM Plex Mono', monospace; font-size: 11px;
          cursor: pointer; letter-spacing: 1px; transition: all 0.15s;
        }
        .add-btn:hover { background: rgba(0,255,136,0.18); }
        .add-btn.in-watchlist { background: transparent; border-color: rgba(255,255,255,0.1); color: #475569; cursor: default; }
        .chart-card {
          background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07);
          border-radius: 12px; padding: 20px 16px 12px;
        }
        .chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; padding: 0 8px; }
        .chart-title { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #475569; letter-spacing: 2px; text-transform: uppercase; }
        .tf-group { display: flex; gap: 4px; background: rgba(0,0,0,0.3); border-radius: 6px; padding: 3px; }
        .tf-btn { background: none; border: none; border-radius: 4px; padding: 5px 14px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 500; color: #475569; cursor: pointer; transition: all 0.15s; letter-spacing: 1px; }
        .tf-btn:hover { color: #94a3b8; }
        .tf-btn.active { background: rgba(0,255,136,0.12); color: #00ff88; }
        .tf-btn:disabled { opacity: 0.3; cursor: not-allowed; }
        .legend { display: flex; gap: 20px; padding: 12px 8px 0; border-top: 1px solid rgba(255,255,255,0.04); margin-top: 8px; }
        .legend-item { display: flex; align-items: center; gap: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #475569; }
        .legend-dot { width: 8px; height: 8px; border-radius: 2px; }
        @keyframes shimmer { 0% { background-position: -400px 0; } 100% { background-position: 400px 0; } }
        .skeleton {
          background: linear-gradient(90deg, #0f172a 25%, #1e293b 50%, #0f172a 75%);
          background-size: 800px 100%; animation: shimmer 1.4s infinite linear;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        @keyframes slideIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
        @media (max-width: 600px) { .info-card { flex-direction: column; } .info-right { align-items: flex-start; } }
        .suggestions-dropdown {
          position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
          background: #0d1117; border: 1px solid rgba(0,255,136,0.2);
          border-top: none; border-radius: 0 0 8px 8px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.6); overflow: hidden;
        }
        .suggestion-item {
          display: flex; align-items: center; gap: 12px;
          padding: 10px 18px; cursor: pointer; transition: background 0.1s;
          border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .suggestion-item:last-child { border-bottom: none; }
        .suggestion-item:hover { background: rgba(0,255,136,0.06); }
        .suggestion-ticker {
          font-family: 'IBM Plex Mono', monospace; font-size: 13px;
          font-weight: 600; color: #00ff88; min-width: 70px;
        }
        .suggestion-name {
          font-family: 'IBM Plex Mono', monospace; font-size: 12px;
          color: #94a3b8; flex: 1;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .suggestion-meta {
          font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #334155; white-space: nowrap;
        }
      `}</style>

      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-header">Markets</div>
          <Markets activeTicker={ticker} onSelect={handleWatchlistSelect} />
          <div className="sidebar-header" style={{ marginTop: 16 }}>Watchlist</div>
          <Watchlist
            watchlist={watchlist}
            activeTicker={ticker}
            onSelect={handleWatchlistSelect}
            onRemove={handleRemoveFromWatchlist}
          />
        </aside>

        <div className="main">
          <div className="header">
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
              <div>
                <div className="logo">MARKET<span>LENS</span></div>
                <div className="tagline">Personal Stock Research Dashboard</div>
              </div>
              <div className="tf-group">
                <button className={`tf-btn ${activeTab === "stocks" ? "active" : ""}`} onClick={() => setActiveTab("stocks")}>📈 STOCKS</button>
                <button className={`tf-btn ${activeTab === "nhl" ? "active" : ""}`} onClick={() => setActiveTab("nhl")}>🏒 ICE EDGE</button>
              </div>
            </div>
          </div>

          {activeTab === "nhl" && <NHLPredictor />}

          {activeTab === "stocks" && <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>

          <div style={{ position: "relative" }}>
            <div className="search-row">
              <input
                className="search-input"
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleSearch()}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                placeholder="TICKER OR COMPANY NAME…"
                maxLength={50}
              />
              <button className="search-btn" onClick={handleSearch} disabled={loadingSearch || !query.trim()}>
                {loadingSearch ? "LOADING…" : "SEARCH →"}
              </button>
            </div>
            {showSuggestions && suggestions.length > 0 && (
              <div className="suggestions-dropdown">
                {suggestions.map(s => (
                  <div key={s.ticker} className="suggestion-item" onMouseDown={() => handleSuggestionSelect(s.ticker)}>
                    <span className="suggestion-ticker">{s.ticker}</span>
                    <span className="suggestion-name">{s.name}</span>
                    <span className="suggestion-meta">{s.exchange}{s.type ? ` · ${s.type}` : ""}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {searchError && <ErrorBanner message={searchError} onDismiss={() => setSearchError(null)} />}

          {loadingSearch ? <InfoCardSkeleton /> : info ? (
            <div className="info-card">
              <div>
                <div className="company-name">{info.name}</div>
                <div className="company-meta">
                  {info.ticker} · {info.exchange} · {info.sector !== "N/A" ? info.sector : info.industry}
                </div>
              </div>
              <div className="info-right">
                {currentData.length > 0 && (
                  <>
                    <div className="current-price">{formatPrice(currentData[currentData.length - 1]?.close)}</div>
                    {change && (
                      <div className={`price-change ${change.up ? "up" : "down"}`}>
                        {change.up ? "▲" : "▼"} {Math.abs(change.pct).toFixed(2)}% ({timeframe.toUpperCase()})
                      </div>
                    )}
                  </>
                )}
                <button className={`add-btn ${inWatchlist ? "in-watchlist" : ""}`} onClick={handleAddToWatchlist} disabled={inWatchlist}>
                  {inWatchlist ? "✓ IN WATCHLIST" : "+ ADD TO WATCHLIST"}
                </button>
              </div>
            </div>
          ) : null}

          {(loadingFundamentals || fundamentals) && (
            <FundamentalsCard data={fundamentals} loading={loadingFundamentals} />
          )}

          <div className="chart-card">
            <div className="chart-header">
              <div className="chart-title">{ticker ? `${ticker} — PRICE + VOLUME` : "PRICE + VOLUME"}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div className="tf-group" style={{ marginRight: 8 }}>
                  <button className={`tf-btn ${chartType === "line" ? "active" : ""}`} onClick={() => setChartType("line")}>LINE</button>
                  <button className={`tf-btn ${chartType === "candle" ? "active" : ""}`} onClick={() => setChartType("candle")}>CANDLE</button>
                </div>
                <div className="tf-group">
                  {["1d", "5d", "6m", "1y"].map(tf => (
                    <button key={tf} className={`tf-btn ${timeframe === tf ? "active" : ""}`}
                      onClick={() => handleTimeframe(tf)} disabled={!ticker || loadingChart}>
                      {tf.toUpperCase()}
                    </button>
                  ))}
                </div>
                <div className="tf-group">
                  <button
                    className={`tf-btn ${drawMode ? "active" : ""}`}
                    onClick={() => setDrawMode(v => !v)}
                    title={drawMode ? "Exit draw mode" : "Draw trendlines"}
                    disabled={!ticker}
                  >DRAW</button>
                  {currentLines.length > 0 && (
                    <button className="tf-btn" onClick={handleClearLines} title="Clear all lines">CLEAR</button>
                  )}
                </div>
              </div>
            </div>

            {drawMode && (
              <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 8px 16px", flexWrap: "wrap" }}>
                <div className="tf-group">
                  {[{ id: "line", label: "LINE" }, { id: "hline", label: "HLINE" }, { id: "channel", label: "CHANNEL" }, { id: "fib", label: "FIB" }].map(t => (
                    <button key={t.id} className={`tf-btn ${drawTool === t.id ? "active" : ""}`} onClick={() => setDrawTool(t.id)}>{t.label}</button>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {["#f59e0b", "#ef4444", "#00ff88", "#3b82f6", "#a855f7", "#ffffff"].map(c => (
                    <button key={c} onClick={() => setDrawColor(c)} title={c} style={{
                      width: 14, height: 14, borderRadius: "50%", background: c, padding: 0,
                      border: drawColor === c ? "2px solid rgba(255,255,255,0.9)" : "2px solid rgba(255,255,255,0.15)",
                      cursor: "pointer", flexShrink: 0,
                    }} />
                  ))}
                </div>
                {drawTool === "channel" && (
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", letterSpacing: 1 }}>
                    DRAG BASE LINE → CLICK TO SET WIDTH
                  </span>
                )}
                {drawTool === "fib" && (
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", letterSpacing: 1 }}>
                    DRAG HIGH → LOW
                  </span>
                )}
                {drawTool === "hline" && (
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#475569", letterSpacing: 1 }}>
                    CLICK TO PLACE
                  </span>
                )}
              </div>
            )}

            <ChartPanel data={currentData} timeframe={timeframe} ticker={ticker} loading={loadingChart} error={chartError} chartType={chartType} drawMode={drawMode} drawTool={drawTool} drawColor={drawColor} lines={currentLines} onAddLine={handleAddLine} dividends={fundamentals?.dividend_history} />

            {chartError && (
              <div style={{ padding: "0 8px 8px" }}>
                <ErrorBanner message={chartError} onDismiss={() => setChartError(null)} />
              </div>
            )}

            <div className="legend">
              {chartType === "candle" ? (
                <>
                  <div className="legend-item"><div className="legend-dot" style={{ background: "#00ff88" }} />Up Candle</div>
                  <div className="legend-item"><div className="legend-dot" style={{ background: "#ef4444" }} />Down Candle</div>
                </>
              ) : (
                <div className="legend-item"><div className="legend-dot" style={{ background: "#00ff88" }} />Close Price</div>
              )}
              <div className="legend-item"><div className="legend-dot" style={{ background: "rgba(59,130,246,0.5)" }} />Volume Overlay</div>
              <div className="legend-item"><div className="legend-dot" style={{ background: "rgba(59,130,246,0.5)", width: 4, height: 8 }} />Vol/Price</div>
              {currentLines.length > 0 && (
                <div className="legend-item"><div className="legend-dot" style={{ background: "#f59e0b", height: 2, borderRadius: 1 }} />Trendlines ({currentLines.length})</div>
              )}
            </div>
          </div>
          </div>} {/* end stocks tab */}

        </div>
      </div>
    </>
  );
}
