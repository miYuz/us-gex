# -*- coding: utf-8 -*-
"""抓 yfinance 選擇權鏈,算逐履約價 GEX + Gamma Flip + Max Pain,重建互動儀表板 HTML。

    python build_dashboard.py [輸出路徑]

樣板放在 dashboard/ 底下,結構仿 taifex_gex/taifex_vix 的 build_dashboard.py:
    template_head.html  版面 + CSS + 靜態結構
    template_tail.js    繪圖與互動邏輯
全部圖表都是純 SVG,由前端 JS 直接吃 JSON payload 畫出來。只吃 yfinance 公開選擇權
資料,沒有任何需要帳密的相依,可以放心跑在 GitHub Actions 的公開 runner 上。

跟 taifex_gex 不一樣的地方:這裡沒有「每日累積歷史」的概念,純粹是即時快照——
每次執行都是當下 yfinance 回傳的最新報價,不落地存 CSV。也因為 yfinance 在
GitHub Actions 的共用 runner IP 上偶爾會被 Yahoo 限流(429 / 空回應),所以:
  1. 每個 (ticker, expiry) 都有重試(REQUEST_RETRIES 次、間隔遞增)。
  2. 只要成功標的數低於 MIN_OK_TICKERS,整批視為「這次抓取品質太差」,
     直接不覆寫 docs/index.html,讓網站維持上一次的好版本,等下一個排程時段重試
     (daily.yml 排了台北 06:00 / 08:30 / 11:00 三個時段,同樣邏輯)。
"""
import json
import os
import re
import sys
import time
import datetime as dt

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_gex as sg

TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "GOOG", "MSFT", "AMZN", "SPCX", "META", "MU", "TSM"]
MAX_SHORT = 4      # 每個標的抓最近 N 個到期日(通常涵蓋 0DTE + 幾個週選)
MAX_TOTAL = 5       # 再補最近的月選,總共最多幾檔
MIN_OK_TICKERS = 6  # 少於這個成功標的數,視為這次抓取品質太差,不覆寫網站

REQUEST_RETRIES = 3
RETRY_BACKOFF_SEC = 4

TPL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "index.html")


def is_monthly(iso):
    d = dt.datetime.strptime(iso, "%Y-%m-%d")
    return d.weekday() == 4 and 15 <= d.day <= 21   # 美股標準月選:第三個星期五


def pick_expiries(all_expiries):
    short = list(all_expiries[:MAX_SHORT])
    monthly = next((e for e in all_expiries if is_monthly(e)), None)
    if monthly and monthly not in short:
        short.append(monthly)
    return short[:MAX_TOTAL]


def tag_for(iso, dte):
    if is_monthly(iso):
        return "月選"
    if dte == 0:
        return "0DTE"
    return "週選"


def wall_rows(df):
    return [{"strike": float(r.strike), "gex": round(float(r.gex_e6), 3)} for r in df.itertuples()]


def with_retries(fn, *args, **kwargs):
    last_err = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:                       # noqa: BLE001
            last_err = e
            if attempt < REQUEST_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
    raise last_err


