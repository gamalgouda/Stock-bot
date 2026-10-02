import yfinance as yf
import requests
import os

# ========= اعداداتك =========
RISK_PER_TRADE = 30  # خسارة 30$ في الصفقة
SL_PCT = 0.07  # وقف 7%
TP_PCT = 0.15  # هدف 15%
STOCKS = ["AAPL","MSFT","NVDA","TSLA","AMD","META","GOOGL","AMZN","NFLX","MSTR","COIN","PLTR"]

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

msg = "📈 تقرير سوينج بعد الاغلاق - دخول بكرة\n\n"

found = 0
for ticker in STOCKS:
    try:
        data = yf.Ticker(ticker).history(period="5d")
        if len(data) < 2: continue
        
        last = data.iloc[-1]
        prev = data.iloc[-2]
        
        # فلتر سوينج: حجم عالي + قفل فوق 1%
        if last['Volume'] < prev['Volume'] * 1.2: continue
        if last['Close'] < prev['Close'] * 1.01: continue
        
        high_yest = last['High']
        entry = round(high_yest * 1.005, 2)  # دخول = هاي امبارح + 0.5%
        sl = round(entry * (1 - SL_PCT), 2)
        tp = round(entry * (1 + TP_PCT), 2)
        
        risk_per_share = entry - sl
        qty = int(RISK_PER_TRADE / risk_per_share) if risk_per_share > 0 else 0
        if qty == 0: continue
        
        found += 1
        msg += f"🔹 {ticker}\nدخول: ${entry} (اختراق {high_yest:.2f})\nوقف: ${sl} (-7%)\nهدف: ${tp} (+15%)\nالكمية: {qty} سهم (ريسك ~${RISK_PER_TRADE})\n\n"
    except: continue

if found == 0:
    msg += "مفيش فرص قوية بكرة، ارتاح."

send_msg(msg)
