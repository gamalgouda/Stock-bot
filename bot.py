import yfinance as yf
import requests
import os
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

# ========= الإعدادات =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
SHEET_CSV = os.getenv("SHEET_CSV")

# إعدادات الاستراتيجية
LOOKBACK          = 10      # clean breakdown lookback
PIVOT_LOOKBACK    = 30      # range lookback
ENTRY_WINDOW      = 5       # صلاحية الأوردر (أيام تداول)
REACTION_LOOKBACK = 250     # عدد الأيام لحساب reactions
MIN_PAST_SAMPLES  = 3       # أدنى عدد reactions
REACTION_MIN      = 4.0     # نسبة reaction الدنيا
ENTRY_OFF         = 0.15    # Buy Limit = close - 0.15 × range
SL_MULT           = 3.0     # SL = entry - 3 × ATR
TP_MULT           = 3.0     # TP = entry + 3 × ATR
MAX_HOLD          = 60      # أقصى مدة للصفقة (أيام تداول)


# ========= إرسال تليجرام =========
def send_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        try:
            requests.post(url, data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown"
            })
        except Exception as e:
            print(f"Telegram error: {e}")


# ========= S&P 500 Tickers =========
def get_sp500_tickers():
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    try:
        df = pd.read_csv(url)
        return df['Symbol'].str.replace('.', '-', regex=False).tolist()
    except Exception as e:
        print(f"S&P 500 fetch error: {e}")
        return []


# ========= SPY Regime =========
def check_spy_regime():
    try:
        spy = yf.download("SPY", period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)
        spy['SMA200'] = spy['Close'].rolling(200).mean()
        return float(spy['Close'].iloc[-1]) > float(spy['SMA200'].iloc[-1])
    except:
        return False


# ========= Screener: Clean Breakdown + Reaction + Range =========
def run_screener():
    tickers = get_sp500_tickers()
    if not tickers:
        return []

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
                            if len(df_s) >= 260:
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
            if n < 260:
                continue

            sma200 = pd.Series(closes).rolling(200).mean().values
            if np.isnan(sma200[-1]) or closes[-1] < sma200[-1]:
                continue

            # ATR(14)
            prev_c = np.roll(closes, 1); prev_c[0] = closes[0]
            tr = np.maximum.reduce([
                highs - lows,
                np.abs(highs - prev_c),
                np.abs(lows - prev_c)
            ])
            atr = pd.Series(tr).rolling(14).mean().values
            if np.isnan(atr[-1]) or atr[-1] <= 0:
                continue

            i = n - 1  # آخر شمعة

            # 1) Breakdown
            if i - LOOKBACK < 0:
                continue
            if closes[i] >= lows[i-LOOKBACK:i].min():
                continue

            # 2) Clean breakdown
            clean = True
            for k in range(1, LOOKBACK + 1):
                idxk = i - k
                if idxk - LOOKBACK < 0:
                    continue
                if closes[idxk] < lows[idxk-LOOKBACK:idxk].min():
                    clean = False
                    break
            if not clean:
                continue

            # 3) Reaction filter
            reactions = []
            for j in range(200, n - ENTRY_WINDOW):
                if closes[j] <= highs[j-LOOKBACK:j].max():
                    continue
                if closes[j] < sma200[j]:
                    continue
                clean_j = True
                for k in range(1, LOOKBACK + 1):
                    idxj = j - k
                    if idxj - LOOKBACK < 0:
                        continue
                    if closes[idxj] > highs[idxj-LOOKBACK:idxj].max():
                        clean_j = False
                        break
                if clean_j:
                    el = highs[j]
                    mh = highs[j+1:j+1+ENTRY_WINDOW].max()
                    reactions.append((mh - el) / el * 100)

            if len(reactions) < MIN_PAST_SAMPLES:
                continue
            avg_reaction = float(np.mean(reactions[-10:]))
            if avg_reaction < REACTION_MIN:
                continue

            # 4) Range
            window_highs = highs[i-LOOKBACK:i]
            if len(window_highs) < LOOKBACK:
                continue
            h_off = np.argmax(window_highs[::-1])
            h_idx = i - 1 - h_off
            start = h_idx - PIVOT_LOOKBACK + 1
            if start < 0:
                continue
            range_low = lows[start:h_idx+1].min()
            range_high = highs[h_idx]
            rng = range_high - range_low
            if rng <= 0:
                continue

            # 5) Entry, SL, TP
            buy_limit = closes[i] - ENTRY_OFF * rng
            if buy_limit <= 0:
                continue
            sl = buy_limit - SL_MULT * atr[i]
            tp = buy_limit + TP_MULT * atr[i]
            if sl <= 0:
                continue

            rr = (tp - buy_limit) / (buy_limit - sl)
            atr_pct = atr[i] / closes[i] * 100
            range_pct = rng / closes[i] * 100

            candidates.append({
                'ticker': ticker,
                'close': float(closes[i]),
                'buy_limit': float(buy_limit),
                'sl': float(sl),
                'tp': float(tp),
                'rr': float(rr),
                'atr_pct': float(atr_pct),
                'range_pct': float(range_pct),
                'reaction': avg_reaction,
                'signal_date': df.index[i].strftime('%Y-%m-%d'),
            })
        except Exception as e:
            continue

    candidates.sort(key=lambda x: x['reaction'], reverse=True)
    return candidates