def build_one(ticker, expiry):
    spot, expiry, dte, calls, puts = sg.fetch_chain(ticker, expiry=expiry, verbose=False)
    contracts, per_strike = sg.compute_gex(spot, dte, calls, puts)
    if contracts.empty:
        raise RuntimeError(f"{ticker} {expiry}: 沒有有效 OI 的合約")
    max_pain, pain_df = sg.compute_max_pain(calls, puts)
    call_wall, put_wall = sg.top_walls(per_strike, n=5)
    total_gex = float(per_strike["gex_e6"].sum())
    curve = sg.gex_curve(contracts, spot, dte)
    gamma_flip = sg.find_gamma_flip(curve, spot=spot)
    gamma_flip_v = float(gamma_flip) if gamma_flip is not None else None

    lo, hi = sg.active_window(per_strike, spot, key_levels=(max_pain, gamma_flip_v))
    ps = per_strike[(per_strike.strike >= lo) & (per_strike.strike <= hi)].copy()

    pain_lo, pain_hi = spot * 0.70, spot * 1.30
    pp = pain_df[(pain_df.strike >= pain_lo) & (pain_df.strike <= pain_hi)].copy()

    return {
        "ticker": ticker,
        "date": dt.datetime.now(dt.timezone.utc).astimezone(
            dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M (台北)"),
        "spot": round(float(spot), 2),
        "expiry": expiry,
        "dte": int(dte),
        "tag": tag_for(expiry, dte),
        "total_gex": round(total_gex, 2),
        "max_pain": round(float(max_pain), 1),
        "gamma_flip": round(gamma_flip_v, 1) if gamma_flip_v is not None else None,
        "strike": [round(float(v), 2) for v in ps["strike"]],
        "strike_gex": [round(float(v), 3) for v in ps["gex_e6"]],
        "pain_strike": [round(float(v), 2) for v in pp["strike"]],
        "pain_payout": [round(float(v) / 1e6, 3) for v in pp["payout_usd"]],
        "call_wall": wall_rows(call_wall.sort_values("strike")),
        "put_wall": wall_rows(put_wall.sort_values("strike", ascending=False)),
        "n_contracts": int(len(contracts)),
        "n_raw": int(len(calls) + len(puts)),
    }


def fetch_all(verbose=True):
    out = {}
    for tk in TICKERS:
        try:
            t = yf.Ticker(tk)
            expiries = pick_expiries(list(with_retries(lambda: t.options)))
        except Exception as e:                        # noqa: BLE001
            if verbose:
                print(f"[warn] {tk} 抓不到到期日清單: {e}")
            continue
        out[tk] = {}
        for exp in expiries:
            try:
                out[tk][exp] = with_retries(build_one, tk, exp)
            except Exception as e:                    # noqa: BLE001
                if verbose:
                    print(f"[warn] {tk} {exp} 失敗: {e}")
        if not out[tk]:
            del out[tk]
        elif verbose:
            print(f"{tk}: {len(out[tk])} 個到期日 OK")
    return out


def build(out_path=None, verbose=True):
    out_path = out_path or DEFAULT_OUT
    snapshots = fetch_all(verbose=verbose)

    if len(snapshots) < MIN_OK_TICKERS:
        if verbose:
            print(f"[warn] 只有 {len(snapshots)}/{len(TICKERS)} 個標的抓到資料"
                  f"(門檻 {MIN_OK_TICKERS}),疑似被 Yahoo 限流。"
                  f"跳過這次重建,保留網站上一次的版本,等下一個排程時段重試。")
        return None

    head = open(os.path.join(TPL_DIR, "template_head.html"), encoding="utf-8").read()
    tail = open(os.path.join(TPL_DIR, "template_tail.js"), encoding="utf-8").read()

    now_tw = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8)))
    head = _patch_footer(head, snapshots, now_tw)

    data_js = "const SNAPSHOTS = " + json.dumps(snapshots, ensure_ascii=False, separators=(",", ":")) + ";"
    html = head + "\n<script>\n" + data_js + "\n" + tail + "\n</" + "script>\n"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    if verbose:
        print(f"儀表板已重建: {out_path}  ({len(html):,} bytes, {len(snapshots)}/{len(TICKERS)} 個標的)")
    return out_path


def _patch_footer(head, snapshots, now_tw):
    n_ok = len(snapshots)
    n_total = len(TICKERS)
    new = (f"資料每天台北時間 06:00 更新(08:30 / 11:00 為備援,遇 Yahoo 限流才會補跑)。"
           f"本次建置 {now_tw:%Y-%m-%d %H:%M} 台北時間,{n_ok}/{n_total} 個標的成功。"
           f"本頁僅作市場結構說明,<b>不構成投資建議</b>。資料來源:yfinance(Yahoo Finance 公開行情)。")
    return re.sub(r'<div id="footerBuild">.*?</div>',
                  f'<div id="footerBuild">{new}</div>', head, flags=re.S)


def main(argv=None):
    argv = argv or sys.argv[1:]
    # 抓取品質不足時 build() 回傳 None、故意不覆寫 docs/index.html,但這是「等下一個
    # 排程時段重試」的正常流程,不是壞掉——所以這裡固定回 0,讓 workflow 保持綠燈,
    # 不會每次 Yahoo 限流就寄一封嚇人的失敗通知信。commit 那一步本來就只看 docs/
    # 有沒有變動,build() 沒寫檔的話自然什麼都不會 commit。
    build(argv[0] if argv else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
