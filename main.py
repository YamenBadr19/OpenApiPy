import os
import sys
import re
import requests
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from twisted.internet import reactor, task
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# cTrader
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
import ctrader_open_api.messages.OpenApiMessages_pb2 as OpenApiMessages
import ctrader_open_api.messages.OpenApiCommonMessages_pb2 as OpenApiCommon

# ==================== 1. متغيرات البيئة ====================
host_type = os.getenv("HOST_TYPE", "demo").lower()
host = EndPoints.PROTOBUF_LIVE_HOST if host_type == "live" else EndPoints.PROTOBUF_DEMO_HOST
port = int(os.getenv("PORT", 8080))

client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
token = os.getenv("ACCESS_TOKEN")
account_id = os.getenv("ACCOUNT_ID")

if account_id:
    account_id = int(account_id)

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STR = os.getenv("SESSION_STR", "")
CHAT_IDS_STR = os.getenv("CHAT_IDS", "")
chat_ids = [int(x.strip()) for x in CHAT_IDS_STR.split(",") if x.strip()]

LOG_BOT_TOKEN = os.getenv("LOG_BOT_TOKEN", "")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", "")

LOT_SIZE = 0.01
LABEL = "Alpha_Ultra"
last_signal = ""
current_chat_id = None
active_positions = {}

client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)

# ==================== 2. خادم ويب خفيف ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot is Running Successfully!".encode("utf-8"))
    def log_message(self, *args):
        pass

def run_health():
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 [خادم الويب] منفذ {port}")
    server.serve_forever()

