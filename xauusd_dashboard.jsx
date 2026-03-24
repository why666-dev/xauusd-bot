import { useState, useEffect, useRef, useCallback } from "react";
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts";

// ── MOCK DATA ─────────────────────────────────────────────────────────────────
const makeMock = (tick) => {
  const price = 3045 + Math.sin(tick * 0.07) * 18;
  const s1pnl = tick * 3.2, s2pnl = tick * 7.1, s3pnl = tick * 5.4;
  return {
    account: { equity: 51000 + (s1pnl+s2pnl+s3pnl), balance: 51000, pnl_today: s1pnl+s2pnl+s3pnl, available: 45000 },
    price:   { bid: +(price-0.15).toFixed(2), ask: +(price+0.15).toFixed(2), mid: +price.toFixed(2), spread: 0.30 },
    overall: { total_trades: Math.floor(tick/3), total_wins: Math.floor(tick/4), total_losses: Math.floor(tick/12),
               hit_ratio: 74.2, net_pnl: +(s1pnl+s2pnl+s3pnl).toFixed(2), daily_trades: Math.floor(tick/8),
               daily_pnl: +(s1pnl+s2pnl+s3pnl).toFixed(2), daily_halted: false },
    strategies: {
      S1_Asian_Breakout: { name:"S1_Asian_Breakout", trades: Math.floor(tick/5), wins: Math.floor(tick/9),
        losses: Math.floor(tick/20), hit_ratio: 52.4, net_pnl: +s1pnl.toFixed(2),
        gain_loss_ratio: 2.1, max_win: 142.50, max_loss: -68.20, trade_history: [] },
      S2_Goldmine: { name:"S2_Goldmine", trades: Math.floor(tick/4), wins: Math.floor(tick/5),
        losses: Math.floor(tick/22), hit_ratio: 82.1, net_pnl: +s2pnl.toFixed(2),
        gain_loss_ratio: 1.9, max_win: 198.00, max_loss: -52.40, trade_history: [] },
      S3_Silver_Bullet: { name:"S3_Silver_Bullet", trades: Math.floor(tick/6), wins: Math.floor(tick/8),
        losses: Math.floor(tick/25), hit_ratio: 78.6, net_pnl: +s3pnl.toFixed(2),
        gain_loss_ratio: 2.3, max_win: 215.00, max_loss: -44.80, trade_history: [] },
    },
    open_trade: tick % 20 > 10 ? {
      strategy: "S2_Goldmine", direction: "BUY", entry: 3042.50,
      sl: 3035.20, tp1: 3053.75, tp2: 3065.00,
      size: 0.5, open_time: new Date(Date.now()-3600000).toISOString(), tp1_hit: false,
    } : null,
    news_events: [
      { time: "14:30", event: "US CPI Data", impact: "HIGH" },
    ],
    timestamp: new Date().toISOString(),
  };
};

