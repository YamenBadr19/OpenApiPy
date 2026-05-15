import sys
import re
import threading
import time
import requests
from twisted.internet import reactor, task
# القراءة من المجلد الموجود بجانبه مباشرة في القائمة الرئيسية
from open_api_pages.client import Client
import open_api_pages.messages.OpenApiMessages_pb2 as OpenApiMessages

# ==================== 1. رابط البيانات الخاص بك ====================
DATA_URL = "https://ctrader-bot-94ve.onrender.com/get"

# إعدادات التداول (يتم قراءة التوكن والحساب تلقائياً من مجلد الإعدادات الخاص بك)
LOT_SIZE = 0.01
USE_TRAILING_STOP = True  # تفعيل الستوب المتحرك تلقائياً لحماية الأرباح
LABEL = "Alpha_Ultra"

# ==================== 2. قاموس ترجمة الإشارات والعملات الذكي ====================
SIGNAL_DICTIONARY = {
    "buy": "BUY", "شراء": "BUY", "long": "BUY",
    "sell": "SELL", "بيع": "SELL", "short": "SELL"
}

# قاموس العملات لربط الرموز الحرة بأرقام الـ ID الخاصة بالبروكر
SYMBOLS_DICTIONARY = {
    "xauusd": 1,   # الذهب يأخذ الرمز 1 افتراضياً
    "gold": 1,
    "btcusd": 2,   # البيتكوين يأخذ الرمز 2 (تأكد من رقم الـ ID من البروكر الخاص بك)
    "btc": 2
}

ctrader_client = None
last_signal = ""

# ==================== 3. دوال تفكيك الأسعار والمراقبة والعملات ====================
def extract_price(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0
    return 0.0

def extract_symbol_id(text):
    clean_text = text.lower()
    # البحث التلقائي عن اسم العملة في نص التليجرام القادم
    for key, symbol_id in SYMBOLS_DICTIONARY.items():
        if key in clean_text:
            return symbol_id
    return 1  # إذا لم يجد اسم العملة، يتداول افتراضياً على الذهب (ID: 1)

def monitor_signal_loop():
    global last_signal
    try:
        # سحب الإشارة من سيرفر الريندر الخاص بك (Timeout سريع لعدم حظر السيرفر)
        response = requests.get(DATA_URL, timeout=3)
        signal = response.text.strip().upper()

        if signal and signal != last_signal and "WAITING" not in signal:
            last_signal = signal
            print(f"[+] إشارة جديدة تم التقاطها في السحاب: {signal}")
            
            clean_msg = signal.lower()
            side = None

            # فحص الاتجاه عبر القاموس الذكي
            for key, val in SIGNAL_DICTIONARY.items():
                if key in clean_msg:
                    side = val
                    break

            if side:
                tp_price = extract_price(signal, r"TP[:\s]*([\d.]+)")
                sl_price = extract_price(signal, r"SL[:\s]*([\d.]+)") # تم تصحيح المتغير هنا من msg إلى signal

                if tp_price > 0 and sl_price > 0:
                    print(f"[+] تم ترجمة العقل: {side} | هدف: {tp_price} | ستوب: {sl_price}")
                    execute_cloud_order(side, tp_price, sl_price, signal)
                    
            elif "CLOSE" in signal or "إغلاق" in clean_msg:
                print("🔄 جاري إغلاق الصفقات بناءً على أمر التليجرام...")
                
    except Exception as e:
        # يتجاهل أخطاء الاتصال المؤقتة لضمان استمرار البوت في العمل
        pass

# ==================== 4. تنفيذ الأمر والستوب المتحرك والعملة الذكية ====================
def execute_cloud_order(side, tp_price, sl_price, raw_signal_text):
    global ctrader_client
    if not ctrader_client:
        print("[-] خطأ: اتصال سي ترايدر غير نشط حالياً.")
        return

    # تحديد رقم الـ ID الخاص بالعملة تلقائياً بناءً على محتوى الرسالة
    chosen_symbol_id = extract_symbol_id(raw_signal_text)

    # بناء طلب فتح صفقة جديدة
    request_msg = OpenApiMessages.ProtoOANewOrderReq()
    request_msg.symbolId = chosen_symbol_id  # تم استبدال الرقم الثابت بمتغير العملة الذكي
    request_msg.orderType = OpenApiMessages.ProtoOAOrderType.MARKET
    request_msg.tradeSide = OpenApiMessages.ProtoOATradeSide.BUY if side == "BUY" else OpenApiMessages.ProtoOATradeSide.SELL
    request_msg.volume = int(LOT_SIZE * 100000)
    request_msg.label = LABEL
    
    # تمرير ميزة الستوب المتحرك والأسعار مباشرة في السحاب
    request_msg.trailingStopLoss = USE_TRAILING_STOP
    request_msg.stopLoss = sl_price
    request_msg.takeProfit = tp_price

    print(f"🚀 [السحاب] تم إرسال أمر {side} على العملة ID: {chosen_symbol_id} مع تفعيل الستوب المتحرك تلقائياً!")
    ctrader_client.send(request_msg)

def on_connected(client):
    print(f"[+] تم ربط سيرفر Render بنجاح! جاري القراءة التلقائية للتوكنات من مجلدك الخاص...")

if __name__ == "__main__":
    # بدء تشغيل اتصال مكتبة سي ترايدر بناءً على كائن العميل الافتراضي بمجلدك
    ctrader_client = Client() 
    ctrader_client.setConnectedCallback(on_connected)
    
    # دمج حلقة فحص رابط التليجرام كل ثانية (1.0) بتوافق كامل مع محرك Twisted
    looping_task = task.LoopingCall(monitor_signal_loop)
    looping_task.start(1.0)
    
    print("[+] عقل البوت يعمل الآن في القائمة الرئيسية ومستعد لسحب الإشارات للذهب والبيتكوين...")
    ctrader_client.start()
    reactor.run()
    
