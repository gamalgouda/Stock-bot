import yfinance as yf
import requests
import os
import pandas as pd

# ========= الإعدادات =========
STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN", "NFLX", "MSTR", "COIN", "PLTR"]
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
SHEET_CSV = os.getenv("SHEET_CSV")

ATR_MULT = 3.0

def send_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

# ========= 1. سكرينر =========
def check_stock(ticker):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        if len(df) < 210: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['SMA200'] = df['Close'].rolling(200).mean()
        df['Low20']  = df['Low'].rolling(20).min()
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift(1)).abs(),
            (df['Low']  - df['Close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()

        yest = df.iloc[-2]
        prev_high20 = df.iloc[-22:-2]['High'].max()

        is_breakout = yest['High'] > prev_high20
        is_fresh = True
        for i in range(3, 6):
            candle_high = df.iloc[-i]['High']
            high20_before = df.iloc[-i-20:-i]['High'].max()
            if candle_high > high20_before:
                is_fresh = False
                break
        above_sma200 = yest['Close'] > yest['SMA200']

        if is_breakout and is_fresh and above_sma200:
            return {
                "ticker": ticker,
                "atr": float(yest['ATR']),
                "low20": float(yest['Low20']),
                "date": str(df.index[-2].date())
            }
    except:
        return None
    return None

# ========= 2. قراءة الصفقات =========
def load_positions():
    if not SHEET_CSV:
        return []
    try:
        df = pd.read_csv(SHEET_CSV)
        df.columns = [c.strip() for c in df.columns]
        open_trades = df[df['Status'].astype(str).str.lower() == 'open']
        return open_trades.to_dict('records')
    except Exception as e:
        print(f"Sheet error: {e}")
        return []

# ========= 3. Chandelier =========
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
        return {
            "current": current,
            "chandelier": chandelier,
            "days": len(df)
        }
    except:
        return None

# ========= 4. بناء الرسالة =========
def build_message():
    positions = load_positions()
    pos_msg = "💼 *الصفقات المفتوحة:*\n"
    if not positions:
        pos_msg += "لا يوجد صفقات مفتوحة.\n"
    else:
        for p in positions:
            ticker = str(p.get('Ticker', '')).strip()
            entry_price = float(p.get('Entry_Price', 0))
            entry_date = str(p.get('Entry_Date', ''))
            if not ticker or entry_price <= 0:
                continue
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
    found = 0
    for t in STOCKS:
        res = check_stock(t)
        if res:
            found += 1
            screen_msg += (
                f"\n*{res['ticker']}* — اختراق {res['date']}\n"
                f"  Buy Stop @ High\n"
            )
    if found == 0:
        screen_msg += "مفيش فرص النهاردة."

    return pos_msg + "\n" + "─"*25 + screen_msg

if __name__ == "__main__":
    msg = f"📊 *تقرير يومي — {pd.Timestamp.now().date()}*\n\n"
    msg += build_message()
    send_msg(msg)
    print(msg)
