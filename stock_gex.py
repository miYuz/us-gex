# -*- coding: utf-8 -*-
"""單一美股個股的 GEX(Gamma Exposure)+ Max Pain,資料源 yfinance。

跟 taifex_gex 的差異:
  - 標的是個股現貨(不是指數期貨),用標準 Black-Scholes,不用 Black-76。
  - IV 直接吃 yfinance 選擇權鏈自帶的 impliedVolatility,不用自己反推
    (Yahoo 的中間價已經幫你算好了,省掉整套 brentq 求解)。
  - Max Pain:對每個「實際掛牌的履約價」當作假設結算價,算全部買方的
    到期損益總和,找出讓買方損益總和最小(賣方/做市商最有利)的那一檔。

GEX 符號慣例(業界標準,同 SpotGamma / taifex_gex):
    造市商 long call gamma、short put gamma
    GEX_strike = Σ ±(gamma × OI × 100 × S² × 1%)   (call 正、put 負)
"""
import math

import numpy as np
import pandas as pd
from scipy.stats import norm

CONTRACT_MULTIPLIER = 100.0   # 美股選擇權:100 股/約
RISK_FREE = 0.04              # 短天期影響小,取近似值即可


def _d1(S, K, T, sigma, r=RISK_FREE, q=0.0):
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def gamma_bs(S, K, T, sigma, r=RISK_FREE, q=0.0):
    """標準 Black-Scholes gamma(call/put 共用同一個公式)。"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return float("nan")
    d1 = _d1(S, K, T, sigma, r, q)
    return math.exp(-q * T) * norm.pdf(d1) / (S * sigma * math.sqrt(T))


def fetch_chain(ticker, expiry=None, verbose=True):
    """回傳 (spot, expiry_used, dte, calls_df, puts_df)。expiry=None 取最近到期日。"""
    import yfinance as yf

    t = yf.Ticker(ticker)
    spot = t.fast_info["lastPrice"]
    expiries = t.options
    if not expiries:
        raise RuntimeError(f"{ticker} 沒有掛牌選擇權")
    expiry = expiry or expiries[0]
    if expiry not in expiries:
        raise ValueError(f"{expiry} 不是有效到期日,可用: {expiries}")

    oc = t.option_chain(expiry)
    dte = max((pd.Timestamp(expiry) - pd.Timestamp.today().normalize()).days, 0)
    if verbose:
        print(f"{ticker}  spot={spot:.2f}  expiry={expiry}  dte={dte}  "
             f"calls={len(oc.calls)} puts={len(oc.puts)}")
    return spot, expiry, dte, oc.calls, oc.puts


def compute_gex(spot, dte, calls, puts, min_t_days=0.5):
    """逐履約價算 GEX。回傳 per_strike DataFrame(strike, gex_e6 單位:百萬美元/1%)。"""
    T = max(dte, min_t_days) / 365.0
    rows = []
    for df, sign in ((calls, 1.0), (puts, -1.0)):
        for r in df.itertuples():
            oi = getattr(r, "openInterest", 0)
            oi = 0 if oi is None or pd.isna(oi) else oi
            iv = getattr(r, "impliedVolatility", None)
            if oi <= 0 or iv is None or iv <= 0 or pd.isna(iv):
                continue
            g = gamma_bs(spot, float(r.strike), T, float(iv))
            if pd.isna(g):
                continue
            dollar_gamma = g * oi * CONTRACT_MULTIPLIER * spot ** 2 * 0.01 * sign
            rows.append({"strike": float(r.strike), "right": "C" if sign > 0 else "P",
                        "oi": oi, "iv": iv, "gamma": g, "dollar_gamma": dollar_gamma})
    contracts = pd.DataFrame(rows)
    if contracts.empty:
        return contracts, pd.DataFrame(columns=["strike", "gex_e6"])
    per_strike = contracts.groupby("strike")["dollar_gamma"].sum().reset_index()
    per_strike["gex_e6"] = per_strike["dollar_gamma"] / 1e6
    return contracts, per_strike.sort_values("strike").reset_index(drop=True)


def compute_max_pain(calls, puts):
    """回傳 (max_pain_strike, payout DataFrame(strike, payout_total_usd))。

    對每個實際掛牌履約價當假設結算價,算全部買方(call+put)到期可拿回的內含價值總額
    ×OI×100,找出讓這個總額最小的履約價 —— 那就是「讓最多買方最痛」的價位。
    """
    strikes = sorted(set(calls["strike"]).union(puts["strike"]))
    c_oi = {k: (0 if pd.isna(v) else v) for k, v in calls.set_index("strike")["openInterest"].to_dict().items()}
    p_oi = {k: (0 if pd.isna(v) else v) for k, v in puts.set_index("strike")["openInterest"].to_dict().items()}

    payout = []
    for settle in strikes:
        total = 0.0
        for k, oi in c_oi.items():
            total += max(settle - k, 0) * oi
        for k, oi in p_oi.items():
            total += max(k - settle, 0) * oi
        payout.append({"strike": settle, "payout_usd": total * CONTRACT_MULTIPLIER})
    pdf = pd.DataFrame(payout)
    max_pain = float(pdf.loc[pdf["payout_usd"].idxmin(), "strike"])
    return max_pain, pdf


def top_walls(per_strike, n=5):
    calls_wall = per_strike[per_strike["gex_e6"] > 0].nlargest(n, "gex_e6")
    puts_wall = per_strike[per_strike["gex_e6"] < 0].nsmallest(n, "gex_e6")
    return calls_wall.sort_values("strike"), puts_wall.sort_values("strike")


def _gamma_bs_vec(S, K, T, sigma, r=RISK_FREE, q=0.0):
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))


def gex_curve(contracts, spot, dte, pct_range=(0.7, 1.3), n=200, min_t_days=0.5):
    """sticky-strike 假設:每個假設現貨價 S_hyp 下,每個合約自己的 IV 固定不動,
    只有 S_hyp 代入 gamma 公式重新算,加總成當下假設現貨價的總 GEX。

    跟 taifex_gex 的 sticky-strike 簡化同一套邏輯,只是這裡 S 就是股票本身現貨,
    不用像期貨那樣另外用 forward 平移。
    """
    T = max(dte, min_t_days) / 365.0
    S_grid = np.linspace(spot * pct_range[0], spot * pct_range[1], n)
    signs = np.where(contracts["right"].values == "C", 1.0, -1.0)
    K = contracts["strike"].values.astype(float)
    iv = contracts["iv"].values.astype(float)
    oi = contracts["oi"].values.astype(float)

    totals = np.empty(n)
    for i, S in enumerate(S_grid):
        g = _gamma_bs_vec(S, K, T, iv)
        dollar = g * oi * CONTRACT_MULTIPLIER * S ** 2 * 0.01 * signs
        totals[i] = np.nansum(dollar) / 1e6
    return pd.DataFrame({"S_hyp": S_grid, "gex_e6": totals})


def active_window(per_strike, spot, key_levels=(), min_pct=0.06, max_pct=0.30,
                   threshold_frac=0.03, pad_strikes=3):
    """自動抓「GEX 真的有東西」的履約價範圍,而不是死板 ±X%。

    到期日越近,gamma 集中在現貨附近的範圍越窄(這是 gamma ~ 1/sqrt(T) 的直接後果,
    見 gamma_bs 的推導)——0DTE 如果還硬套跟月選一樣的 ±30% 視窗,大部分履約價的
    GEX 都趨近 0,圖表大半是空的,看起來「太窄」(訊號被稀釋在一大片空白裡)。
    做法:先找出 |GEX| 超過全體最大值 threshold_frac 的履約價當作「有效範圍」,
    往外墊 pad_strikes 檔給一點衰減的視覺脈絡,再用 [spot*(1-max_pct), spot*(1+max_pct)]
    當外框上限、min_pct 當下限,並確保 key_levels(現貨/Max Pain/Gamma Flip)都在範圍內。
    """
    lo_cap, hi_cap = spot * (1 - max_pct), spot * (1 + max_pct)
    strikes = per_strike["strike"].values
    vals = per_strike["gex_e6"].abs().values
    mx = vals.max() if len(vals) else 0.0

    if mx <= 0 or len(strikes) == 0:
        lo, hi = lo_cap, hi_cap
    else:
        active_idx = np.where(vals >= mx * threshold_frac)[0]
        order = np.argsort(strikes)
        strikes_sorted = strikes[order]
        pos_of = {s: i for i, s in enumerate(strikes_sorted)}
        lo_i = min(pos_of[strikes[i]] for i in active_idx)
        hi_i = max(pos_of[strikes[i]] for i in active_idx)
        lo_i = max(0, lo_i - pad_strikes)
        hi_i = min(len(strikes_sorted) - 1, hi_i + pad_strikes)
        lo, hi = float(strikes_sorted[lo_i]), float(strikes_sorted[hi_i])

    for k in key_levels:
        if k is not None:
            lo, hi = min(lo, k), max(hi, k)

    lo, hi = max(lo, lo_cap), min(hi, hi_cap)
    min_span = spot * min_pct
    if hi - lo < min_span:
        mid = (hi + lo) / 2
        lo, hi = mid - min_span / 2, mid + min_span / 2
    return lo, hi


def find_gamma_flip(curve, spot=None):
    """回傳 GEX 曲線在 0 的所有交叉點(線性內插);spot 給定時回傳離現貨最近的那個。"""
    xs = curve["S_hyp"].values
    ys = curve["gex_e6"].values
    crossings = []
    for i in range(len(ys) - 1):
        if ys[i] == 0:
            crossings.append(float(xs[i]))
        elif ys[i] * ys[i + 1] < 0:
            t = ys[i] / (ys[i] - ys[i + 1])
            crossings.append(float(xs[i] + t * (xs[i + 1] - xs[i])))
    if not crossings:
        return None
    if spot is None:
        return crossings
    return min(crossings, key=lambda c: abs(c - spot))
