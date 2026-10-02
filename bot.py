import yfinance as yf
import requests
import os
import pandas as pd

# ========= اعداداتك =========
STOCKS = ["AAPL","MSFT","NVDA","TSLA","AMD","META","GOOGL","AMZN","NFLX","MSTR","COIN","PLTR"]
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

def check_stock(ticker):
    df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
    if len(df) < 210: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

    df['SMA200'] = df['Close'].rolling(200).mean()
    df['Low20'] = df['Low'].rolling(20).min()
    tr = pd.concat([(df['High']-df['Low']), (df['High']-df['Close'].shift(1)).abs(), (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    yest = df.iloc[-2]
    prev_high20 = df.iloc[-22:-2]['High'].max()

    # الشرط 1: اختراق 20 يوم
    is_breakout = yest['High'] > prev_high20

    # الشرط 2: Fresh - اخر 3 شمعات مكنش فيهم كسر
    is_fresh = True
    for i in range(3, 6):
        candle_high = df.iloc[-i]['High']
        high20_before_candle = df.iloc[-i-20:-i]['High'].max()
        if candle_high > high20_before_candle:
            is_fresh = False
            break

    # الشرط 3: فوق SMA200
    above_sma200 = yest['Close'] > yest['SMA200']

    if is_breakout and is_fresh and above_sma200:
        return {
            "ticker": ticker,
            "atr": float(yest['ATR']),
            "low20": float(yest['Low20']),
            "date": str(df.index[-2].date())
        }
    return None

msg = f"🔔 *Fresh Breakout 3 Days - دخول اليوم*\n📅 {pd.Timestamp.now().date()}\n\n"
found = 0
for t in STOCKS:
    try:
        res = check_stock(t)
        if res:
            found += 1
            msg += f"🔹 *{res['ticker']}* - اختراق {res['date']}\n"
            msg += f"دخول: Market Open اليوم\n"
            msg += f"وقف: 3×ATR = {res['atr']*3:.2f}$ تحت الدخول\n"
            msg += f"خروج: اقفال تحت Low20 = ${res['low20']:.2f}\n\n"
    except: continue

if found == 0:
    msg += "💤 مفيش فرص Fresh النهاردة."

send_msg(msg)