// ── HOOK ──────────────────────────────────────────────────────────────────────
function useBot() {
  const [state, setState]         = useState(null);
  const [chart, setChart]         = useState([]);
  const [connected, setConnected] = useState(false);
  const tick = useRef(0);

  const push = useCallback((s) => {
    setState(s);
    const ts = new Date().toLocaleTimeString("en-IN", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
    setChart(prev => [...prev, { t: ts, price: s.price?.mid, gold: s.price?.mid }].slice(-80));
  }, []);

  useEffect(() => {
    let ws;
    try {
      ws = new WebSocket("ws://localhost:5051/ws");
      ws.onopen    = () => setConnected(true);
      ws.onclose   = () => setConnected(false);
      ws.onerror   = () => {};
      ws.onmessage = (e) => { try { push(JSON.parse(e.data)); } catch(_){} };
    } catch(_) {}
    const iv = setInterval(() => { tick.current++; push(makeMock(tick.current)); setConnected(true); }, 2000);
    return () => { clearInterval(iv); ws?.close(); };
  }, [push]);

  return { state, chart, connected };
}

// ── UTILS ─────────────────────────────────────────────────────────────────────
const f2  = (n) => n == null ? "—" : (+n).toFixed(2);
const fM  = (n, s=false) => {
  if (n == null) return "—";
  const a = Math.abs(+n).toLocaleString("en-US", { minimumFractionDigits: 2 });
  return s ? ((+n >= 0 ? "+$" : "-$") + a) : "$" + a;
};
const fN  = (n) => n == null ? "—" : (+n).toLocaleString();
const fP  = (n) => n == null ? "—" : `${(+n).toFixed(1)}%`;

const GOLD   = "#FFB800";
const GREEN  = "#00E676";
const RED    = "#FF3D5A";
const BLUE   = "#4D9EFF";
const PURPLE = "#B388FF";
const BG     = "#060B14";
const CARD   = "#0C1420";
const ALT    = "#121E2E";
const BORDER = "#1E3048";
const TEXT   = "#E8F0FF";
const DIM    = "#5A7090";

const MONO = { fontFamily: "'JetBrains Mono', 'Fira Code', monospace" };
const MK   = { background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8 };
const TTS  = { background: CARD, border: `1px solid ${BORDER}`, borderRadius: 6, color: TEXT, fontSize: 11, ...MONO };

const STRAT_INFO = {
  S1_Asian_Breakout: { label: "ASIAN BREAKOUT", short: "S1", color: GOLD,   target: "55%",  tf: "1H + 15M" },
  S2_Goldmine:       { label: "GOLDMINE",        short: "S2", color: GREEN,  target: "82%",  tf: "15M" },
  S3_Silver_Bullet:  { label: "SILVER BULLET",   short: "S3", color: PURPLE, target: "78%",  tf: "1M + 5M" },
};

// ── COMPONENTS ────────────────────────────────────────────────────────────────
function GoldDot({ on }) {
  return (
    <span style={{ display:"inline-flex", alignItems:"center", gap:6 }}>
      <span style={{ width:8, height:8, borderRadius:"50%", display:"inline-block",
        background: on ? GREEN : RED, boxShadow: `0 0 10px ${on ? GREEN : RED}`,
        animation: on ? "pulse 2s infinite" : "none" }} />
      <span style={{ fontSize:10, letterSpacing:2, color: on ? GREEN : RED, ...MONO }}>
        {on ? "LIVE" : "OFFLINE"}
      </span>
    </span>
  );
}

function PnL({ v, size=15 }) {
  return <span style={{ color:(+v)>=0?GREEN:RED, fontWeight:700, fontSize:size, ...MONO }}>{fM(v,true)}</span>;
}

function StatBox({ label, children, accent=GOLD }) {
  return (
    <div style={{ background: ALT, borderRadius:6, padding:"10px 14px", borderLeft:`2px solid ${accent}30` }}>
      <div style={{ fontSize:9, color:DIM, letterSpacing:2, marginBottom:5 }}>{label}</div>
      {children}
    </div>
  );
}

function HitRing({ pct, color=GOLD, size=60 }) {
  const r = 22, c = 2*Math.PI*r, p = (pct||0)/100;
  return (
    <div style={{ position:"relative", width:size, height:size }}>
      <svg width={size} height={size} style={{ transform:"rotate(-90deg)" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={BORDER} strokeWidth={4}/>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={`${c*p} ${c}`} strokeLinecap="round"/>
      </svg>
      <div style={{ position:"absolute", inset:0, display:"flex", alignItems:"center",
        justifyContent:"center", fontSize:11, fontWeight:700, color, ...MONO }}>
        {(pct||0).toFixed(0)}%
      </div>
    </div>
  );
}

function StrategyCard({ name, data }) {
  if (!data) return null;
  const info = STRAT_INFO[name] || {};
  const col  = info.color || GOLD;
  const isGood = (data.hit_ratio || 0) >= parseFloat(info.target);

  return (
    <div style={{ ...MK, borderTop:`2px solid ${col}`, padding:"18px 20px", flex:1, minWidth:0 }}>
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:14 }}>
        <div>
          <div style={{ fontSize:11, color:col, fontWeight:700, letterSpacing:3, ...MONO }}>{info.label}</div>
          <div style={{ fontSize:9, color:DIM, marginTop:3, letterSpacing:1 }}>Timeframe: {info.tf}</div>
        </div>
        <div style={{ background:`${col}15`, border:`1px solid ${col}30`,
          padding:"3px 10px", borderRadius:4, fontSize:10, color:col, fontWeight:700, letterSpacing:2, ...MONO }}>
          {info.short}
        </div>
      </div>

      {/* Hit ratio + P&L */}
      <div style={{ display:"flex", gap:16, alignItems:"center", marginBottom:14 }}>
        <HitRing pct={data.hit_ratio} color={col} size={62} />
        <div>
          <div style={{ fontSize:9, color:DIM, letterSpacing:2, marginBottom:4 }}>NET P&L</div>
          <PnL v={data.net_pnl} size={18} />
          <div style={{ fontSize:9, color:DIM, marginTop:4 }}>
            Target: <span style={{ color:col }}>{info.target}</span>
            {" "}— <span style={{ color: isGood ? GREEN : RED }}>
              {isGood ? "ON TRACK ✓" : "BELOW TARGET"}
            </span>
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
        <StatBox label="TRADES" accent={col}>
          <div style={{ fontSize:16, fontWeight:700, color:TEXT, ...MONO }}>{data.trades || 0}</div>
        </StatBox>
        <StatBox label="GAIN:LOSS" accent={col}>
          <div style={{ fontSize:16, fontWeight:700, color:col, ...MONO }}>{(data.gain_loss_ratio||0).toFixed(1)}×</div>
        </StatBox>
        <StatBox label="MAX WIN" accent={GREEN}>
          <div style={{ fontSize:13, fontWeight:700, color:GREEN, ...MONO }}>{fM(data.max_win)}</div>
        </StatBox>
        <StatBox label="MAX LOSS" accent={RED}>
          <div style={{ fontSize:13, fontWeight:700, color:RED, ...MONO }}>{fM(data.max_loss)}</div>
        </StatBox>
      </div>
    </div>
  );
}

function OpenTrade({ t, price }) {
  if (!t) return (
    <div style={{ ...MK, padding:"16px 20px", marginBottom:14, borderLeft:`2px solid ${BORDER}` }}>
      <div style={{ fontSize:10, color:DIM, letterSpacing:3 }}>OPEN POSITION</div>
      <div style={{ fontSize:12, color:DIM, marginTop:8, textAlign:"center", padding:10 }}>
        No open position — waiting for signal
      </div>
    </div>
  );

  const info     = STRAT_INFO[t.strategy] || {};
  const col      = info.color || GOLD;
  const dir      = t.direction;
  const dcol     = dir === "BUY" ? GREEN : RED;
  const mid      = price?.mid || t.entry;
  const unreal   = dir === "BUY" ? (mid - t.entry) * t.size * 100 : (t.entry - mid) * t.size * 100;
  const stopDist = Math.abs(t.entry - t.sl);
  const pnlDist  = Math.abs(mid - t.entry);
  const rr       = stopDist > 0 ? (pnlDist / stopDist).toFixed(2) : "0";
  const pct      = Math.min(Math.abs(mid - t.entry) / stopDist * 100, 100);

  return (
    <div style={{ ...MK, padding:"16px 20px", marginBottom:14, borderLeft:`2px solid ${col}` }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:12 }}>
        <div style={{ fontSize:10, color:DIM, letterSpacing:3 }}>OPEN POSITION</div>
        <div style={{ display:"flex", gap:8 }}>
          <span style={{ background:`${col}20`, color:col, border:`1px solid ${col}30`,
            padding:"2px 10px", borderRadius:3, fontSize:10, fontWeight:700, letterSpacing:2, ...MONO }}>
            {info.short}
          </span>
          <span style={{ background:`${dcol}20`, color:dcol, border:`1px solid ${dcol}30`,
            padding:"2px 10px", borderRadius:3, fontSize:10, fontWeight:700, letterSpacing:2, ...MONO }}>
            {dir}
          </span>
        </div>
      </div>
      <div style={{ display:"flex", gap:20, flexWrap:"wrap" }}>
        {[["ENTRY", `$${f2(t.entry)}`, TEXT], ["CURRENT", `$${f2(mid)}`, dcol],
          ["SL", `$${f2(t.sl)}`, RED], ["TP1", `$${f2(t.tp1)}`, GREEN],
          ["TP2", `$${f2(t.tp2)}`, GREEN], ["SIZE", `${t.size}oz`, TEXT],
          ["UNREALIZED", null, null, unreal], ["R:R NOW", `${rr}×`, col]
        ].map(([l, v, c, pnlV], i) => (
          <div key={i}>
            <div style={{ fontSize:9, color:DIM, letterSpacing:2, marginBottom:3 }}>{l}</div>
            {pnlV !== undefined
              ? <PnL v={pnlV} size={14} />
              : <div style={{ fontSize:14, fontWeight:700, color:c, ...MONO }}>{v}</div>
            }
          </div>
        ))}
      </div>
      {/* Progress bar to TP */}
      <div style={{ marginTop:10 }}>
        <div style={{ height:3, background:BORDER, borderRadius:2 }}>
          <div style={{ height:"100%", width:`${pct}%`, background:dcol,
            borderRadius:2, transition:"all 1s ease" }} />
        </div>
        <div style={{ display:"flex", justifyContent:"space-between",
          fontSize:9, color:DIM, marginTop:3 }}>
          <span>Entry</span><span>TP2</span>
        </div>
      </div>
    </div>
  );
}

