import requests
import json
import os
import time
import random
import logging
import threading
import math
from datetime import datetime, timezone
from collections import Counter

# -------------------- Configuration --------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8627473964:AAGn2XACu_yF99_P7mYvLErlbOndK31wsvI")
OWNER_ID = int(os.environ.get("OWNER_ID", "8473134685"))

# API URLs
WINGO_30S_API  = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
WINGO_1MIN_API = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

# -------------------- Database (JSON file) --------------------
class Database:
    def __init__(self, filename="database.json"):
        self.filename = filename
        self.lock = threading.Lock()
        self.data = {}
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            with open(self.filename, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}
            self.save()

    def save(self):
        with self.lock:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put(self, key, value):
        self.data[key] = value
        self.save()

    def delete(self, key):
        if key in self.data:
            del self.data[key]
            self.save()

    def get_json(self, key, default=None):
        val = self.get(key)
        if val is None:
            return default
        try:
            return json.loads(val)
        except:
            return default

    def put_json(self, key, value):
        self.put(key, json.dumps(value, ensure_ascii=False))

# -------------------- Telegram API Helpers --------------------
def telegram_request(method, payload, bot_token=BOT_TOKEN, req_timeout=15):
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=req_timeout)
        raw = r.text.strip() if r.content else ""
        if not raw:
            return {"ok": False}
        return r.json()
    except requests.exceptions.Timeout:
        logging.warning(f"Telegram API timeout [{method}]")
        return {"ok": False}
    except Exception as e:
        logging.error(f"Telegram API error [{method}]: {e}")
        return {"ok": False}

def send_message(chat_id, text, parse_mode=None, reply_markup=None, bot_token=BOT_TOKEN):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_request("sendMessage", payload, bot_token)

def edit_message_text(chat_id, message_id, text, parse_mode=None, reply_markup=None, bot_token=BOT_TOKEN):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_request("editMessageText", payload, bot_token)

def send_sticker(chat_id, file_id, bot_token=BOT_TOKEN):
    return telegram_request("sendSticker", {"chat_id": chat_id, "sticker": file_id}, bot_token)

def answer_callback_query(callback_query_id, text=None, bot_token=BOT_TOKEN):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return telegram_request("answerCallbackQuery", payload, bot_token)

# -------------------- Core Logic --------------------
def check_membership(user_id, db, bot_token):
    channels = db.get_json("CONFIG:CHANNELS", [])
    if not channels:
        return True
    for ch in channels:
        res = telegram_request("getChatMember", {"chat_id": ch["id"], "user_id": user_id}, bot_token)
        if not res.get("ok"):
            return False
        if res["result"].get("status") in ("left", "kicked"):
            return False
    return True

def get_balance(user_id, db):
    return int(db.get(f"BAL:{user_id}", 0))

def add_balance(user_id, amount, db):
    current = get_balance(user_id, db)
    db.put(f"BAL:{user_id}", str(current + amount))

def get_total_signals(user_id, db):
    return int(db.get(f"SIG:{user_id}", 0))

def increment_total_signals(user_id, db):
    db.put(f"SIG:{user_id}", str(get_total_signals(user_id, db) + 1))

def initialize_user(user_id, first_name, db):
    if db.get(f"USER_INIT:{user_id}") is None:
        db.put(f"USER_INIT:{user_id}", "1")
        users = db.get_json("ALL_USERS", [])
        if user_id not in users:
            users.append(user_id)
            db.put_json("ALL_USERS", users)
        db.put(f"BAL:{user_id}", "0")
        db.put(f"SIG:{user_id}", "0")

def process_referral_reward(user_id, db, bot_token):
    referrer_id = db.get(f"REFERRER:{user_id}")
    if not referrer_id or db.get(f"REF_REWARD:{user_id}"):
        return
    reward = int(db.get("CONFIG:REF_REWARD") or 25)
    add_balance(referrer_id, reward, db)
    db.put(f"REF_REWARD:{user_id}", "true")
    send_message(referrer_id,
                 f"🤖 *New Referral Completed!*\n\n✅ Your friend joined all channels!\n💰 You received `{reward}` coins!",
                 "Markdown", bot_token=bot_token)

def send_force_join_message(chat_id, db, bot_token):
    channels = db.get_json("CONFIG:CHANNELS", [])
    buttons = [[{"text": "♻ 𝗝𝗢𝗜𝗡 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 ♻", "url": ch["link"]}] for ch in channels]
    send_message(chat_id,
                 "🤖 *আপনি আমাদের Channel/Group এ জয়েন নেই* ❌, _তাই অবশ্যই জয়েন হতে হবে।_",
                 "Markdown", {"inline_keyboard": buttons}, bot_token)
    send_message(chat_id, "👇 জয়েন করার পর নিচের বাটনে ক্লিক করুন 👇",
                 reply_markup={"keyboard": [[{"text": "✅ CHECK JOINED"}]], "resize_keyboard": True, "one_time_keyboard": True},
                 bot_token=bot_token)

