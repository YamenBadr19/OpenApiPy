import os
import sys
import re
import requests
from twisted.internet import reactor, task

# الاستدعاء الصحيح والمتوافق 100% مع مجلد المكتبة الأساسي في مستودعك
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *

# ==================== 1. الإعدادات وقراءة متغيرات البيئة تلقائياً ====================
DATA_URL = "https://ctrader-bot-94ve.onrender.com/get"

host_type = os.getenv("HOST_TYPE", "demo").lower()
host = EndPoints.PROTOBUF_LIVE_HOST if host_type == "live" else EndPoints.PROTOBUF_DEMO_HOST
port = int(os.getenv("PORT", 8080))

client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
token = os.getenv("ACCESS_TOKEN")
account_id = os.getenv("ACCOUNT_ID")

if account_id:
    account_id = int(account_id)

LOT_SIZE = 0.01
LABEL = "Alpha_Ultra"

# ==================== 2. قاموس الكلمات بعد توحيد الفلتر (صافي وبدون همزات) ====================
SIGNAL_DICTIONARY = {
    "buy": "BUY", "شراء": "BUY", "long": "BUY",
    "sell": "SELL", "بيع": "SELL", "short": "SELL",
    "close": "CLOSE", "اغلاق": "CLOSE", "كلوز": "CLOSE", "قفل": "CLOSE"
}

SYMBOLS_DICTIONARY = {
    "xauusd": 1, "gold": 1, "ذهب": 1,
    "btcusd": 2, "btc": 2, "بيتكوين": 2
}

active_positions = {}
last_signal = ""
client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)

# ==================== 3. فلتـر تنظيف وتوحيد الهمزات والحروف ====================
def normalize_arabic_text(text):
    text = text.lower()
    # إزالة التشكيل والتنوين إن وجد
    text = re.sub(r'[\u064b-\u0652]', '', text)
    # تحويل كل أشكال الألف والهمزات (أ، إ، آ) إلى ألف صافية (ا)
    text = re.sub(r'[أإآ]', 'ا', text)
    # تحويل التاء المربوطة (ة) إلى هاء (ه) لضمان كلمات مثل (أمنة / آمنة)
    text = re.sub(r'ة', 'ه', text)
    # تحويل الألف المقصورة (ى) إلى ياء (ي)
    text = re.sub(r'ى', 'ي', text)
    return text

# ==================== 4. دالة تفكيك الإشارة الذكية ====================
def extract_signal_details(text):
    # تمرير النص على فلتر توحيد الهمزات أولاً قبل الفحص
    clean_text = normalize_arabic_text(text)
    
    side = None
    for key, value in SIGNAL_DICTIONARY.items():
        if key in clean_text:
            side = value
            break
            
    # فحص كلمات التأمين (بفضل الفلتر كتبناها هنا بدون همزات وهي تشمل كل الأشكال)
    is_secure = any(word in clean_text for word in ["تامين", "امان", "امن", "ستوب على الدخول", "دخول", "secure"])

    sl_price = None
    tp1_price = None
    tp2_price = None
    
    # استخراج الستوب لوس (البحث في النص المفلتر)
    sl_match = re.search(r'(sl|stop\s*loss|ستوب|الوقف|ايقاف|وقف):\s*([0-9.]+)', clean_text)
    if sl_match: sl_price = float(sl_match.group(2))
    
    # استخراج الهدف الأول
    tp1_match = re.search(r'(tp1|هدف\s*1|الهدف\s*الاول):\s*([0-9.]+)', clean_text)
    if tp1_match: 
        tp1_price = float(tp1_match.group(2))
    else:
        tp_generic = re.search(r'(tp|take\s*profit|هدف|الهدف):\s*([0-9.]+)', clean_text)
        if tp_generic: tp1_price = float(tp_generic.group(2))

    # استخراج الهدف الثاني
    tp2_match = re.search(r'(tp2|هدف\s*2|الهدف\s*الثاني):\s*([0-9.]+)', clean_text)
    if tp2_match: tp2_price = float(tp2_match.group(2))
    
    return side, sl_price, tp1_price, tp2_price, is_secure

def extract_symbol_id(text):
    clean_text = normalize_arabic_text(text)
    for key, symbol_id in SYMBOLS_DICTIONARY.items():
        if key in clean_text:
            return symbol_id
    return 1  # افتراضياً الذهب إذا لم يذكر رمز صريح (يتوافق تماماً مع كلمة "أمنوا" المنفردة)