# ==================== 3. بوت السجلات ====================
def send_log(message):
    if LOG_BOT_TOKEN and LOG_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{LOG_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": LOG_CHAT_ID, "text": message}, timeout=5)
        except:
            pass

# ==================== 4. القواميس ====================
SIGNAL_DICTIONARY = {
    "buy": "BUY", "شراء": "BUY", "long": "BUY", "اشتري": "BUY", "اشتروا": "BUY", "دخلنا": "BUY",
    "sell": "SELL", "بيع": "SELL", "short": "SELL", "بيعوا": "SELL",
    "close": "CLOSE", "اغلاق": "CLOSE", "كلوز": "CLOSE", "قفل": "CLOSE", "سكر": "CLOSE"
}

SYMBOLS_DICTIONARY = {
    "xauusd": 1, "gold": 1, "ذهب": 1, "الذهب": 1,
    "btcusd": 2, "btc": 2, "بيتكوين": 2, "بتكوين": 2
}

# ==================== 5. دوال مساعدة ====================
def normalize_arabic_text(text):
    text = text.lower()
    text = re.sub(r'[\u064b-\u0652]', '', text)
    text = re.sub(r'[أإآ]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    return text

def extract_signal_details(text):
    clean_text = normalize_arabic_text(text)
    
    side = None
    match = re.search(r'\b(buy|sell|close|شراء|بيع|اغلاق|قفل|كلوز|اشتري|اشتروا|بيعوا|سكر)\b', clean_text)
    if match:
        side = SIGNAL_DICTIONARY.get(match.group(1))
    else:
        for k, v in SIGNAL_DICTIONARY.items():
            if k in clean_text:
                side = v
                break

    tp_list = []
    for tp in re.findall(r'(?:^|\n)\s*(?:tp|هدف|الهدف)\s*[:.]?\s*([0-9.]+)', clean_text, re.IGNORECASE):
        tp_list.append(float(tp))
    if not tp_list:
        match = re.search(r'(tp1|هدف\s*1|الهدف\s*الاول):\s*([0-9.]+)', clean_text)
        if match:
            tp_list.append(float(match.group(2)))
        else:
            match = re.search(r'(tp|take\s*profit|هدف|الهدف):\s*([0-9.]+)', clean_text)
            if match:
                tp_list.append(float(match.group(2)))
        match = re.search(r'(tp2|هدف\s*2|الهدف\s*الثاني):\s*([0-9.]+)', clean_text)
        if match:
            tp_list.append(float(match.group(2)))

    sl_price = None
    match = re.search(r'(?:sl|stop\s*loss|ستوب|الوقف|ايقاف|وقف)\s*[:.]?\s*([0-9.]+)', clean_text, re.IGNORECASE)
    if match:
        sl_price = float(match.group(1))
    if not sl_price:
        match = re.search(r'(?:^|\n)\s*sl\s*[:.]?\s*([0-9.]+)', clean_text, re.IGNORECASE)
        if match:
            sl_price = float(match.group(1))

    lot_size = None
    match = re.search(r'(\d+(?:\.\d+)?)\s*:?\s*لوت', clean_text)
    if match:
        lot_size = float(match.group(1))
    else:
        match = re.search(r'لوت\s*:?\s*(\d+(?:\.\d+)?)', clean_text)
        if match:
            lot_size = float(match.group(1))
        else:
            match = re.search(r'lot\s*:?\s*(\d+(?:\.\d+)?)', clean_text, re.IGNORECASE)
            if match:
                lot_size = float(match.group(1))

    repeat_count = 1
    match = re.search(r'(\d+)\s*مرات', clean_text)
    if match:
        repeat_count = int(match.group(1))
    else:
        match = re.search(r'repeat\s*:?\s*(\d+)', clean_text, re.IGNORECASE)
        if match:
            repeat_count = int(match.group(1))

    is_secure = any(w in clean_text for w in ["تامين", "امان", "امن", "ستوب على الدخول", "دخول", "secure"])

    return side, sl_price, tp_list, is_secure, lot_size, repeat_count

def extract_symbol_id(text):
    clean_text = normalize_arabic_text(text)
    for key, sym_id in SYMBOLS_DICTIONARY.items():
        if key in clean_text:
            return sym_id
    return 1

# ==================== 6. تنفيذ الصفقات ====================
def process_and_execute_trade(signal_text, chat_id=None):
    global last_signal
    
    print(f"🔵 [تشخيص] استقبلت: {signal_text}")
    send_log(f"🔵 [تشخيص] استقبلت: {signal_text}")
    
    if signal_text == last_signal:
        print(f"🔵 [تشخيص] تجاهل (مكرر)")
        send_log(f"🔵 [تشخيص] تجاهل (مكرر)")
        return
    last_signal = signal_text

    if "unknown" in signal_text.lower():
        send_log("ℹ️ تجاهل إشارة UNKNOWN")
        return

    side, sl_price, tp_list, is_secure, lot_size, repeat_count = extract_signal_details(signal_text)
    symbol_id = extract_symbol_id(signal_text)

    if side == "CLOSE":
        closed = []
        for pos_id, data in list(active_positions.items()):
            if data.get("chat_id") == chat_id:
                close_msg = OpenApiMessages.ProtoOAClosePositionReq()
                close_msg.ctidTraderAccountId = account_id
                close_msg.positionId = pos_id
                client.send(close_msg)
                closed.append(pos_id)
        if closed:
            send_log(f"🛑 أغلق {len(closed)} صفقة من القناة {chat_id}")
        else:
            send_log(f"ℹ️ لا صفقات مفتوحة من القناة {chat_id}")
        return

    if is_secure:
        send_log(f"🛡️ أمر تأمين من القناة {chat_id} (لم تفتح صفقة)")
        return
    if not side:
        send_log("⚠️ فشل فهم الاتجاه")
        return
    if not tp_list:
        send_log("⚠️ لا توجد أهداف")
        return

    for i, tp_price in enumerate(tp_list, 1):
        for _ in range(repeat_count):
            req = OpenApiMessages.ProtoOANewOrderReq()
            req.ctidTraderAccountId = account_id
            req.symbolId = symbol_id
            req.orderType = 1
            req.tradeSide = 1 if side == "BUY" else 2
            req.volume = int((lot_size or LOT_SIZE) * 100000)
            req.label = f"{LABEL}_TP{i}"
            if sl_price: req.stopLoss = sl_price
            req.takeProfit = tp_price

            client.send(req)
            send_log(f"🚀 فتح {side} هدف {i} (TP {tp_price}) حجم {lot_size or LOT_SIZE}")

# ==================== 7. استقبال رسائل cTrader ====================
def on_message_received(client_instance, message):
    global current_chat_id
    if message.payloadType == OpenApiMessages.ProtoOASpotEvent().payloadType:
        msg = OpenApiMessages.ProtoOASpotEvent()
        msg.ParseFromString(message.payload)
        if msg.bidPrice:
            pass

    if message.payloadType == OpenApiMessages.ProtoOAExecutionEvent().payloadType:
        event = OpenApiMessages.ProtoOAExecutionEvent()
        event.ParseFromString(message.payload)
        if event.executionType == 1:
            pos_id = event.positionId
            active_positions[pos_id] = {"chat_id": current_chat_id}
            send_log(f"📌 صفقة {pos_id} مرتبطة بقناة {current_chat_id}")

# ==================== 8. عميل تيليجرام ====================
async def start_telegram():
    global current_chat_id
    tg = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)
    await tg.start()

    @tg.on(events.NewMessage(chats=chat_ids))
    async def handler(event):
        global current_chat_id
        text = event.message.text
        if text:
            current_chat_id = event.chat_id
            print(f"📡 [قناة {current_chat_id}] {text}")
            process_and_execute_trade(text, chat_id=current_chat_id)

    send_log(f"🤖 بدأ مراقبة {len(chat_ids)} قنوات")
    await tg.run_until_disconnected()

def run_telegram():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_telegram())

# ==================== 9. اتصال cTrader ====================
def connected(client_instance):
    print("✅ [اتصل]")
    send_log("✅ اتصل بـ cTrader")
    app_auth = OpenApiMessages.ProtoOAApplicationAuthReq()
    app_auth.clientId = client_id
    app_auth.clientSecret = client_secret
    def on_app(res):
        print("✅ [تطبيق] تم قبول التطبيق")
        send_log("✅ قبول التطبيق، جاري تفعيل الحساب...")
        acc_auth = OpenApiMessages.ProtoOAAccountAuthReq()
        acc_auth.ctidTraderAccountId = account_id
        acc_auth.accessToken = token
        def on_acc(res2):
            print(f"🎯 [جاهز] تم تسجيل الدخول للحساب {account_id}")
            send_log(f"🎯 جاهز على الحساب {account_id}")
        client.send(acc_auth).addCallback(on_acc).addErrback(on_error)
    client.send(app_auth).addCallback(on_app).addErrback(on_error)

def disconnected(client_instance, reason):
    send_log(f"❌ انفصال: {reason}")
    reactor.callLater(10, client.startService)

def on_error(failure):
    send_log(f"🚨 خطأ cTrader: {failure}")

# ==================== 10. التشغيل ====================
if __name__ == "__main__":
    if not all([client_id, client_secret, token, account_id]):
        print("❌ متغيرات ناقصة")
        sys.exit(1)

    threading.Thread(target=run_health, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(on_message_received)
    client.startService()
    reactor.run()
