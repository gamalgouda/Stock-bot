# حط هنا التوكن الجديد والـ ID
BOT_TOKEN = "7934754458:AAH5GmtDM4lwLtjVGS9glfwXMgtsOwhBCs0"
CHAT_ID = "5443864893"
import requests, yfinance as yf
from datetime import datetime
import pytz

STOCKS = ["AAPL", "NVDA", "TSLA", "AMD", "MSFT", "SPY", "QQQ"]

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def check_stocks():
    result = "📊 *تقرير افتتاح امريكا 4:30 بتوقيت مصر:*\n\n"
    found = False
    for s in STOCKS:
        try:
            ticker = yf.Ticker(s)
            df = ticker.history(period="2d")
            if len(df) < 2: continue
            last = df['Close'].iloc[-1]
            prev = df['Close'].iloc[-2]
            change = (last - prev) / prev * 100
            if change > 1:
                result += f"🚀 {s}: +{change:.2f}% - {last:.2f}$\n"
                found = True
        except: pass
    if not found:
        result += "مفيش اسهم عاملة Gap عالي النهاردة"
    send(result)

check_stocks()