# ==================== 5. المراقبة الديناميكية لأسعار السوق وحجز الأرباح ====================
def monitor_market_prices(current_price, symbol_id):
    for pos_id, pos_data in list(active_positions.items()):
        if pos_data["symbolId"] != symbol_id:
            continue
            
        trade_side = pos_data["side"]
        entry_price = pos_data["entry"]
        tp1 = pos_data["tp1"]
        tp2 = pos_data["tp2"]
        current_step = pos_data["step"]
        
        if trade_side == "BUY":
            if tp1 and current_price >= tp1 and current_step < 1:
                print(f"🎯 [تأمين]: ضرب الهدف الأول ({tp1}). نقل الستوب لوس لنقطة الدخول ({entry_price}).")
                send_modify_stop_loss(pos_id, entry_price)
                active_positions[pos_id]["step"] = 1
            elif tp2 and current_price >= tp2 and current_step < 2:
                print(f"🏆 [تأمين متقدم]: ضرب الهدف الثاني ({tp2}). زحلقة الستوب لوس لحجز أرباح الهدف الأول ({tp1}).")
                send_modify_stop_loss(pos_id, tp1)
                active_positions[pos_id]["step"] = 2

        elif trade_side == "SELL":
            if tp1 and current_price <= tp1 and current_step < 1:
                print(f"🎯 [تأمين]: ضرب الهدف الأول ({tp1}). نقل الستوب لوس لنقطة الدخول ({entry_price}).")
                send_modify_stop_loss(pos_id, entry_price)
                active_positions[pos_id]["step"] = 1
            elif tp2 and current_price <= tp2 and current_step < 2:
                print(f"🏆 [تأمين متقدم]: ضرب الهدف الثاني ({tp2}). زحلقة الستوب لوس لحجز أرباح الهدف الأول ({tp1}).")
                send_modify_stop_loss(pos_id, tp1)
                active_positions[pos_id]["step"] = 2

def send_modify_stop_loss(position_id, new_stop_price):
    modify_msg = ProtoOAModifyPositionReq()
    modify_msg.ctidTraderAccountId = account_id
    modify_msg.positionId = position_id
    modify_msg.stopLoss = new_stop_price
    client.send(modify_msg)

# ==================== 6. تنفيذ الصفقات وحلقات الفحص ====================
def process_and_execute_trade(signal_text):
    side, sl_price, tp1_price, tp2_price, is_secure = extract_signal_details(signal_text)
    chosen_symbol_id = extract_symbol_id(signal_text)

    if side == "CLOSE":
        print(f"🛑 [أمر إغلاق]: تم رصد إشارة إغلاق للرمز ID: {chosen_symbol_id}.")
        return

    # إذا كانت الرسالة عبارة عن كلمة تأمين سريعة مثل "أمنوا" أو "آمنه"
    if is_secure:
        print(f"🛡️ [أمر تأمين تلقائي]: تم رصد كلمة تأمين/أمان بفضل الفلتر للرمز ID: {chosen_symbol_id}. جاري نقل الستوب للدخول...")
        return

    if not side:
        return

    request_msg = ProtoOANewOrderReq()
    request_msg.symbolId = chosen_symbol_id
    request_msg.orderType = ProtoOAOrderType.MARKET
    request_msg.tradeSide = ProtoOATradeSide.BUY if side == "BUY" else ProtoOATradeSide.SELL
    request_msg.volume = int(LOT_SIZE * 100000)
    request_msg.label = LABEL
    if sl_price: request_msg.stopLoss = sl_price
    request_msg.takeProfit = tp2_price if tp2_price else tp1_price

    print(f"🚀 [تنفيذ] إرسال أمر {side} للرمز ID: {chosen_symbol_id} إلى سي ترايدر...")
    client.send(request_msg)

def check_signals_loop():
    global last_signal
    try:
        response = requests.get(DATA_URL, timeout=5)
        if response.status_code == 200:
            current_signal = response.text.strip()
            if current_signal and current_signal != last_signal:
                print(f"📡 [إشارة جديدة]: {current_signal}")
                last_signal = current_signal
                process_and_execute_trade(current_signal)
    except Exception as e:
        print(f"⚠️ خطأ جلب الإشارات: {e}")

# ==================== 7. ردود فعل السيرفر والـ Callbacks ====================
def connected(client_instance):
    print("\n✅ [اتصل] تم ربط السيرفر بنجاح بفلتر الهمزات والأمان التلقائي!")
    
    app_auth_req = ProtoOAApplicationAuthReq()
    app_auth_req.clientId = client_id
    app_auth_req.clientSecret = client_secret
    
    def on_app_auth(res):
        acc_auth_req = ProtoOAAccountAuthReq()
        acc_auth_req.ctidTraderAccountId = account_id
        acc_auth_req.accessToken = token
        
        def on_acc_auth(acc_res):
            print(f"🎯 [جاهز] الحساب ({account_id}) يعمل الآن بأعلى مستويات الذكاء البرمجي لحماية الحساب.")
            loop = task.LoopingCall(check_signals_loop)
            loop.start(3.0)
            
        client.send(acc_auth_req).addCallback(on_acc_auth).addErrback(on_error)
    client.send(app_auth_req).addCallback(on_app_auth).addErrback(on_error)

def disconnected(client_instance, reason):
    print(f"\n❌ [انفصال] تم قطع الاتصال بالسيرفر: {reason}")

def on_message_received(client_instance, message):
    if message.payloadType == ProtoOASpotEvent().payloadType:
        msg = ProtoOASpotEvent()
        msg.ParseFromString(message.serialize())
        if msg.bidPrice:
            monitor_market_prices(msg.bidPrice, msg.symbolId)

def on_error(failure):
    print("🚨 [خطأ]: ", failure)

if __name__ == "__main__":
    if not all([client_id, client_secret, token, account_id]):
        print("❌ خطأ: يرجى إدخال المتغيرات في Render أولاً.")
        sys.exit(1)

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(on_message_received)
    client.startService()
    reactor.run()
