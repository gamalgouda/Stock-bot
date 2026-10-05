import yfinance as yf
import requests
import os
import pandas as pd
import numpy as np

# ========= الإعدادات =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
SHEET_CSV = os.getenv("SHEET_CSV")

ATR_MULT = 3.0
BREAKOUT_WINDOW = 20
FRESH_WINDOW = 20
REACTION_MIN = 4.0
MIN_PAST_SAMPLES = 3

def send_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        try:
            requests.post(url, data={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "Markdown"})
        except Exception as e:
            print(f"Telegram error: {e}")

# ========= 1. جلب قائمة S&P 500 =========
def get_sp500_tickers():
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    try:
        df = pd.read_csv(url)
        return df['Symbol'].str.replace('.', '-', regex=False).tolist()
    except Exception as e:
        print(f"S&P 500 fetch error: {e}")
        return []

# ========= 2. SPY Regime =========
def check_spy_regime():
    try:
        spy = yf.download("SPY", period="2y", interval="1d", progress=False, auto_adjust=True)
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)
        spy['SMA200'] = spy['Close'].rolling(200).mean()
        last_close = float(spy['Close'].iloc[-1])
        last_sma = float(spy['SMA200'].iloc[-1])
        return last_close > last_sma
    except:
        return False

# ========= 3. السكرينر =========
def run_screener():
    tickers = get_sp500_tickers()
    if not tickers:
        return []
    print(f"فحص {len(tickers)} سهم...")

    all_data = {}
    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            d = yf.download(batch, period="2y", interval="1d",
                          progress=False, auto_adjust=True,
                          group_by='ticker', threads=True)
            for s in batch:
                try:
                    if isinstance(d.columns, pd.MultiIndex):
                        if s in d.columns.get_level_values(0):
                            df_s = d[s].dropna()
                            if len(df_s) >= 230:
                                all_data[s] = df_s
                except:
                    continue
        except Exception as e:
            print(f"Batch error: {e}")

    print(f"تم تحميل {len(all_data)} سهم")

    candidates = []
    for ticker, df in all_data.items():
        try:
            closes = df['Close'].values
            highs = df['High'].values
            lows = df['Low'].values
            n = len(df)

            sma200 = closes[-201:-1].mean()
            h20 = highs[-21:-1].max()

            if closes[-1] <= h20: continue
            if closes[-1] < sma200: continue

            # Fresh breakout
            clean = True
            for k in range(2, 22):
                if closes[-k] > highs[-k-20:-k].max():
                    clean = False
                    break
            if not clean: continue

            # Reaction history
            reactions = []
            for j in range(200, n - 5):
                if closes[j] <= highs[j-20:j].max(): continue
                if closes[j] < closes[j-200:j].mean(): continue
                clean_j = True
                for k in range(1, 21):
                    idx = j - k
                    if idx - 20 < 0: continue
                    if closes[idx] > highs[idx-20:idx].max():
                        clean_j = False
                        break
                if clean_j:
                    entry_lvl = highs[j]
                    max_h5 = highs[j+1:j+6].max()
                    reactions.append((max_h5 - entry_lvl) / entry_lvl * 100)

            if len(reactions) < MIN_PAST_SAMPLES: continue
            recent = reactions[-10:]
            avg_reaction = float(np.mean(recent))
            if avg_reaction < REACTION_MIN: continue

            candidates.append({
                'ticker': ticker,
                'close': float(closes[-1]),
                'buy_stop': float(highs[-1]),
                'reaction': avg_reaction,
            })
        except:
            continue

    candidates.sort(key=lambda x: x['reaction'], reverse=True)
    return candidates

# ========= 4. قراءة الصفقات =========
def load_positions():
    if not SHEET_CSV: return []
    try:
        df = pd.read_csv(SHEET_CSV)
        df.columns = [c.strip() for c in df.columns]
        return df[df['Status'].astype(str).str.lower() == 'open'].to_dict('records')
    except Exception as e:
        print(f"Sheet error: {e}")
        return []

# ========= 5. Chandelier =========
def calc_chandelier(ticker, entry_date):
    try:
        df = yf.download(ticker, start=entry_date, interval="1d", progress=False, auto_adjust=True)
        if len(df) < 15: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        highest = float(df['High'].max())
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift(1)).abs(),
            (df['Low']  - df['Close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])
        current = float(df['Close'].iloc[-1])
        chandelier = highest - ATR_MULT * atr14
        return {"current": current, "chandelier": chandelier, "days": len(df)}
    except:
        return None

# ========= 6. بناء الرسالة =========
def build_message():
    regime_ok = check_spy_regime()

    header = f"📊 *تقرير يومي — {pd.Timestamp.now().date()}*\n\n"
    header += "🌍 السوق: 🟢 SPY فوق SMA200\n" if regime_ok else "🌍 السوق: 🔴 SPY تحت SMA200 — لا صفقات جديدة\n"

    positions = load_positions()
    pos_msg = "\n💼 *الصفقات المفتوحة:*\n"
    if not positions:
        pos_msg += "لا يوجد صفقات مفتوحة.\n"
    else:
        for p in positions:
            ticker = str(p.get('Ticker', '')).strip()
            entry_price = float(p.get('Entry_Price', 0))
            entry_date = str(p.get('Entry_Date', ''))
            if not ticker or entry_price <= 0: continue
            ch = calc_chandelier(ticker, entry_date)
            if not ch:
                pos_msg += f"\n❌ *{ticker}* — تعذر جلب البيانات\n"
                continue
            pnl = (ch['current'] - entry_price) / entry_price * 100
            dist = (ch['current'] - ch['chandelier']) / ch['current'] * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            warn = " ⚠️" if dist < 3 else ""
            pos_msg += (
                f"\n{emoji} *{ticker}*{warn}\n"
                f"  دخول: {entry_price:.2f}\n"
                f"  حالي: {ch['current']:.2f} ({pnl:+.2f}%)\n"
                f"  🛑 Chandelier: *{ch['chandelier']:.2f}*\n"
                f"  مسافة: {dist:.2f}%\n"
                f"  أيام: {ch['days']}\n"
            )

    screen_msg = "\n🎯 *مرشحين اليوم:*\n"
    if not regime_ok:
        screen_msg += "🔴 السوق تحت SMA200 — لا مرشحين.\n"
    else:
        candidates = run_screener()
        if not candidates:
            screen_msg += "مفيش فرص النهاردة.\n"
        else:
            for c in candidates[:15]:
                dist_pct = (c['buy_stop'] - c['close']) / c['close'] * 100
                screen_msg += (
                    f"\n*{c['ticker']}*\n"
                    f"  إغلاق: {c['close']:.2f}\n"
                    f"  🔵 Buy Stop @ {c['buy_stop']:.2f}\n"
                    f"  (من الإغلاق: +{dist_pct:.2f}%)\n"
                    f"  Reaction: {c['reaction']:.2f}%\n"
                )
            if len(candidates) > 15:
                screen_msg += f"\n_+{len(candidates)-15} مرشح آخر_\n"

    return header + pos_msg + "\n" + "─"*25 + screen_msg

if __name__ == "__main__":
    msg = build_message()
    send_msg(msg)
    print(msg)
