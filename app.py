from flask import Flask, request
import requests
import os

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_data(as_text=True)
    # اللي جاي من TradingView
    msg = f"🔥 تجميع EGX\n\n{data}"
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    return "ok"

@app.route('/')
def home():
    return "TradingView webhook شغال"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
