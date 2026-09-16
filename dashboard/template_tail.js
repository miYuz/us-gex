const SVGNS = "http://www.w3.org/2000/svg";
const el = (n, a = {}) => {
  const e = document.createElementNS(SVGNS, n);
  for (const k in a) if (a[k] !== null && a[k] !== undefined) e.setAttribute(k, a[k]);
  return e;
};
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = (v, n = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : v.toFixed(n);
const fmtSigned = (v, n = 1) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : (v > 0 ? "+" : "") + v.toFixed(n);
const marginsFor = (W) => ({ l: 58, r: W < 560 ? 16 : 60 });

function niceTicks(lo, hi, count = 5) {
  const span = hi - lo || 1;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.ceil(lo / step) * step;
  const out = [];
  for (let v = start; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function drawTiles(S) {
  const flipDist = S.gamma_flip === null ? null : S.spot - S.gamma_flip;
  const regime = S.total_gex >= 0 ? "positive" : "negative";
  const items = [
    { k: "Gamma Flip", c: "--flip", v: S.gamma_flip === null ? "—" : S.gamma_flip.toLocaleString(),
      sub: `${S.expiry} · dte ${S.dte} · ${S.tag}` },
    { k: "現貨", c: "--spot", v: S.spot.toLocaleString(undefined,{maximumFractionDigits:2}), sub: `${S.date}` },
    { k: "距離(現貨-Flip)", c: null, v: flipDist === null ? "—" : fmtSigned(flipDist, 1),
      sub: flipDist === null ? "—" : (flipDist >= 0 ? "在煞車區之上" : "在油門區之下") },
    { k: "Max Pain", c: "--key", v: S.max_pain.toLocaleString(), sub: fmtSigned(S.max_pain - S.spot, 1) + " 點" },
    { k: "總 GEX(百萬美元)", c: regime === "positive" ? "--gex-pos" : "--gex-neg", v: fmtSigned(S.total_gex, 1),
      sub: null, pill: regime },
  ];
  document.getElementById("tiles").innerHTML = items.map((it) => `
    <div class="tile">
      <div class="k">${it.c ? `<span class="swatch" style="background:var(${it.c})"></span>` : ""}${it.k}</div>
      <div class="v">${it.v}</div>
      <div class="sub">${
        it.pill
          ? `<span class="pill ${it.pill === "positive" ? "pos" : "neg"}"><span class="dot"></span>${it.pill === "positive" ? "正 GEX · 煞車" : "負 GEX · 油門"}</span>`
          : (it.sub ?? "")
      }</div>
    </div>`).join("");
}

/* ---------- GEX 各履約價 ---------- */
function drawStrikeBar(host, S) {
  host.querySelectorAll("svg").forEach((n) => n.remove());
  const n = S.strike.length;
  const W = Math.max(320, host.clientWidth);
  const PLOT_H = W < 560 ? 200 : 260;
  const M = { t: 12, b: 26, ...marginsFor(W) };
  const H = PLOT_H + M.t + M.b;
  const iw = W - M.l - M.r, ih = PLOT_H;

  const loK = Math.min(...S.strike), hiK = Math.max(...S.strike);
  const kPad = (hiK - loK) * 0.04 || 10;
  const X = (k) => M.l + ((k - (loK - kPad)) / ((hiK + kPad) - (loK - kPad))) * iw;

  const vals = S.strike_gex;
  const mx = Math.max(...vals.map(Math.abs)) * 1.15 || 1;
  const Y = (v) => M.t + ih / 2 - (v / mx) * (ih / 2);

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "各履約價 GEX" });

  for (const t of [mx * 0.6, -mx * 0.6]) {
    svg.appendChild(el("line", { x1: M.l, x2: M.l + iw, y1: Y(t), y2: Y(t), stroke: css("--grid"), "stroke-width": 1 }));
    const tx = el("text", { x: M.l - 8, y: Y(t) + 4, "text-anchor": "end", fill: css("--muted"), "font-size": 10.5, "font-family": "ui-monospace, Consolas, monospace" });
    tx.textContent = (t > 0 ? "+" : "") + t.toFixed(0);
    svg.appendChild(tx);
  }
  const zero = Y(0);
  svg.appendChild(el("line", { x1: M.l, x2: M.l + iw, y1: zero, y2: zero, stroke: css("--axis"), "stroke-width": 1 }));

  const avgGap = n > 1 ? (hiK - loK) / (n - 1) : 5;
  const pxPerUnit = iw / ((hiK + kPad) - (loK - kPad));
  const bw = Math.max(2, Math.min(20, avgGap * 0.7 * pxPerUnit));
  const posC = css("--gex-pos"), negC = css("--gex-neg");

  for (let i = 0; i < n; i++) {
    const v = vals[i], x = X(S.strike[i]);
    const y = v >= 0 ? Y(v) : zero;
    svg.appendChild(el("rect", { x: x - bw / 2, y, width: bw, height: Math.max(0.5, Math.abs(Y(v) - zero)), fill: v >= 0 ? posC : negC }));
  }

  svg.appendChild(el("line", { x1: X(S.spot), x2: X(S.spot), y1: M.t, y2: M.t + ih, stroke: css("--spot"), "stroke-width": 1.4 }));
  if (S.gamma_flip !== null && S.gamma_flip >= loK - kPad && S.gamma_flip <= hiK + kPad) {
    svg.appendChild(el("line", { x1: X(S.gamma_flip), x2: X(S.gamma_flip), y1: M.t, y2: M.t + ih, stroke: css("--flip"), "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
  }
  svg.appendChild(el("line", { x1: X(S.max_pain), x2: X(S.max_pain), y1: M.t, y2: M.t + ih, stroke: css("--key"), "stroke-width": 1.4, "stroke-dasharray": "2 3" }));

  for (const k of niceTicks(loK - kPad, hiK + kPad, Math.floor(iw / 70))) {
    const tx = el("text", { x: X(k), y: M.t + ih + 17, "text-anchor": "middle", fill: css("--muted"), "font-size": 10.5, "font-family": "ui-monospace, Consolas, monospace" });
    tx.textContent = k.toLocaleString();
    svg.appendChild(tx);
  }

  host.appendChild(svg);

  const tip = host.querySelector(".tip");
  const nearest = (clientX) => {
    const r = svg.getBoundingClientRect();
    const x = (clientX - r.left) * (W / r.width);
    const k = loK - kPad + ((x - M.l) / iw) * ((hiK + kPad) - (loK - kPad));
    let best = 0, bd = Infinity;
    S.strike.forEach((sk, i) => { const d = Math.abs(sk - k); if (d < bd) { bd = d; best = i; } });
    return best;
  };
  const show = (i) => {
    if (!tip) return;
    tip.innerHTML = `<div class="t1">履約價 ${S.strike[i].toLocaleString()}</div>
      <div class="row"><span class="swatch" style="background:${vals[i] >= 0 ? posC : negC}"></span>GEX <b>${fmtSigned(vals[i], 2)} M</b></div>`;
    tip.classList.add("on");
    const scale = host.clientWidth / W;
    const px = X(S.strike[i]);
    const tw = tip.offsetWidth;
    const left = Math.max(tw / 2 + 2, Math.min(host.clientWidth - tw / 2 - 2, px * scale));
    tip.style.left = left + "px"; tip.style.top = "6px";
  };
  svg.addEventListener("pointermove", (e) => show(nearest(e.clientX)));
  svg.addEventListener("pointerdown", (e) => show(nearest(e.clientX)));
  svg.addEventListener("pointerleave", () => tip && tip.classList.remove("on"));
}

/* ---------- Max Pain 到期損益曲線 ---------- */
function drawPainCurve(host, S) {
  host.querySelectorAll("svg").forEach((n) => n.remove());
  const n = S.pain_strike.length;
  const W = Math.max(320, host.clientWidth);
  const PLOT_H = W < 560 ? 200 : 260;
  const M = { t: 12, b: 26, ...marginsFor(W) };
  const H = PLOT_H + M.t + M.b;
  const iw = W - M.l - M.r, ih = PLOT_H;

  const loK = Math.min(...S.pain_strike), hiK = Math.max(...S.pain_strike);
  const X = (k) => M.l + ((k - loK) / (hiK - loK)) * iw;
  const mx = Math.max(...S.pain_payout) * 1.08 || 1;
  const Y = (v) => M.t + ih - (v / mx) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Max Pain 到期損益曲線" });

  for (const t of niceTicks(0, mx, 4)) {
    svg.appendChild(el("line", { x1: M.l, x2: M.l + iw, y1: Y(t), y2: Y(t), stroke: t === 0 ? css("--axis") : css("--grid"), "stroke-width": 1 }));
    const tx = el("text", { x: M.l - 8, y: Y(t) + 4, "text-anchor": "end", fill: css("--muted"), "font-size": 10.5, "font-family": "ui-monospace, Consolas, monospace" });
    tx.textContent = t.toFixed(0);
    svg.appendChild(tx);
  }
  for (const k of niceTicks(loK, hiK, Math.floor(iw / 70))) {
    const tx = el("text", { x: X(k), y: M.t + ih + 17, "text-anchor": "middle", fill: css("--muted"), "font-size": 10.5, "font-family": "ui-monospace, Consolas, monospace" });
    tx.textContent = k.toLocaleString();
    svg.appendChild(tx);
  }

  let dpath = "";
  S.pain_strike.forEach((k, i) => { dpath += (i ? "L" : "M") + X(k).toFixed(1) + " " + Y(S.pain_payout[i]).toFixed(1) + " "; });
  svg.appendChild(el("path", { d: dpath, fill: "none", stroke: css("--key"), "stroke-width": 2, "stroke-linejoin": "round" }));

  svg.appendChild(el("line", { x1: X(S.spot), x2: X(S.spot), y1: M.t, y2: M.t + ih, stroke: css("--spot"), "stroke-width": 1.4 }));

  let minIdx = 0;
  S.pain_payout.forEach((v, i) => { if (v < S.pain_payout[minIdx]) minIdx = i; });
  const mpx = X(S.pain_strike[minIdx]), mpy = Y(S.pain_payout[minIdx]);
  svg.appendChild(el("line", { x1: mpx, x2: mpx, y1: M.t, y2: M.t + ih, stroke: css("--key"), "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
  svg.appendChild(el("circle", { cx: mpx, cy: mpy, r: 4.5, fill: css("--key"), stroke: css("--surface"), "stroke-width": 2 }));

  host.appendChild(svg);

  const tip = host.querySelector(".tip");
  const cross = el("line", { y1: M.t, y2: M.t + ih, stroke: css("--axis"), "stroke-width": 1, opacity: 0 });
  svg.insertBefore(cross, svg.firstChild.nextSibling);
  const idxFrom = (clientX) => {
    const r = svg.getBoundingClientRect();
    const x = (clientX - r.left) * (W / r.width);
    const k = loK + ((x - M.l) / iw) * (hiK - loK);
    const t = (k - loK) / (hiK - loK) * (n - 1);
    return Math.max(0, Math.min(n - 1, Math.round(t)));
  };
  const show = (i) => {
    const px = X(S.pain_strike[i]);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 1);
    if (!tip) return;
    tip.innerHTML = `<div class="t1">假設結算價 ${S.pain_strike[i].toLocaleString()}</div>
      <div class="row">買方損益總額 <b>${S.pain_payout[i].toFixed(1)} M</b></div>`;
    tip.classList.add("on");
    const scale = host.clientWidth / W;
    const tw = tip.offsetWidth;
    const left = Math.max(tw / 2 + 2, Math.min(host.clientWidth - tw / 2 - 2, px * scale));
    tip.style.left = left + "px"; tip.style.top = "6px";
  };
  svg.addEventListener("pointermove", (e) => show(idxFrom(e.clientX)));
  svg.addEventListener("pointerdown", (e) => show(idxFrom(e.clientX)));
  svg.addEventListener("pointerleave", () => { cross.setAttribute("opacity", 0); if (tip) tip.classList.remove("on"); });
}

function renderWalls(S) {
  const callBody = document.getElementById("callWallBody");
  const putBody = document.getElementById("putWallBody");
  const distCell = (k) => {
    const d = k - S.spot;
    return `${fmtSigned(d, 1)} (${fmtSigned(d / S.spot * 100, 1)}%)`;
  };
  const calls = [...S.call_wall].sort((a, b) => b.gex - a.gex).map((r, i) => ({ ...r, rank: i + 1 })).sort((a, b) => a.strike - b.strike);
  callBody.innerHTML = calls.map((r) => `<tr><td>${r.rank}</td><td>${r.strike.toLocaleString()}</td><td style="color:var(--gex-pos)">${fmtSigned(r.gex, 2)}</td><td>${distCell(r.strike)}</td></tr>`).join("");
  const puts = [...S.put_wall].sort((a, b) => a.gex - b.gex).map((r, i) => ({ ...r, rank: i + 1 })).sort((a, b) => b.strike - a.strike);
  putBody.innerHTML = puts.map((r) => `<tr><td>${r.rank}</td><td>${r.strike.toLocaleString()}</td><td style="color:var(--gex-neg)">${fmtSigned(r.gex, 2)}</td><td>${distCell(r.strike)}</td></tr>`).join("");
}

const TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "GOOG", "MSFT", "AMZN", "SPCX", "META", "MU", "TSM"].filter((t) => SNAPSHOTS[t]);
let currentTicker = SNAPSHOTS["SPY"] ? "SPY" : TICKERS[0];
let currentExpiry = null;

function expiriesFor(tk) {
  return Object.keys(SNAPSHOTS[tk]).sort();
}

function render() {
  const S = SNAPSHOTS[currentTicker][currentExpiry];
  drawTiles(S);
  document.getElementById("strikeNote").textContent = `${S.tag} · dte ${S.dte} · 自動抓 GEX 有效範圍 · ${S.n_contracts}/${S.n_raw} 檔合約有效 OI`;
  drawStrikeBar(document.getElementById("plotStrike"), S);
  drawPainCurve(document.getElementById("plotPain"), S);
  renderWalls(S);
  document.getElementById("footerRange").textContent = `更新於 ${S.date} · 標的 ${S.ticker} · 到期日 ${S.expiry}(${S.tag} · dte ${S.dte})· 現貨 ${S.spot}`;
}

function buildExpiryRow() {
  const expiryRow = document.getElementById("expiryRow");
  expiryRow.querySelectorAll("button.tk").forEach((b) => b.remove());
  const exps = expiriesFor(currentTicker);
  if (!exps.includes(currentExpiry)) currentExpiry = exps[0];
  exps.forEach((exp) => {
    const d = SNAPSHOTS[currentTicker][exp];
    const btn = document.createElement("button");
    btn.className = "tk";
    btn.textContent = `${exp.slice(5)} · ${d.tag}`;
    btn.setAttribute("aria-pressed", exp === currentExpiry ? "true" : "false");
    btn.addEventListener("click", () => {
      currentExpiry = exp;
      expiryRow.querySelectorAll("button.tk").forEach((b) => b.setAttribute("aria-pressed", "false"));
      btn.setAttribute("aria-pressed", "true");
      render();
    });
    expiryRow.appendChild(btn);
  });
}

const tickerRow = document.getElementById("tickerRow");
TICKERS.forEach((tk) => {
  const btn = document.createElement("button");
  btn.className = "tk";
  btn.textContent = tk;
  btn.setAttribute("aria-pressed", tk === currentTicker ? "true" : "false");
  btn.addEventListener("click", () => {
    currentTicker = tk;
    currentExpiry = null;
    tickerRow.querySelectorAll("button.tk").forEach((b) => b.setAttribute("aria-pressed", b.textContent === tk ? "true" : "false"));
    buildExpiryRow();
    render();
  });
  tickerRow.appendChild(btn);
});

buildExpiryRow();
render();
window.addEventListener("resize", () => {
  clearTimeout(window.__rt);
  window.__rt = setTimeout(render, 120);
});