# ========= قراءة الـJournal =========
def load_journal():
    if not SHEET_CSV:
        return pd.DataFrame()
    try:
        df = pd.read_csv(SHEET_CSV)
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception as e:
        print(f"Sheet error: {e}")
        return pd.DataFrame()


# ========= تحليل WAITING orders =========
def analyze_waiting(df):
    if len(df) == 0:
        return []
    waiting = df[df['Status'].astype(str).str.strip().str.lower() == 'waiting']
    results = []

    for _, row in waiting.iterrows():
        ticker = str(row['Ticker']).strip()
        try:
            signal_date = pd.Timestamp(row['Signal_Date'])
            buy_limit = float(row['Buy_Limit'])
            sl = float(row['SL'])
            tp = float(row['TP'])
        except:
            continue

        try:
            d = yf.download(ticker, start=signal_date.strftime('%Y-%m-%d'),
                            interval="1d", progress=False, auto_adjust=True)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
        except:
            continue

        if len(d) < 1:
            continue

        # عدد أيام التداول بعد الإشارة (بدون شمعة الإشارة نفسها)
        trading_days_since = len(d) - 1

        # هل السعر لمس Buy_Limit بعد الإشارة؟
        d_after = d.iloc[1:]
        touched = bool((d_after['Low'] <= buy_limit).any()) if len(d_after) > 0 else False
        current = float(d['Close'].iloc[-1])

        if touched:
            status = 'touched'
            days_left = 0
        elif trading_days_since >= ENTRY_WINDOW:
            status = 'expired'
            days_left = 0
        else:
            status = 'waiting'
            days_left = ENTRY_WINDOW - trading_days_since

        dist_to_limit = (current - buy_limit) / current * 100

        results.append({
            'ticker': ticker,
            'buy_limit': buy_limit,
            'sl': sl,
            'tp': tp,
            'current': current,
            'signal_date': signal_date.strftime('%Y-%m-%d'),
            'days_since': trading_days_since,
            'days_left': days_left,
            'status': status,
            'dist_to_limit': dist_to_limit,
        })

    return results


# ========= تحليل OPEN positions =========
def analyze_open(df):
    if len(df) == 0:
        return []
    open_pos = df[df['Status'].astype(str).str.strip().str.lower() == 'open']
    results = []

    for _, row in open_pos.iterrows():
        ticker = str(row['Ticker']).strip()
        try:
            entry_date = pd.Timestamp(row['Entry_Date'])
            entry_price = float(row['Entry_Price'])
            sl = float(row['SL'])
            tp = float(row['TP'])
        except:
            continue

        try:
            d = yf.download(ticker, start=entry_date.strftime('%Y-%m-%d'),
                            interval="1d", progress=False, auto_adjust=True)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
        except:
            continue

        if len(d) < 1:
            continue

        trading_days_open = len(d) - 1

        hit_tp = bool((d['High'] >= tp).any())
        hit_sl = bool((d['Low'] <= sl).any())
        current = float(d['Close'].iloc[-1])
        pnl = (current - entry_price) / entry_price * 100

        if hit_sl and hit_tp:
            status = 'both_hit'
        elif hit_sl:
            status = 'sl_hit'
        elif hit_tp:
            status = 'tp_hit'
        elif trading_days_open >= MAX_HOLD:
            status = 'timeout'
        else:
            status = 'open'

        dist_tp = (tp - current) / current * 100
        dist_sl = (current - sl) / current * 100

        results.append({
            'ticker': ticker,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp,
            'current': current,
            'entry_date': entry_date.strftime('%Y-%m-%d'),
            'days_open': trading_days_open,
            'days_left': max(0, MAX_HOLD - trading_days_open),
            'pnl_pct': pnl,
            'dist_tp': dist_tp,
            'dist_sl': dist_sl,
            'status': status,
        })

    return results


