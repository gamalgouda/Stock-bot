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
    # ATR 14
    tr = pd.concat([(df['High']-df['Low']), (df['High']-df['Close'].shift(1)).abs(), (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    yest = df.iloc[-2] # شمعة الاختراق
    prev_high20 = df.iloc[-22:-2]['High'].max() # اعلى هاي 20 يوم قبلها
    prev_was_breakout = df.iloc[-3]['High'] > df.iloc[-23:-3]['High'].max()

    # الشرط الجديد بتاعك
    is_breakout = yest['High'] > prev_high20
    is_fresh = not prev_was_breakout
    above_sma200 = yest['Close'] > yest['SMA200']

    if is_breakout and is_fresh and above_sma200:
        return {
            "ticker": ticker,
            "atr": float(yest['ATR']),
            "low20": float(yest['Low20']),
            "date": str(df.index[-2].date())
        }
    return None

msg = f"🔔 *سكرينر Fresh Breakout 20D - دخول اليوم*\n📅 {pd.Timestamp.now().date()}\nالشروط: اختراق fresh + فوق SMA200\n\n"
found = 0
for t in STOCKS:
    try:
        res = check_stock(t)
        if res:
            found += 1
            msg += f"🔹 *{res['ticker']}* - اختراق {res['date']}\n"
            msg += f"دخول: بسعر الافتتاح اليوم Market Open\n"
            msg += f"وقف: 3×ATR = {res['atr']*3:.2f}$ تحت الدخول\n"
            msg += f"خروج: اقفال تحت Low20 = ${res['low20']:.2f}\n\n"
    except: continue

if found == 0:
    msg += "💤 مفيش اختراقات fresh النهاردة، ارتاح."

send_msg(msg)