def send_main_menu(chat_id, bot_token):
    keyboard = {
        "keyboard": [
            [{"text": "❇️ 𝗪𝗜𝗡𝗚𝗢 𝗦𝗜𝗚𝗡𝗔𝗟 ❇️"}, {"text": "👤 𝗣𝗥𝗢𝗙𝗜𝗟𝗘"}],
            [{"text": "🧑‍🍼 𝗥𝗘𝗙𝗘𝗥𝗥𝗘𝗗"}],
            [{"text": "📥 𝗥𝗘𝗗𝗘𝗘𝗠 𝗖𝗢𝗗𝗘"}, {"text": "ℹ️ 𝗜𝗡𝗙𝗢"}],
            [{"text": "🧑‍💻 𝗛𝗘𝗟𝗣 𝗔𝗡𝗗 𝗦𝗨𝗣𝗣𝗢𝗥𝗧"}]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "👇 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨 👇", reply_markup=keyboard, bot_token=bot_token)

def check_join_and_start(chat_id, user_id, first_name, db, bot_token):
    if user_id == OWNER_ID:
        send_main_menu(chat_id, bot_token)
        return
    if check_membership(user_id, db, bot_token):
        process_referral_reward(user_id, db, bot_token)
        send_message(chat_id, "🤖 `আপনাকে আমাদের সিগনাল বটে স্বাগতম 🎉`", "MarkdownV2", bot_token=bot_token)
        send_main_menu(chat_id, bot_token)
    else:
        send_force_join_message(chat_id, db, bot_token)

# ==================== PERIOD CALCULATION ====================
def get_period_info(game_type):
    """Auto-calculate current period ID and time remaining"""
    now = datetime.now(timezone.utc)
    year  = now.strftime("%Y")
    month = now.strftime("%m")
    day   = now.strftime("%d")
    hours   = now.hour
    minutes = now.minute
    seconds = now.second

    if game_type == "GAME_30S":
        total_minutes   = hours * 60 + minutes
        period_in_minute = 1 if seconds < 30 else 2
        period_number    = total_minutes * 2 + period_in_minute
        period_id        = f"{year}{month}{day}10005{str(period_number).zfill(4)}"
        seconds_remaining = 30 - (seconds % 30)
        total_seconds     = 30
    else:  # 1MIN
        total_minutes   = hours * 60 + minutes
        period_number    = 10001 + total_minutes
        period_id        = f"{year}{month}{day}1000{period_number}"
        seconds_remaining = 60 - seconds
        total_seconds     = 60

    return period_id, seconds_remaining, total_seconds

# ==================== API DATA FETCHING ====================
def fetch_history(game_type, count=100):
    """Fetch historical results from WinGo API"""
    url = WINGO_30S_API if game_type == "GAME_30S" else WINGO_1MIN_API
    try:
        r = requests.get(url, params={"pageNo": 1, "pageSize": count}, timeout=10)
        raw = r.text.strip() if r.content else ""
        if not raw:
            logging.error("fetch_history: empty response from API")
            return []
        try:
            data = r.json()
        except Exception as je:
            logging.error(f"fetch_history: JSON parse error: {je} | body: {raw[:120]}")
            return []
        items = []
        if isinstance(data, dict):
            d = data.get("data", data)
            if isinstance(d, dict):
                items = d.get("list", d.get("records", d.get("data", [])))
            elif isinstance(d, list):
                items = d
        elif isinstance(data, list):
            items = data

        results = []
        for item in items:
            try:
                raw = item.get("number", item.get("winningNumber", item.get("result", 0)))
                num = int(str(raw).strip())
                results.append({
                    "number": num,
                    "result": "BIG" if num >= 5 else "SMALL",
                    "period": str(item.get("issueNumber", item.get("period", item.get("periodNumber", ""))))
                })
            except:
                continue
        return results
    except Exception as e:
        logging.error(f"API fetch error: {e}")
        return []

def check_period_result(game_type, period_id, retries=10):
    """Poll API until the given period appears in results"""
    url = WINGO_30S_API if game_type == "GAME_30S" else WINGO_1MIN_API
    for attempt in range(retries):
        time.sleep(4)
        try:
            r = requests.get(url, params={"pageNo": 1, "pageSize": 20}, timeout=10)
            raw = r.text.strip() if r.content else ""
            if not raw:
                logging.warning(f"check_period_result attempt {attempt+1}: empty response, retrying...")
                continue
            try:
                data = r.json()
            except Exception as je:
                logging.warning(f"check_period_result attempt {attempt+1}: JSON error: {je} | body: {raw[:80]}")
                continue
            items = []
            if isinstance(data, dict):
                d = data.get("data", data)
                items = d.get("list", d.get("records", [])) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            elif isinstance(data, list):
                items = data
            for item in items:
                item_period = str(item.get("issueNumber", item.get("period", item.get("periodNumber", ""))))
                if item_period == str(period_id):
                    raw = item.get("number", item.get("winningNumber", item.get("result", 0)))
                    num = int(str(raw).strip())
                    return num, ("BIG" if num >= 5 else "SMALL")
        except Exception as e:
            logging.error(f"Result check attempt {attempt+1} error: {e}")
    return None, None

# ==================== 200+ PREDICTION ALGORITHMS ====================
def run_mega_prediction(history):
    """
    200+ Algorithm Voting Engine.
    Returns: (prediction, confidence_pct, algo_count)
    """
    if len(history) < 3:
        pred = random.choice(["BIG", "SMALL"])
        return pred, 50.0, 0

    big_votes   = 0.0
    small_votes = 0.0
    algo_count  = 0

    results = [h["result"] for h in history]
    numbers = [h["number"] for h in history]

    # ===== GROUP 1: Last-N Frequency (10 algos) =====
    for n in [3, 5, 7, 10, 15, 20, 25, 30, 40, 50]:
        if len(results) >= n:
            sub = results[:n]
            b, s = sub.count("BIG"), sub.count("SMALL")
            w = 1.0
            if b > s:   big_votes += w
            elif s > b: small_votes += w
            else:       big_votes += 0.5; small_votes += 0.5
            algo_count += 1

    # ===== GROUP 2: Recency-Weighted Frequency (10 algos) =====
    for n in [3, 5, 7, 10, 15, 20, 25, 30, 40, 50]:
        if len(results) >= n:
            sub = results[:n]
            bs = sum((n - i) for i, r in enumerate(sub) if r == "BIG")
            ss = sum((n - i) for i, r in enumerate(sub) if r == "SMALL")
            w = 1.5
            if bs >= ss: big_votes += w
            else:        small_votes += w
            algo_count += 1

    # ===== GROUP 3: Streak Reversal Logic (12 algos) =====
    last = results[0]; streak = 1
    for r in results[1:]:
        if r == last: streak += 1
        else: break
    for threshold in range(2, 14):
        w = threshold * 0.25
        if streak >= threshold:
            if last == "BIG": small_votes += w
            else:             big_votes   += w
        else:
            if last == "BIG": big_votes   += w * 0.4
            else:             small_votes += w * 0.4
        algo_count += 1

    # ===== GROUP 4: Pattern Matching (20 algos) =====
    for pat_len in [2, 3, 4, 5]:
        if len(results) > pat_len + 5:
            pattern = tuple(results[:pat_len])
            big_after = small_after = 0
            for i in range(1, len(results) - pat_len):
                if tuple(results[i:i + pat_len]) == pattern:
                    prev = results[i - 1] if i > 0 else None
                    if prev == "BIG":   big_after   += 1
                    elif prev == "SMALL": small_after += 1
            total = big_after + small_after
            if total > 0:
                w = 2.0
                big_votes   += w * (big_after   / total)
                small_votes += w * (small_after / total)
                algo_count += 5

    # ===== GROUP 5: Number Threshold Analysis (25 algos) =====
    for n in [5, 10, 15, 20, 30]:
        if len(numbers) >= n:
            sub = numbers[:n]
            for threshold in [2, 3, 4, 5, 6]:
                above = sum(1 for x in sub if x >= threshold)
                w = 0.35
                if above > n / 2: big_votes   += w
                else:             small_votes += w
                algo_count += 1

    # ===== GROUP 6: RSI-like Momentum (10 algos) =====
    for period in [5, 7, 9, 11, 14, 18, 21, 28, 35, 42]:
        if len(numbers) >= period:
            sub = numbers[:period]
            gains  = [max(0, sub[i] - sub[i+1]) for i in range(len(sub)-1)]
            losses = [max(0, sub[i+1] - sub[i]) for i in range(len(sub)-1)]
            avg_g = sum(gains)  / len(gains)  if gains  else 0.0
            avg_l = sum(losses) / len(losses) if losses else 0.0
            avg_l = avg_l if avg_l > 0 else 0.001   # prevent division by zero
            rs  = avg_g / avg_l
            rsi = 100 - (100 / (1 + rs))
            w = 1.2
            if rsi > 58:  small_votes += w
            elif rsi < 42: big_votes   += w
            else:          big_votes   += 0.6; small_votes += 0.6
            algo_count += 1

    # ===== GROUP 7: MA Crossover (15 algos) =====
    ma_pairs = [(3,7),(5,10),(7,14),(10,20),(5,15),(7,21),(10,30),
                (3,10),(5,20),(7,28),(3,14),(5,25),(3,20),(4,12),(6,18)]
    for short, long in ma_pairs:
        if len(numbers) >= long:
            sma = sum(numbers[:short]) / short
            lma = sum(numbers[:long])  / long
            w   = 1.0
            if sma > lma: big_votes   += w
            else:         small_votes += w
            algo_count += 1

    # ===== GROUP 8: Alternating Pattern (10 algos) =====
    for check_len in range(2, 12):
        if len(results) >= check_len * 2:
            alt = all(results[i*2] != results[i*2+1] for i in range(check_len))
            if alt:
                w = check_len * 0.2
                if results[0] == "BIG": small_votes += w
                else:                   big_votes   += w
                algo_count += 1

    # ===== GROUP 9: Double Pattern BB/SS (8 algos) =====
    for check_len in range(2, 10):
        if len(results) >= check_len * 2:
            dbl = all(results[i*2] == results[i*2+1] for i in range(check_len))
            if dbl:
                w = check_len * 0.3
                if results[0] == "BIG": big_votes   += w
                else:                   small_votes += w
                algo_count += 1

    # ===== GROUP 10: Fibonacci Sequence Windows (8 algos) =====
    for fib_n in [1,2,3,5,8,13,21,34]:
        if len(results) >= fib_n:
            sub = results[:fib_n]
            b, s = sub.count("BIG"), sub.count("SMALL")
            w = 0.6
            if b > s:   big_votes   += w
            elif s > b: small_votes += w
            algo_count += 1

    # ===== GROUP 11: Chi-Square-like Balance (10 algos) =====
    for n in [10,15,20,25,30,35,40,45,50,100]:
        if len(results) >= n:
            sub = results[:n]
            expected = n / 2
            b = sub.count("BIG")
            s = sub.count("SMALL")
            w = 0.4
            if b < expected: big_votes   += w * (1 + (expected - b) * 0.05)
            else:            small_votes += w * (1 + (b - expected) * 0.05)
            algo_count += 1

    # ===== GROUP 12: Shannon Entropy (5 algos) =====
    for n in [10, 20, 30, 40, 50]:
        if len(results) >= n:
            sub = results[:n]
            bp = sub.count("BIG") / n
            sp = sub.count("SMALL") / n
            if bp > 0 and sp > 0:
                entropy = -(bp * math.log2(bp) + sp * math.log2(sp))
                w = entropy * 0.5
                if bp < sp: big_votes   += w
                else:       small_votes += w
                algo_count += 1

    # ===== GROUP 13: EMA-based (10 algos) =====
    for alpha_x10 in range(1, 11):
        alpha = alpha_x10 / 10
        if len(numbers) >= 3:
            ema = float(numbers[-1])
            for num in reversed(numbers[:-1]):
                ema = alpha * num + (1 - alpha) * ema
            w = 0.9
            if ema >= 4.5: small_votes += w
            else:          big_votes   += w
            algo_count += 1

    # ===== GROUP 14: Standard Deviation / Variance (5 algos) =====
    for n in [5, 10, 15, 20, 30]:
        if len(numbers) >= n:
            sub   = numbers[:n]
            mean  = sum(sub) / n
            std   = math.sqrt(sum((x - mean)**2 for x in sub) / n)
            w     = 0.5
            if mean > 4.5 and std < 2.5: small_votes += w
            elif mean < 4.5 and std < 2.5: big_votes += w
            else:                          big_votes += 0.25; small_votes += 0.25
            algo_count += 1

    # ===== GROUP 15: Hot/Cold Number Frequency (10 algos) =====
    for n in [10, 15, 20, 25, 30, 40, 50, 60, 70, 100]:
        if len(numbers) >= n:
            sub = numbers[:n]
            cnt = Counter(sub)
            big_f   = sum(cnt.get(x, 0) for x in range(5, 10))
            small_f = sum(cnt.get(x, 0) for x in range(0, 5))
            w = 0.7
            if big_f < small_f: big_votes   += w
            else:               small_votes += w
            algo_count += 1

    # ===== GROUP 16: Triple Block Pattern (7 algos) =====
    for rep in range(1, 8):
        if len(results) >= rep * 3:
            blocks = [results[i*3:(i+1)*3] for i in range(rep)]
            if all(len(set(b)) == 1 and len(b) == 3 for b in blocks):
                val = blocks[-1][0]
                w = rep * 0.4
                if val == "BIG": small_votes += w
                else:            big_votes   += w
                algo_count += 1

    # ===== GROUP 17: Cyclical Repetition (10 algos) =====
    for cycle in [2, 3, 4, 5, 6, 7, 8, 9, 10, 12]:
        if len(results) >= cycle * 3:
            matches = sum(1 for i in range(cycle, cycle*3) if results[i % cycle] == results[i])
            match_rate = matches / (cycle * 2)
            if match_rate > 0.65:
                predicted = results[0 % cycle]
                w = match_rate * 0.8
                if predicted == "BIG": big_votes   += w
                else:                  small_votes += w
                algo_count += 1

    # ===== GROUP 18: Number Parity Analysis (10 algos) =====
    for n in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
        if len(numbers) >= n:
            sub = numbers[:n]
            big_among_even = sum(1 for x in sub if x % 2 == 0 and x >= 6)
            big_among_odd  = sum(1 for x in sub if x % 2 == 1 and x >= 5)
            all_big = big_among_even + big_among_odd
            w = 0.3
            if all_big > n * 0.5: small_votes += w
            else:                  big_votes   += w
            algo_count += 1

    # ===== GROUP 19: Weighted Exponential Decay (10 algos) =====
    for decay in [0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.92, 0.95]:
        if len(results) >= 5:
            b_score = s_score = 0.0
            weight  = 1.0
            for r in results[:30]:
                if r == "BIG": b_score += weight
                else:          s_score += weight
                weight *= decay
            w = 0.8
            if b_score >= s_score: big_votes   += w
            else:                  small_votes += w
            algo_count += 1

    # ===== GROUP 20: Sum/Digit Analysis (5 algos) =====
    for n in [5, 10, 15, 20, 30]:
        if len(numbers) >= n:
            dsum = sum(numbers[:n])
            w = 0.3
            if dsum % 2 == 0: big_votes   += w
            else:             small_votes += w
            algo_count += 1

    # ===== FINAL CALCULATION =====
    total = big_votes + small_votes
    if total == 0:
        return random.choice(["BIG", "SMALL"]), 50.0, algo_count

    big_pct   = (big_votes   / total) * 100
    small_pct = (small_votes / total) * 100

    if big_votes >= small_votes:
        return "BIG",   round(big_pct,   1), algo_count
    else:
        return "SMALL", round(small_pct, 1), algo_count

# ==================== PROGRESS BAR BUILDER ====================
PROGRESS_CHARS = 20

def build_progress_bar(remaining, total):
    elapsed    = total - remaining
    filled     = int((elapsed / total) * PROGRESS_CHARS)
    empty      = PROGRESS_CHARS - filled
    bar        = "█" * filled + "░" * empty
    pct        = int((elapsed / total) * 100)
    return f"`[{bar}]` *{pct}%*"

def build_prediction_msg(period_id, prediction, confidence, algo_count, game_label, bar_text, remaining):
    emoji = "🔼" if prediction == "BIG" else "🔽"
    return (
        f"🤖 *{game_label} — LIVE SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📆 *Period:* `{period_id}`\n\n"
        f"{emoji} *Prediction:* `{prediction}`\n"
        f"📊 *Confidence:* `{confidence}%`\n"
        f"🔬 *Algorithms Used:* `{algo_count}+`\n\n"
        f"⏱ *Remaining:* `{remaining}s`\n"
        f"{bar_text}"
    )

def build_result_msg(period_id, prediction, actual_result, actual_num, confidence, game_label, is_win):
    emoji    = "🔼" if prediction == "BIG" else "🔽"
    res_emj  = "✅ WIN! 🏆" if is_win else "❌ LOSS! 💔"
    num_emoji = "🔼" if actual_result == "BIG" else "🔽"
    return (
        f"🤖 *{game_label} — RESULT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📆 *Period:* `{period_id}`\n\n"
        f"{emoji} *Prediction:* `{prediction}`\n"
        f"{num_emoji} *Actual:* `{actual_result}` *(Number: {actual_num})*\n"
        f"📊 *Confidence:* `{confidence}%`\n\n"
        f"*{res_emj}*"
    )

# ==================== PREDICTION SESSION (Background Thread) ====================
def run_prediction_session(chat_id, user_id, game_type, db, bot_token, active_key=None):
    """Full prediction lifecycle: period → predict → timer → API check → win/loss"""
    try:
        game_label = "𝗪𝗜𝗡𝗚𝗢 𝟯𝟬𝗦" if game_type == "GAME_30S" else "𝗪𝗜𝗡𝗚𝗢 𝟭𝗠𝗜𝗡"

        # Step 1: Show "Analysing..." message
        ana_msg = send_message(chat_id, "🔄 *ডেটা বিশ্লেষণ করা হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।*", "Markdown", bot_token=bot_token)

        # Step 2: Get period + fetch history + predict
        period_id, secs_remaining, total_secs = get_period_info(game_type)
        history = fetch_history(game_type, 100)
        prediction, confidence, algo_count = run_mega_prediction(history)

        # Delete "analysing" message if possible
        if ana_msg.get("ok"):
            telegram_request("deleteMessage", {"chat_id": chat_id, "message_id": ana_msg["result"]["message_id"]}, bot_token)

        # Step 3: Send prediction message with progress bar
        bar_text = build_progress_bar(secs_remaining, total_secs)
        msg_text = build_prediction_msg(period_id, prediction, confidence, algo_count, game_label, bar_text, secs_remaining)
        sent = send_message(chat_id, msg_text, "Markdown", bot_token=bot_token)
        if not sent.get("ok"):
            return
        message_id = sent["result"]["message_id"]

        # Step 4: Update progress bar every 1 second (per-second live countdown)
        start_time     = time.time()
        last_remaining = secs_remaining
        while True:
            elapsed   = time.time() - start_time
            remaining = max(0, secs_remaining - elapsed)
            if remaining <= 0:
                break
            cur_sec = int(remaining)
            # Edit only when the displayed second changes (avoids Telegram flood)
            if cur_sec != last_remaining:
                bar = build_progress_bar(cur_sec, total_secs)
                txt = build_prediction_msg(period_id, prediction, confidence, algo_count, game_label, bar, cur_sec)
                edit_message_text(chat_id, message_id, txt, "Markdown", bot_token=bot_token)
                last_remaining = cur_sec
            time.sleep(1.0)  # CPU fix: edit হয় শুধু প্রতি সেকেন্ডে, তাই 0.25 দিয়ে চেক করা অপচয়

        # Show bar 100%
        full_bar = build_progress_bar(0, total_secs)
        checking = (
            f"🤖 *{game_label} — CHECKING RESULT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📆 *Period:* `{period_id}`\n\n"
            f"⌛ *ফলাফল যাচাই হচ্ছে...*\n"
            f"{full_bar}"
        )
        edit_message_text(chat_id, message_id, checking, "Markdown", bot_token=bot_token)

        # Step 5: Wait for API to update & check result
        time.sleep(5)
        actual_num, actual_result = check_period_result(game_type, period_id)

        if actual_result is None:
            edit_message_text(
                chat_id, message_id,
                f"⚠️ *{game_label}*\n\n📆 Period: `{period_id}`\n\n❓ ফলাফল পাওয়া যায়নি। API সাড়া দেয়নি।",
                "Markdown", bot_token=bot_token
            )
            return

        # Step 6: Show result in the same message
        is_win    = (prediction == actual_result)
        result_txt = build_result_msg(period_id, prediction, actual_result, actual_num, confidence, game_label, is_win)
        next_btn   = {"inline_keyboard": [[{"text": "🔄 𝗡𝗘𝗫𝗧 𝗣𝗥𝗘𝗗𝗜𝗖𝗧𝗜𝗢𝗡", "callback_data": f"NEXT_PRED:{game_type}"}]]}
        edit_message_text(chat_id, message_id, result_txt, "Markdown", next_btn, bot_token)

        # Step 7: Send win/loss sticker or text
        if is_win:
            sticker_id = db.get("CONFIG:WIN_STICKER")
            if sticker_id:
                send_sticker(chat_id, sticker_id, bot_token)
            else:
                send_message(chat_id,
                    "🏆 *WIN!* 🎉\n\n✅ প্রেডিকশন সঠিক হয়েছে!\n🔥 দারুণ! পরের সিগনালের জন্য অপেক্ষা করুন।",
                    "Markdown", bot_token=bot_token)
        else:
            sticker_id = db.get("CONFIG:LOSS_STICKER")
            if sticker_id:
                send_sticker(chat_id, sticker_id, bot_token)
            else:
                send_message(chat_id,
                    "💔 *LOSS!*\n\n❌ এবার হয়নি। হাল ছাড়বেন না!\n💪 পরের রাউন্ডে আবার চেষ্টা করুন।",
                    "Markdown", bot_token=bot_token)

    except Exception as e:
        logging.exception(f"Prediction session error for user {user_id}: {e}")
        try:
            send_message(chat_id, "⚠️ একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।", bot_token=bot_token)
        except:
            pass
    finally:
        # CPU fix: session শেষে lock মুক্ত করো যাতে user আবার signal নিতে পারে
        if active_key:
            db.delete(active_key)

# -------------------- Wingo Game --------------------
def send_wingo_menu(chat_id, bot_token):
    text = "🤖 *তুমি কোন গেম টাইপে সিগনাল নিতে চাও?*"
    buttons = {
        "inline_keyboard": [
            [{"text": "⚡ 𝗪𝗜𝗡𝗚𝗢 𝟯𝟬𝗦 ⚡", "callback_data": "GAME_30S"}],
            [{"text": "🕐 𝗪𝗜𝗡𝗚𝗢 𝟭𝗠𝗜𝗡 🕐", "callback_data": "GAME_1M"}]
        ]
    }
    send_message(chat_id, text, "Markdown", buttons, bot_token)

def handle_game_request(chat_id, user_id, game_type, db, bot_token):
    """Auto period: no manual input needed anymore"""
    bal = get_balance(user_id, db)
    if bal < 1:
        send_message(chat_id,
            "❌ *আপনার পর্যাপ্ত ব্যালেন্স নেই।*\n\n💡 রেফার করে বা রিডিম কোড দিয়ে ব্যালেন্স যোগ করুন।",
            "Markdown", bot_token=bot_token)
        return

    # CPU fix: একজন user একসাথে একটার বেশি session চালাতে পারবে না
    active_key = f"ACTIVE_SESSION:{user_id}"
    if db.get(active_key):
        send_message(chat_id,
            "⏳ *আপনার একটি সিগনাল ইতিমধ্যে চলছে।*\n\nসেটি শেষ হলে আবার চেষ্টা করুন।",
            "Markdown", bot_token=bot_token)
        return

    # Deduct 1 coin and count signal
    add_balance(user_id, -1, db)
    increment_total_signals(user_id, db)
    db.put(active_key, "1")

    # Launch background thread
    t = threading.Thread(
        target=run_prediction_session,
        args=(chat_id, user_id, game_type, db, bot_token, active_key),
        daemon=True
    )
    t.start()

# -------------------- Redeem Codes --------------------
def generate_redeem_code():
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return '-'.join(''.join(random.choice(chars) for _ in range(4)) for _ in range(4))

def process_redeem_code(chat_id, user_id, code, db, bot_token):
    norm_code = code.strip().upper()
    redeem_data = db.get_json(f"REDEEM:{norm_code}")
    if not redeem_data:
        send_message(chat_id, "❌ *Invalid Redeem Code!*\n\nকোড চেক করে আবার চেষ্টা করুন।", "Markdown", bot_token=bot_token)
        return
    if redeem_data.get("used"):
        send_message(chat_id, "❌ *এই কোড ইতিমধ্যে ব্যবহৃত হয়েছে!*", "Markdown", bot_token=bot_token)
        return
    if db.get(f"REDEEM_USED:{user_id}:{norm_code}"):
        send_message(chat_id, "❌ *আপনি এই কোড আগেই ব্যবহার করেছেন!*", "Markdown", bot_token=bot_token)
        return
    redeem_data["used"]   = True
    redeem_data["usedBy"] = user_id
    redeem_data["usedAt"] = datetime.now().isoformat()
    db.put_json(f"REDEEM:{norm_code}", redeem_data)
    db.put(f"REDEEM_USED:{user_id}:{norm_code}", "true")
    add_balance(user_id, redeem_data["amount"], db)
    send_message(chat_id,
        f"✅ *Redeem Successful!*\n\n💰 Amount: `{redeem_data['amount']}` coins\n🎟 Code: `{norm_code}`\n\n🎉 Thank you!",
        "Markdown", bot_token=bot_token)

# -------------------- Profile & Info --------------------
def send_profile(chat_id, user_id, first_name, db, bot_token):
    bal = get_balance(user_id, db)
    sig = get_total_signals(user_id, db)
    send_message(chat_id,
        f"🧑‍💻 *𝗬𝗢𝗨𝗥 𝗡𝗔𝗠𝗘 :* *{first_name}*\n\n"
        f"🆔 𝗨𝗦𝗘𝗥 𝗜𝗗 : `{user_id}`\n\n"
        f"💰 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : *{bal}*\n\n"
        f"💹 𝗧𝗢𝗧𝗔𝗟 𝗦𝗜𝗚𝗡𝗔𝗟 : *{sig}*",
        "Markdown", bot_token=bot_token)

def send_referral_info(chat_id, user_id, db, bot_token):
    bot_info = telegram_request("getMe", {}, bot_token)
    if not bot_info.get("ok"):
        return
    bot_username  = bot_info["result"]["username"]
    ref_link      = f"https://t.me/{bot_username}?start={user_id}"
    reward_amount = int(db.get("CONFIG:REF_REWARD") or 25)
    send_message(chat_id,
        f"🖇️ 𝗬𝗢𝗨𝗥 𝗥𝗘𝗙𝗘𝗥 𝗟𝗜𝗡𝗞 :- `{ref_link}`\n\n"
        f"🤖 *প্রতি রেফারে {reward_amount}টা সিগনাল ফ্রি পাবেন!*\n\n"
        f"⚠️ _নোট: বন্ধু সব চ্যানেলে জয়েন করলেই রেফার কাউন্ট হবে।_",
        "Markdown",
        {"inline_keyboard": [[{"text": "🛡 𝗦𝗛𝗘𝗔𝗥𝗘 𝗥𝗘𝗙𝗘𝗥 𝗟𝗜𝗡𝗞 🛡️",
                                "url": f"https://t.me/share/url?url={ref_link}&text=Join%20Now!"}]]},
        bot_token)

def send_info_message(chat_id, db, bot_token):
    info = db.get("CONFIG:INFO")
    if info:
        send_message(chat_id, f"*{info}*", "Markdown", bot_token=bot_token)
    else:
        send_message(chat_id, "⚠️ *No Info Available.*", "Markdown", bot_token=bot_token)

def send_support_message(chat_id, db, bot_token):
    support = db.get_json("CONFIG:SUPPORT")
    if not support:
        send_message(chat_id, "No support info configured.", bot_token=bot_token)
        return
    send_message(chat_id, support.get("text", "Contact Support"),
                 reply_markup={"inline_keyboard": [[{"text": support.get("btnName", "Support"), "url": support["url"]}]]},
                 bot_token=bot_token)

# -------------------- Admin Panel --------------------
def send_admin_panel(chat_id, bot_token):
    win_set  = "✅" if True else "❌"   # placeholder; always show
    loss_set = "✅" if True else "❌"
    buttons = {
        "inline_keyboard": [
            [{"text": "👥 𝗔𝗟𝗟 𝗨𝗦𝗘𝗥𝗦",            "callback_data": "ADMIN_USERS:0"}],
            [{"text": "➕ 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 𝗔𝗗𝗗",          "callback_data": "ADMIN_ADD_BAL"}],
            [{"text": "➕ 𝗖𝗛𝗔𝗡𝗡𝗘𝗟𝗦 𝗔𝗗𝗗",         "callback_data": "ADMIN_ADD_CH"}],
            [{"text": "📳 𝗕𝗢𝗧 𝗜𝗡𝗙𝗢 𝗠𝗘𝗦𝗦𝗔𝗚𝗘",   "callback_data": "ADMIN_SET_INFO"}],
            [{"text": "🤙 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗔𝗡𝗗 𝗛𝗘𝗟𝗣",   "callback_data": "ADMIN_SET_SUP"}],
            [{"text": "⚔ 𝗥𝗘𝗠𝗢𝗩𝗘 𝗖𝗛𝗔𝗡𝗡𝗘𝗟𝗦 ⚔️", "callback_data": "ADMIN_REM_CH"}],
            [{"text": "💰 𝗥𝗘𝗙𝗘𝗥 𝗥𝗘𝗪𝗔𝗥𝗗",        "callback_data": "ADMIN_SET_REF"}],
            [{"text": "🎟 𝗥𝗘𝗗𝗘𝗘𝗠 𝗖𝗢𝗗𝗘𝗦",         "callback_data": "ADMIN_REDEEM_MENU"}],
            # ---- NEW: Sticker Settings ----
            [{"text": "🏆 𝗦𝗘𝗧 𝗪𝗜𝗡 𝗦𝗧𝗜𝗖𝗞𝗘𝗥",     "callback_data": "ADMIN_SET_WIN_STICKER"}],
            [{"text": "💔 𝗦𝗘𝗧 𝗟𝗢𝗦𝗦 𝗦𝗧𝗜𝗖𝗞𝗘𝗥",    "callback_data": "ADMIN_SET_LOSS_STICKER"}],
            [{"text": "🗑 𝗥𝗘𝗠𝗢𝗩𝗘 𝗦𝗧𝗜𝗖𝗞𝗘𝗥𝗦",     "callback_data": "ADMIN_REMOVE_STICKERS"}],
        ]
    }
    send_message(chat_id, "🛡️ *Admin Panel* 🛡️", "Markdown", buttons, bot_token)

def send_redeem_menu(chat_id, bot_token):
    buttons = {
        "inline_keyboard": [
            [{"text": "➕ 𝗖𝗥𝗘𝗔𝗧𝗘 𝗥𝗘𝗗𝗘𝗘𝗠 𝗖𝗢𝗗𝗘", "callback_data": "ADMIN_CREATE_REDEEM"}],
            [{"text": "📋 𝗩𝗜𝗘𝗪 𝗔𝗟𝗟 𝗖𝗢𝗗𝗘𝗦",    "callback_data": "ADMIN_VIEW_REDEEMS"}],
            [{"text": "🔙 𝗕𝗔𝗖𝗞",                "callback_data": "BACK_TO_AP"}]
        ]
    }
    send_message(chat_id, "🎟 *Redeem Code Management*", "Markdown", buttons, bot_token)

def view_redeem_codes(chat_id, db, bot_token):
    redeem_list = db.get_json("REDEEM_LIST", [])
    if not redeem_list:
        send_message(chat_id, "❌ No redeem codes found.", bot_token=bot_token)
        return
    buttons = []
    for code in redeem_list:
        data = db.get_json(f"REDEEM:{code}")
        if data:
            status = "❌" if data.get("used") else "✅"
            buttons.append([{"text": f"{status} {code} ({data['amount']})", "callback_data": f"VIEW_REDEEM:{code}"}])
    buttons.append([{"text": "🔙 𝗕𝗔𝗖𝗞", "callback_data": "ADMIN_REDEEM_MENU"}])
    send_message(chat_id, "🎟 *All Redeem Codes*\n\n✅ = Available | ❌ = Used",
                 "Markdown", {"inline_keyboard": buttons}, bot_token)

def view_redeem_details(chat_id, code, db, bot_token):
    data = db.get_json(f"REDEEM:{code}")
    if not data:
        send_message(chat_id, "❌ Redeem code not found.", bot_token=bot_token)
        return
    status  = "❌ Used" if data.get("used") else "✅ Available"
    details = (f"🎟 *Redeem Code Details*\n\nCode: `{data['code']}`\nAmount: {data['amount']} coins\nStatus: {status}\n"
               f"Created: {datetime.fromisoformat(data['createdAt']).strftime('%Y-%m-%d %H:%M:%S')}\n")
    if data.get("used"):
        details += f"\nUsed By: `{data['usedBy']}`\nUsed At: {datetime.fromisoformat(data['usedAt']).strftime('%Y-%m-%d %H:%M:%S')}"
    send_message(chat_id, details, "Markdown",
                 {"inline_keyboard": [[{"text": "🔙 𝗕𝗔𝗖𝗞", "callback_data": "ADMIN_VIEW_REDEEMS"}]]}, bot_token)

# -------------------- State & Callback Handling --------------------
def handle_state_input(chat_id, user_id, message, state, db, bot_token):
    text    = message.get("text", "")
    sticker = message.get("sticker")

    # Redeem
    if state == "REDEEM_WAIT_CODE":
        db.delete(f"STATE:{user_id}")
        process_redeem_code(chat_id, user_id, text, db, bot_token)
        return

    # Admin: balance
    if state == "ADMIN_WAIT_BAL_ID":
        db.put(f"STATE:{user_id}", f"ADMIN_WAIT_BAL_AMT:{text}")
        send_message(chat_id, "Enter Amount:", bot_token=bot_token)
        return
    if state.startswith("ADMIN_WAIT_BAL_AMT:"):
        target_id = state.split(":", 1)[1]
        try:
            amt = int(text)
        except:
            send_message(chat_id, "Invalid amount.", bot_token=bot_token)
            return
        add_balance(target_id, amt, db)
        send_message(chat_id, f"✅ Added {amt} coins to {target_id}.", bot_token=bot_token)
        send_message(target_id, f"💰 Admin added {amt} coins to your balance.", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    if state == "ADMIN_WAIT_REF_REWARD":
        try:
            amt = int(text)
        except:
            send_message(chat_id, "❌ Invalid number.", bot_token=bot_token)
            return
        db.put("CONFIG:REF_REWARD", str(amt))
        send_message(chat_id, f"✅ Referral reward set to {amt} coins.", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    if state == "ADMIN_WAIT_REDEEM_AMOUNT":
        try:
            amt = int(text)
        except:
            send_message(chat_id, "❌ Invalid number.", bot_token=bot_token)
            return
        code = generate_redeem_code()
        data = {"code": code, "amount": amt, "createdAt": datetime.now().isoformat(),
                "createdBy": user_id, "used": False, "usedBy": None, "usedAt": None}
        db.put_json(f"REDEEM:{code}", data)
        redeem_list = db.get_json("REDEEM_LIST", [])
        redeem_list.append(code)
        db.put_json("REDEEM_LIST", redeem_list)
        send_message(chat_id, f"✅ *Redeem Code Created!*\n\n🎟 Code: `{code}`\n💰 Amount: {amt} coins",
                     "Markdown", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    if state == "ADMIN_WAIT_CH":
        parts = text.split("|")
        if len(parts) != 2:
            send_message(chat_id, "Invalid format. Use: `ChannelID|Link`", "Markdown", bot_token=bot_token)
            return
        channels = db.get_json("CONFIG:CHANNELS", [])
        channels.append({"id": parts[0].strip(), "link": parts[1].strip()})
        db.put_json("CONFIG:CHANNELS", channels)
        send_message(chat_id, "✅ Channel Added.", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    if state == "ADMIN_WAIT_INFO":
        db.put("CONFIG:INFO", text)
        send_message(chat_id, "✅ Info message updated.", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    if state == "ADMIN_WAIT_SUP_TXT":
        db.put(f"STATE:{user_id}", f"ADMIN_WAIT_SUP_BTN:{text}")
        send_message(chat_id, "Now send: `Button Name|URL`", "Markdown", bot_token=bot_token)
        return
    if state.startswith("ADMIN_WAIT_SUP_BTN:"):
        support_text = state.split(":", 1)[1]
        parts = text.split("|")
        if len(parts) != 2:
            send_message(chat_id, "Invalid format.", bot_token=bot_token)
            return
        db.put_json("CONFIG:SUPPORT", {"text": support_text, "btnName": parts[0].strip(), "url": parts[1].strip()})
        send_message(chat_id, "✅ Support section updated.", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    # ====== NEW: Sticker Setting States ======
    if state == "ADMIN_WAIT_WIN_STICKER":
        file_id = None
        if sticker:
            file_id = sticker.get("file_id")
        elif text:
            file_id = text.strip()   # Admin can also paste file_id as text
        if file_id:
            db.put("CONFIG:WIN_STICKER", file_id)
            send_message(chat_id, f"✅ *WIN Sticker set!*\n\n`file_id: {file_id}`", "Markdown", bot_token=bot_token)
            send_sticker(chat_id, file_id, bot_token)   # Preview
        else:
            send_message(chat_id, "❌ Sticker পাওয়া যায়নি। একটি স্টিকার পাঠান।", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

    if state == "ADMIN_WAIT_LOSS_STICKER":
        file_id = None
        if sticker:
            file_id = sticker.get("file_id")
        elif text:
            file_id = text.strip()
        if file_id:
            db.put("CONFIG:LOSS_STICKER", file_id)
            send_message(chat_id, f"✅ *LOSS Sticker set!*\n\n`file_id: {file_id}`", "Markdown", bot_token=bot_token)
            send_sticker(chat_id, file_id, bot_token)   # Preview
        else:
            send_message(chat_id, "❌ Sticker পাওয়া যায়নি। একটি স্টিকার পাঠান।", bot_token=bot_token)
        db.delete(f"STATE:{user_id}")
        return

def handle_callback(callback_query, db, bot_token):
    data    = callback_query["data"]
    chat_id = callback_query["message"]["chat"]["id"]
    user_id = callback_query["from"]["id"]
    cb_id   = callback_query["id"]

    # Game selection
    if data in ("GAME_30S", "GAME_1M"):
        handle_game_request(chat_id, user_id, data, db, bot_token)
    elif data.startswith("NEXT_PRED:"):
        game_type = data.split(":")[1]
        handle_game_request(chat_id, user_id, game_type, db, bot_token)

    # Admin callbacks
    if user_id == OWNER_ID:
        if data == "ADMIN_ADD_BAL":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_BAL_ID")
            send_message(chat_id, "Enter User ID:", bot_token=bot_token)
        elif data == "ADMIN_ADD_CH":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_CH")
            send_message(chat_id, "Send: `ChannelID|Link`", "Markdown", bot_token=bot_token)
        elif data == "ADMIN_SET_INFO":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_INFO")
            send_message(chat_id, "Send new Info Message:", bot_token=bot_token)
        elif data == "ADMIN_SET_SUP":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_SUP_TXT")
            send_message(chat_id, "Send Support Message Text:", bot_token=bot_token)
        elif data == "ADMIN_SET_REF":
            current = db.get("CONFIG:REF_REWARD", "25")
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_REF_REWARD")
            send_message(chat_id, f"💰 Current reward: {current} coins\n\nNew amount দিন:", "Markdown", bot_token=bot_token)
        elif data == "ADMIN_REM_CH":
            channels = db.get_json("CONFIG:CHANNELS", [])
            if not channels:
                send_message(chat_id, "No channels.", bot_token=bot_token)
            else:
                buttons = [[{"text": f"🗑 {ch['link']}", "callback_data": f"DEL_CH:{idx}"}] for idx, ch in enumerate(channels)]
                buttons.append([{"text": "🔙 BACK", "callback_data": "BACK_TO_AP"}])
                send_message(chat_id, "Remove Channel:", reply_markup={"inline_keyboard": buttons}, bot_token=bot_token)
        elif data.startswith("DEL_CH:"):
            idx = int(data.split(":")[1])
            channels = db.get_json("CONFIG:CHANNELS", [])
            if 0 <= idx < len(channels):
                channels.pop(idx)
                db.put_json("CONFIG:CHANNELS", channels)
                send_message(chat_id, "✅ Channel Removed.", bot_token=bot_token)
        elif data == "BACK_TO_AP":
            send_admin_panel(chat_id, bot_token)
        elif data == "ADMIN_REDEEM_MENU":
            send_redeem_menu(chat_id, bot_token)
        elif data == "ADMIN_CREATE_REDEEM":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_REDEEM_AMOUNT")
            send_message(chat_id, "🎟 কত কয়েনের কোড বানাবেন?", bot_token=bot_token)
        elif data == "ADMIN_VIEW_REDEEMS":
            view_redeem_codes(chat_id, db, bot_token)
        elif data.startswith("VIEW_REDEEM:"):
            view_redeem_details(chat_id, data.split(":")[1], db, bot_token)
        # ====== NEW: Sticker Callbacks ======
        elif data == "ADMIN_SET_WIN_STICKER":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_WIN_STICKER")
            send_message(chat_id,
                "🏆 *WIN Sticker Set করুন*\n\n"
                "একটি স্টিকার পাঠান অথবা সরাসরি `file_id` টেক্সট হিসেবে পাঠান।\n\n"
                "স্টিকারের `file_id` পেতে @sticker bot ব্যবহার করুন।",
                "Markdown", bot_token=bot_token)
        elif data == "ADMIN_SET_LOSS_STICKER":
            db.put(f"STATE:{user_id}", "ADMIN_WAIT_LOSS_STICKER")
            send_message(chat_id,
                "💔 *LOSS Sticker Set করুন*\n\n"
                "একটি স্টিকার পাঠান অথবা সরাসরি `file_id` টেক্সট হিসেবে পাঠান।",
                "Markdown", bot_token=bot_token)
        elif data == "ADMIN_REMOVE_STICKERS":
            db.delete("CONFIG:WIN_STICKER")
            db.delete("CONFIG:LOSS_STICKER")
            send_message(chat_id, "✅ WIN ও LOSS স্টিকার উভয়ই মুছে দেওয়া হয়েছে।\n\nএখন text দিয়ে win/loss দেখাবে।", bot_token=bot_token)
        elif data.startswith("ADMIN_USERS:"):
            page      = int(data.split(":")[1])
            all_users = db.get_json("ALL_USERS", [])
            start     = page * 10
            end       = start + 10
            sliced    = all_users[start:end]
            msg       = "👥 *All Users*\n" + "\n".join(f"`{uid}`" for uid in sliced)
            buttons   = []
            if page > 0:
                buttons.append([{"text": "⬅️ Prev", "callback_data": f"ADMIN_USERS:{page-1}"}])
            if end < len(all_users):
                buttons.append([{"text": "Next ➡️", "callback_data": f"ADMIN_USERS:{page+1}"}])
            buttons.append([{"text": "🔙 BACK", "callback_data": "BACK_TO_AP"}])
            telegram_request("editMessageText", {
                "chat_id": chat_id,
                "message_id": callback_query["message"]["message_id"],
                "text": msg, "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": buttons}
            }, bot_token)
            answer_callback_query(cb_id, bot_token=bot_token)
            return

    answer_callback_query(cb_id, bot_token=bot_token)

def handle_message(message, db, bot_token):
    chat_id    = message["chat"]["id"]
    user_id    = message["from"]["id"]
    text       = message.get("text", "")
    first_name = message["from"].get("first_name", "User")

    # State handling (includes sticker messages)
    state = db.get(f"STATE:{user_id}")
    if state:
        handle_state_input(chat_id, user_id, message, state, db, bot_token)
        return

    # Commands
    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1:
            referrer = parts[1]
            if referrer != str(user_id) and not db.get(f"REFERRER:{user_id}"):
                db.put(f"REFERRER:{user_id}", referrer)
        initialize_user(user_id, first_name, db)
        check_join_and_start(chat_id, user_id, first_name, db, bot_token)
        return

    if text == "/ap_bot":
        if user_id == OWNER_ID:
            send_admin_panel(chat_id, bot_token)
        return

    if text == "✅ CHECK JOINED":
        check_join_and_start(chat_id, user_id, first_name, db, bot_token)
        return

    # Membership check
    if user_id != OWNER_ID and not check_membership(user_id, db, bot_token):
        send_force_join_message(chat_id, db, bot_token)
        return

    # Main menu
    if text == "❇️ 𝗪𝗜𝗡𝗚𝗢 𝗦𝗜𝗚𝗡𝗔𝗟 ❇️":
        send_wingo_menu(chat_id, bot_token)
    elif text == "👤 𝗣𝗥𝗢𝗙𝗜𝗟𝗘":
        send_profile(chat_id, user_id, first_name, db, bot_token)
    elif text == "🧑‍🍼 𝗥𝗘𝗙𝗘𝗥𝗥𝗘𝗗":
        send_referral_info(chat_id, user_id, db, bot_token)
    elif text == "📥 𝗥𝗘𝗗𝗘𝗘𝗠 𝗖𝗢𝗗𝗘":
        db.put(f"STATE:{user_id}", "REDEEM_WAIT_CODE")
        send_message(chat_id, "🎁 *Enter Redeem Code*\n\n`Example: H87J-98H4-UIU6-OO99`", "Markdown", bot_token=bot_token)
    elif text == "ℹ️ 𝗜𝗡𝗙𝗢":
        send_info_message(chat_id, db, bot_token)
    elif text == "🧑‍💻 𝗛𝗘𝗟𝗣 𝗔𝗡𝗗 𝗦𝗨𝗣𝗣𝗢𝗥𝗧":
        send_support_message(chat_id, db, bot_token)

def handle_update(update, db, bot_token):
    if "message" in update:
        handle_message(update["message"], db, bot_token)
    elif "callback_query" in update:
        handle_callback(update["callback_query"], db, bot_token)

# -------------------- Main Polling Loop --------------------
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    db        = Database()
    bot_token = BOT_TOKEN

    if bot_token == "YOUR_BOT_TOKEN":
        print("ERROR: Please set BOT_TOKEN environment variable.")
        return

    last_update_id = 0
    print("🤖 Bot started polling...")
    while True:
        try:
            resp = telegram_request("getUpdates", {
                "offset": last_update_id + 1,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            }, bot_token, req_timeout=35)
            if resp.get("ok"):
                for update in resp["result"]:
                    last_update_id = update["update_id"]
                    threading.Thread(
                        target=handle_update,
                        args=(update, db, bot_token),
                        daemon=True
                    ).start()
            else:
                logging.error(f"getUpdates error: {resp}")
            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped.")
            break
        except Exception:
            logging.exception("Polling error")
            time.sleep(5)

if __name__ == "__main__":
    main()