# ========= Stock Rankings =========
def compute_rankings(df):
    if len(df) == 0:
        return []

    closed = df[df['Status'].astype(str).str.strip().str.lower() == 'closed'].copy()
    if len(closed) == 0:
        return []

    # احسب PnL_% لو ناقص
    if 'PnL_%' not in closed.columns or closed['PnL_%'].isna().all():
        def calc_pnl(row):
            try:
                e = float(row['Entry_Price'])
                x = float(row['Exit_Price'])
                if e <= 0:
                    return np.nan
                return (x - e) / e * 100
            except:
                return np.nan
        closed['PnL_%'] = closed.apply(calc_pnl, axis=1)

    closed['PnL_%'] = pd.to_numeric(closed['PnL_%'], errors='coerce')
    closed = closed.dropna(subset=['PnL_%'])
    if len(closed) == 0:
        return []

    rankings = []
    for ticker, group in closed.groupby('Ticker'):
        pnls = group['PnL_%'].values
        trades = len(pnls)
        wins = int((pnls > 0).sum())
        losses = int((pnls < 0).sum())
        wr = wins / trades * 100 if trades > 0 else 0
        avg_win = float(pnls[pnls > 0].mean()) if wins > 0 else 0.0
        avg_loss = float(pnls[pnls < 0].mean()) if losses > 0 else 0.0
        expectancy = (wr / 100 * avg_win) + ((1 - wr / 100) * avg_loss)
        score = expectancy * np.sqrt(trades)
        rankings.append({
            'ticker': ticker,
            'trades': trades,
            'wins': wins,
            'losses': losses,
            'wr': wr,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'expectancy': expectancy,
            'score': score,
            'total_pnl': float(pnls.sum()),
        })

    rankings.sort(key=lambda x: x['score'], reverse=True)
    return rankings


