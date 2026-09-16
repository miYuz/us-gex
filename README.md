# us-gex

用 **yfinance 公開選擇權資料**估算美股個股/ETF 造市商的 **Gamma 曝險（GEX）**、
**Gamma Flip**（sticky-strike 零交叉點）與 **Max Pain**。免帳號、免券商 API,
純即時快照,每日排程自動更新。

方法沿用業界標準假設（SqueezeMetrics 同款）：造市商 long call gamma、short put
gamma,用標準 Black-Scholes 算每個履約價的 Gamma;IV 直接吃 yfinance 選擇權鏈
自帶值(Yahoo 中間價已內含,不用自己反推)。

📈 **[互動儀表板](https://miyuz.github.io/us-gex/)** — 標的/到期日雙層切換
（0DTE / 週選 / 月選）、GEX 逐履約價、Max Pain 到期損益曲線、Call Wall/Put Wall

---

## 涵蓋標的

`SPY QQQ NVDA AAPL GOOG MSFT AMZN SPCX META MU TSM`

每個標的抓最近 4 個到期日（通常涵蓋 0DTE + 幾個週選)再補上最近的月選（美股標準
第三個星期五),總共最多 5 檔可切換。

---

## 跟 taifex-gex（台指 GEX 儀表板）的差異

| | us-gex | taifex-gex |
|---|---|---|
| 標的 | 美股個股/ETF 現貨 | 台指期貨(TXO) |
| 定價模型 | 標準 Black-Scholes | Black-76(forward 定價) |
| IV 來源 | yfinance 選擇權鏈自帶值 | 用結算價 brentq 反推 |
| 資料型態 | 即時快照(不落地存歷史) | 每日收盤累積歷史 CSV |
| 到期日 | 可切換 0DTE / 週選 / 月選 | 只算最近到期日 |

---

## 快速開始

```bash
pip install -r requirements.txt
python build_dashboard.py docs/index.html
```

---

## 方法

1. **標準 Black-Scholes**:個股/ETF 現貨沒有台指期貨那種除息季逆價差問題,
   不需要像 taifex-gex 那樣繞道 forward 定價。

2. **IV 直接用 yfinance 自帶值**,不用 brentq 反推 —— Yahoo 選擇權鏈的
   `impliedVolatility` 欄位是用中間價算好的,省掉一整套求解。

3. **GEX 符號慣例**(業界標準,SqueezeMetrics 同款):假設造市商 long call
   gamma、short put gamma:

   `GEX_strike = Σ ±(gamma × OI × 100 × S² × 1%)`(call 正、put 負)

4. **Gamma Flip** 用 sticky-strike 簡化:對一系列假設現貨價重算整條 GEX 曲線時,
   每個履約價的 IV 固定不動,只有現貨代入 gamma 公式重新算。曲線由負轉正的
   零交叉點(離現貨最近的一個)就是 Gamma Flip。

5. **Max Pain**:對每個實際掛牌履約價當假設結算價,算全部買方(call+put)到期
   可拿回的內含價值總額,找出讓這個總額最小的履約價。

6. **GEX 顯示範圍自動抓「有效範圍」**(`stock_gex.active_window`):到期日越近,
   gamma 集中在現貨附近的範圍越窄(gamma ∝ 1/√T 的直接後果)。0DTE 如果還套
   跟月選一樣的 ±30% 視窗,大半張圖會是空的。做法是先抓 `|GEX|` 超過全體最大值
   3% 的履約價當「有效範圍」,往外墊幾檔給衰減脈絡,再用 ±30% 當外框上限、
   ±6% 當下限。

---

## 資料來源與限制

| 用途 | 端點 |
|---|---|
| 選擇權鏈(履約價、OI、IV、bid/ask) | yfinance `Ticker(ticker).option_chain(expiry)` |
| 現貨價 | yfinance `Ticker(ticker).fast_info["lastPrice"]` |

- **只算單一到期日**,不跨月加總。
- **個股 OI 集中度高**:相較 SPY/QQQ 這類 ETF 有龐大穩定的市場參與者,個股少數
  大額部位就能讓相鄰履約價的 GEX 大幅跳動,屬正常現象。
- **盤前/盤後資料可能不完整**:OI 在美股開盤前有時還沒更新完成(可能顯示 0),
  IV 也可能是前一天收盤殘留值,建議在美股盤中查看較準。
- **yfinance 在 GitHub Actions 共用 runner IP 上偶爾會被 Yahoo 限流**,`build_dashboard.py`
  對每個 (標的, 到期日) 都有重試,且只有 ≥6 個標的成功才會覆寫網站——抓取品質
  不足時保留上一次的好版本,等下一個排程時段重試,不會讓網站變成空白或半殘。

---

## 自動更新

[`.github/workflows/daily.yml`](.github/workflows/daily.yml) 只在**台北時間週二~週六
早上**排三個時段(06:00 主要、08:30 / 11:00 備援 —— 台北週日/週一早上對應美股
週六/週日,沒有新交易日資料,不用跑。GitHub 的排程是 best-effort,錯開時段
+ 重試機制避免被延遲、丟掉,或被 Yahoo 限流卡住)。冪等設計:資料有實際內容
才會 commit,抓取失敗不會覆寫既有網站。

---

## 免責

本專案僅為公開資料的整理與計算,**不構成任何投資建議**。GEX 的正負號採業界標準
簡化假設(造市商 long call gamma、short put gamma),不是市場實際部位的直接觀測值。
資料來自 Yahoo Finance(經 yfinance)公開行情,正確性以官方/券商資料為準。