function NewsAlert({ events }) {
  if (!events || !events.length) return null;
  return (
    <div style={{ background:"#1A0A08", border:`1px solid ${RED}40`,
      borderRadius:8, padding:"10px 16px", marginBottom:14,
      display:"flex", alignItems:"center", gap:12 }}>
      <span style={{ fontSize:16 }}>⚠️</span>
      <div>
        <div style={{ fontSize:10, color:RED, fontWeight:700, letterSpacing:2 }}>HIGH IMPACT NEWS TODAY</div>
        {events.map((e, i) => (
          <div key={i} style={{ fontSize:11, color:DIM, marginTop:2, ...MONO }}>
            {e.time} ET — {e.event}
          </div>
        ))}
      </div>
      <div style={{ marginLeft:"auto", fontSize:10, color:DIM }}>Bot pauses 30min around events</div>
    </div>
  );
}

function PriceChart({ data }) {
  return (
    <div style={{ ...MK, padding:"16px 20px", marginBottom:14 }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10 }}>
        <div style={{ fontSize:10, color:DIM, letterSpacing:3 }}>XAUUSD LIVE PRICE</div>
        <div style={{ fontSize:9, color:DIM }}>
          <span style={{ color:GOLD }}>——</span> Price &nbsp;
        </div>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data} margin={{ top:4, right:4, left:0, bottom:0 }}>
          <defs>
            <linearGradient id="goldGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={GOLD} stopOpacity={0.2}/>
              <stop offset="95%" stopColor={GOLD} stopOpacity={0}/>
            </linearGradient>
          </defs>
          <XAxis dataKey="t" hide />
          <YAxis domain={["auto","auto"]} hide />
          <Tooltip contentStyle={TTS} formatter={(v)=>[`$${v}`, "XAUUSD"]}/>
          <Area type="monotone" dataKey="price" stroke={GOLD} strokeWidth={1.5}
            fill="url(#goldGrad)" dot={false}/>
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function StrategyCompare({ strategies }) {
  const data = Object.entries(strategies || {}).map(([k, s]) => ({
    name:  STRAT_INFO[k]?.short || k,
    pnl:   s.net_pnl || 0,
    color: STRAT_INFO[k]?.color || GOLD,
  }));

  return (
    <div style={{ ...MK, padding:"16px 20px", marginBottom:14 }}>
      <div style={{ fontSize:10, color:DIM, letterSpacing:3, marginBottom:12 }}>
        STRATEGY P&L COMPARISON
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <BarChart data={data} margin={{ top:0, right:0, left:0, bottom:0 }}>
          <XAxis dataKey="name" tick={{ fill:DIM, fontSize:10, fontFamily:"monospace" }} axisLine={false} tickLine={false}/>
          <YAxis hide />
          <Tooltip contentStyle={TTS} formatter={(v)=>[`$${(+v).toFixed(2)}`, "P&L"]}/>
          <Bar dataKey="pnl" radius={[4,4,0,0]}>
            {data.map((d, i) => <Cell key={i} fill={d.pnl >= 0 ? d.color : RED}/>)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
export default function App() {
  const { state, chart, connected } = useBot();
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const istTime = now.toLocaleTimeString("en-IN", {
    timeZone:"Asia/Kolkata", hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false
  });
  const etTime = now.toLocaleTimeString("en-US", {
    timeZone:"America/New_York", hour:"2-digit", minute:"2-digit", hour12:true
  });

  const mkt = (() => {
    const s    = now.toLocaleString("en-US", { timeZone:"America/New_York", hour:"numeric", minute:"numeric", hour12:false });
    const [h,m]= s.split(":").map(Number);
    const mins = h*60+m;
    if (mins >= 9*60+30 && mins < 16*60) return { label:"MARKET OPEN", col:GREEN };
    if (mins >= 4*60 && mins < 9*60+30)  return { label:"PRE-MARKET",  col:GOLD };
    return { label:"AFTER-HOURS", col:DIM };
  })();

  const ov  = state?.overall || {};
  const acc = state?.account || {};
  const str = state?.strategies || {};

  return (
    <div style={{ minHeight:"100vh", background:BG, color:TEXT,
      fontFamily:"'JetBrains Mono','Fira Code','Courier New',monospace",
      padding:"20px 24px", boxSizing:"border-box" }}>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800;900&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        ::-webkit-scrollbar{width:4px}
        ::-webkit-scrollbar-track{background:${CARD}}
        ::-webkit-scrollbar-thumb{background:${BORDER};border-radius:2px}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
        @keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
      `}</style>

      {/* ── TOP BAR ── */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:20 }}>
        <div style={{ display:"flex", alignItems:"center", gap:14 }}>
          <div style={{ width:44, height:44, borderRadius:10,
            background:`linear-gradient(135deg, ${GOLD}30, ${GOLD}10)`,
            border:`1px solid ${GOLD}40`,
            display:"flex", alignItems:"center", justifyContent:"center", fontSize:22 }}>
            ⚡
          </div>
          <div>
            <div style={{ fontSize:22, fontWeight:900, color:GOLD, letterSpacing:1 }}>XAUUSD BOT</div>
            <div style={{ fontSize:10, color:DIM, letterSpacing:3, marginTop:2 }}>
              ASIAN BREAKOUT · GOLDMINE · SILVER BULLET
            </div>
          </div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", gap:5, alignItems:"flex-end" }}>
          <GoldDot on={connected} />
          <div style={{ fontSize:13, fontWeight:700, color:TEXT }}>{istTime} IST</div>
          <div style={{ fontSize:10, color:DIM }}>{etTime} ET</div>
          <div style={{ fontSize:10, letterSpacing:2, color:mkt.col,
            padding:"2px 10px", background:`${mkt.col}15`,
            border:`1px solid ${mkt.col}30`, borderRadius:3 }}>
            {mkt.label}
          </div>
        </div>
      </div>

      {/* ── ACCOUNT BAR ── */}
      <div style={{ display:"flex", ...MK, overflow:"hidden", marginBottom:14 }}>
        {[
          { l:"EQUITY",      v: fM(acc.equity),           c: TEXT  },
          { l:"AVAILABLE",   v: fM(acc.available),        c: TEXT  },
          { l:"P&L TODAY",   v: fM(acc.pnl_today, true),  c: (+acc.pnl_today||0)>=0?GREEN:RED },
          { l:"GOLD PRICE",  v: `$${f2(state?.price?.mid)}`, c: GOLD },
          { l:"SPREAD",      v: `$${f2(state?.price?.spread)}`, c: DIM },
        ].map(({l,v,c},i,arr)=>(
          <div key={i} style={{ flex:1, padding:"14px 16px",
            borderRight:i<arr.length-1?`1px solid ${BORDER}`:"none" }}>
            <div style={{ fontSize:9, color:DIM, letterSpacing:3, marginBottom:5 }}>{l}</div>
            <div style={{ fontSize:16, fontWeight:700, color:c }}>{v}</div>
          </div>
        ))}
      </div>

      {/* ── OVERALL STATS ── */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(5,1fr)", gap:10, marginBottom:14 }}>
        {[
          { l:"TOTAL TRADES", v: fN(ov.total_trades),   c:TEXT  },
          { l:"WIN RATE",     v: fP(ov.hit_ratio),       c:GREEN },
          { l:"TOTAL NET P&L",v: fM(ov.net_pnl,true),   c:(+ov.net_pnl||0)>=0?GREEN:RED },
          { l:"TODAY TRADES", v: `${ov.daily_trades||0}/2`, c:GOLD },
          { l:"STATUS",       v: ov.daily_halted?"HALTED":"ACTIVE", c:ov.daily_halted?RED:GREEN },
        ].map(({l,v,c},i)=>(
          <div key={i} style={{ ...MK, padding:"12px 14px", borderTop:`2px solid ${GOLD}40` }}>
            <div style={{ fontSize:9, color:DIM, letterSpacing:2, marginBottom:4 }}>{l}</div>
            <div style={{ fontSize:16, fontWeight:700, color:c }}>{v}</div>
          </div>
        ))}
      </div>

      {/* ── NEWS ALERT ── */}
      <NewsAlert events={state?.news_events} />

      {/* ── PRICE CHART + COMPARE ── */}
      <div style={{ display:"flex", gap:14, marginBottom:0 }}>
        <div style={{ flex:2 }}><PriceChart data={chart} /></div>
        <div style={{ flex:1 }}><StrategyCompare strategies={str} /></div>
      </div>

      {/* ── OPEN TRADE ── */}
      <OpenTrade t={state?.open_trade} price={state?.price} />

      {/* ── STRATEGY CARDS ── */}
      <div style={{ display:"flex", gap:14, marginBottom:14, flexWrap:"wrap" }}>
        {Object.keys(STRAT_INFO).map(k => (
          <StrategyCard key={k} name={k} data={str[k]} />
        ))}
      </div>

      {/* ── RISK RULES ── */}
      <div style={{ ...MK, padding:"14px 20px", marginBottom:14 }}>
        <div style={{ fontSize:10, color:DIM, letterSpacing:3, marginBottom:10 }}>
          ACTIVE RISK RULES
        </div>
        <div style={{ display:"flex", flexWrap:"wrap", gap:"8px 28px" }}>
          {[
            ["RISK/TRADE",    "1% of equity"],
            ["DAILY STOP",    "3% max loss → halts"],
            ["WEEKLY STOP",   "5% max loss → halts"],
            ["MAX TRADES",    "2 per day"],
            ["STOP LOSS",     "1.5× ATR"],
            ["TP1",           "1.5R → partial close"],
            ["TP2",           "2.0R → full close"],
            ["BREAKEVEN",     "Move SL at 1R"],
            ["SPREAD FILTER", ">$0.50 → skip"],
            ["NEWS FILTER",   "30min buffer NFP/CPI/FOMC"],
            ["BEST DAYS",     "Tue / Wed / Thu only"],
            ["FRIDAY CUT",    "No new trades after 11:30 PM IST"],
            ["ASIAN RANGE",   "$5–$25 valid range"],
            ["DEAD ZONE",     "3:30 AM–1:30 PM IST skip"],
          ].map(([k,v])=>(
            <div key={k}>
              <span style={{ color:GOLD, fontSize:10, fontWeight:700, marginRight:8 }}>{k}</span>
              <span style={{ color:DIM, fontSize:11 }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── FOOTER ── */}
      <div style={{ display:"flex", justifyContent:"space-between", fontSize:10, color:"#333" }}>
        <span>PAPER TRADING · CAPITAL.COM DEMO · NOT FINANCIAL ADVICE</span>
        <span>{state ? `Updated: ${new Date(state.timestamp).toLocaleTimeString("en-IN", {timeZone:"Asia/Kolkata"})} IST` : "—"}</span>
      </div>
    </div>
  );
}