# ========= بناء الرسالة =========
def build_message():
    egypt_tz = ZoneInfo("Africa/Cairo")
    today_str = datetime.now(egypt_tz).strftime('%Y-%m-%d')

    header = f"📊 *تقرير الإغلاق — {today_str}*\n\n"

    regime_ok = check_spy_regime()
    header += "🌍 السوق: 🟢 SPY فوق SMA200\n" if regime_ok else "🌍 السوق: 🔴 SPY تحت SMA200\n"

    journal = load_journal()

    # ===== WAITING =====
    waiting_msg = "\n⏳ *صفقات في الانتظار:*\n"
    if len(journal) == 0:
        waiting_msg += "_الـJournal فاضي._\n"
    else:
        waiting_list = analyze_waiting(journal)
        if not waiting_list:
            waiting_msg += "_مفيش صفقات في الانتظار._\n"
        else:
            for w in waiting_list:
                if w['status'] == 'touched':
                    icon = "🎯"
                    extra = "← اتنفذت! حدّث الـSheet"
                elif w['status'] == 'expired':
                    icon = "❌"
                    extra = "← صلاحية انتهت، الغيها"
                else:
                    icon = "⏳"
                    extra = f"← باقي {w['days_left']} يوم"

                waiting_msg += (
                    f"\n{icon} *{w['ticker']}*  ({w['days_since']}d منذ الإشارة)\n"
                    f"  🔵 Buy Limit: `{w['buy_limit']:.2f}`\n"
                    f"  🛑 SL: `{w['sl']:.2f}`  |  🎯 TP: `{w['tp']:.2f}`\n"
                    f"  حالي: `{w['current']:.2f}`  (يبعد {w['dist_to_limit']:+.2f}%)\n"
                    f"  {extra}\n"
                )

    # ===== OPEN =====
    open_msg = "\n💼 *صفقات مفتوحة:*\n"
    if len(journal) == 0:
        open_msg += "—\n"
    else:
        open_list = analyze_open(journal)
        if not open_list:
            open_msg += "_مفيش صفقات مفتوحة._\n"
        else:
            for o in open_list:
                if o['status'] == 'tp_hit':
                    icon = "✅"
                    extra = "← ضربت الهدف!"
                elif o['status'] == 'sl_hit':
                    icon = "🛑"
                    extra = "← ضربت الستوب!"
                elif o['status'] == 'both_hit':
                    icon = "⚠️"
                    extra = "← ضربت TP و SL — راجع يدويًا"
                elif o['status'] == 'timeout':
                    icon = "🕐"
                    extra = f"← عدّت {MAX_HOLD} يوم — اقفلها"
                else:
                    icon = "🟢" if o['pnl_pct'] >= 0 else "🔴"
                    extra = ""

                pnl_icon = "🟢" if o['pnl_pct'] >= 0 else "🔴"
                open_msg += (
                    f"\n{icon} *{o['ticker']}*  ({o['days_open']}d)\n"
                    f"  دخول: `{o['entry_price']:.2f}`\n"
                    f"  حالي: `{o['current']:.2f}`  {pnl_icon} ({o['pnl_pct']:+.2f}%)\n"
                    f"  🛑 SL: `{o['sl']:.2f}` (يبعد {o['dist_sl']:+.2f}%)\n"
                    f"  🎯 TP: `{o['tp']:.2f}` (يبعد {o['dist_tp']:+.2f}%)\n"
                )
                if extra:
                    open_msg += f"  {extra}\n"

    # ===== SCREENER =====
    screen_msg = "\n🎯 *مرشحين جدد:*\n"
    if not regime_ok:
        screen_msg += "🔴 *SPY تحت SMA200 — الاستراتيجية متوقفة.*\n"
    else:
        candidates = run_screener()
        if not candidates:
            screen_msg += "_مفيش فرص جديدة._\n"
        else:
            for c in candidates[:10]:
                screen_msg += (
                    f"\n*{c['ticker']}*   _Reaction: {c['reaction']:.1f}%_\n"
                    f"  إغلاق: `{c['close']:.2f}`\n"
                    f"  🔵 Buy Limit: `{c['buy_limit']:.2f}`\n"
                    f"  🛑 SL: `{c['sl']:.2f}`\n"
                    f"  🎯 TP: `{c['tp']:.2f}`   (R:R {c['rr']:.1f})\n"
                    f"  ATR: {c['atr_pct']:.1f}%  |  Range: {c['range_pct']:.1f}%\n"
                )
            if len(candidates) > 10:
                screen_msg += f"\n_+{len(candidates)-10} مرشح آخر_\n"

    # ===== RANKINGS =====
    rank_msg = "\n📊 *ترتيب الأسهم:*\n"
    rankings = compute_rankings(journal) if len(journal) > 0 else []
    if not rankings:
        rank_msg += "_مفيش صفقات مقفولة بعد._\n"
    else:
        rank_msg += "` # Ticker   Tr  WR   Avg    Score`\n"
        for i, r in enumerate(rankings[:15], 1):
            rank_msg += (
                f"`{i:>2} {r['ticker']:<7} {r['trades']:>3} {r['wr']:>3.0f}% "
                f"{r['expectancy']:>+5.2f}% {r['score']:>5.2f}`\n"
            )

    # ===== STATS =====
    stats_msg = "\n📈 *إحصائيات:*\n"
    if len(journal) > 0:
        closed = journal[
            journal['Status'].astype(str).str.strip().str.lower() == 'closed'
        ].copy()
        if len(closed) > 0:
            if 'PnL_%' not in closed.columns or closed['PnL_%'].isna().all():
                def calc_pnl(row):
                    try:
                        e = float(row['Entry_Price'])
                        x = float(row['Exit_Price'])
                        if e <= 0:
                            return np.nan
                        return (x - e) / e * 100
                    except:
                        return np.nan
                closed['PnL_%'] = closed.apply(calc_pnl, axis=1)
            closed['PnL_%'] = pd.to_numeric(closed['PnL_%'], errors='coerce')
            closed = closed.dropna(subset=['PnL_%'])
            n_valid = len(closed)
            if n_valid > 0:
                wins = int((closed['PnL_%'] > 0).sum())
                losses = int((closed['PnL_%'] < 0).sum())
                wr = wins / n_valid * 100
                stats_msg += (
                    f"  Total: *{n_valid}*  |  Wins: {wins}  |  Losses: {losses}\n"
                    f"  WR: *{wr:.1f}%*\n"
                    f"  Avg: {closed['PnL_%'].mean():+.2f}%\n"
                    f"  Sum: {closed['PnL_%'].sum():+.1f}%\n"
                )
            else:
                stats_msg += "_مفيش PnL محسوب._\n"
        else:
            stats_msg += "_مفيش صفقات مقفولة بعد._\n"

    sep = "\n" + "─" * 25 + "\n"
    return (
        header +
        waiting_msg +
        open_msg +
        sep + screen_msg +
        sep + rank_msg +
        stats_msg
    )


if __name__ == "__main__":
    msg = build_message()
    send_msg(msg)
    print(msg)
