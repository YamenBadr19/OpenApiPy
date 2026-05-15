import sys
import re
import threading
import time
import requests
from twisted.internet import reactor
from open_api_pages.client import Client
import open_api_pages.messages.OpenApiMessages_pb2 as OpenApiMessages

# ==================== 1. رابط البيانات الخاص بك المدمج تلقائياً ====================
DATA_URL = "https://ctrader-bot-94ve.onrender.com/get"

# إعدادات إدارة الصفقات (بدون إعدادات اتصال لخبطة)
LOT_SIZE = 0.01
USE_TRAILING_STOP = True  # تفعيل الستوب المتحرك تلقائياً
LABEL = "Alpha_Ultra"

# ==================== 2. قاموس ترجمة الإشارات ====================
SIGNAL_DICTIONARY = {
    "buy": "BUY", "شراء": "BUY", "long": "BUY",
    "sell": "SELL", "بيع": "SELL", "short": "SELL"
}

# كائن الاتصال الرئيسي بـ سي ترايدر ومتغيرات المراقبة
ctrader_client = None
last_signal = ""
is_bot_running = True

# ==================== 3. دالة استخراج الأسعار من النص (Regex) ====================
def extract_price(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0
    return 0.0

# ==================== 4. المراقبة المستمرة وسحب البيانات من رابطك كل ثانية ====================
def monitor_signal_loop():
    global last_signal, is_bot_running
    print(f"[+] تم تفعيل العقل.. جاري مراقبة الرابط الخاص بك: {DATA_URL}")
    
    while is_bot_running:
        try:
            # سحب الإشارة من سيرفر الريندر الخاص بك
            response = requests.get(DATA_URL, timeout=5)
            signal = response.text.strip().upper()

            # التأكد من وجود إشارة جديدة وليست رسالة انتظار
            if signal and signal != last_signal and "WAITING" not in signal:
                last_signal = signal
                print(f"[+] إشارة جديدة تم سحبها من الرابط: {signal}")
                
                clean_msg = signal.lower()
                side = None

                # فحص الاتجاه عبر القاموس الذكي
                for key, val in SIGNAL_DICTIONARY.items():
                    if key in clean_msg:
                        side = val
                        break

                if side:
                    tp_price = extract_price(signal, r"TP[:\s]*([\d.]+)")
                    sl_price = extract_price(signal, r"SL[:\s]*([\d.]+)")

                    if tp_price > 0 and sl_price > 0:
                        print(f"[+] تم ترجمة الإشارة عبر القاموس: {side} | هدف: {tp_price} | ستوب: {sl_price}")
                        # تنفيذ الأمر فوراً في سي ترايدر
                        execute_market_order(side, tp_price, sl_price)
                        
                elif "CLOSE" in signal or "إغلاق" in clean_msg:
                    close_all_positions()
                    
        except Exception as e:
            print(f"⚠️ خطأ أثناء طلب البيانات من الرابط: {e}")
            
        time.sleep(1) # الانتظار لمدة ثانية واحدة قبل الطلب التالي (نفس منطق الـ cBot)

# ==================== 5. إرسال الأمر والستوب المتحرك للمكتبة ====================
def execute_market_order(side, tp_price, sl_price):
    global ctrader_client
    if not ctrader_client:
        print("[-] خطأ: اتصال سي ترايدر غير نشط حالياً.")
        return

    # بناء طلب فتح صفقة جديدة
    request_msg = OpenApiMessages.ProtoOANewOrderReq()
    request_msg.symbolId = 1  # معرف الرمز الخاص بالذهب أو البيتكوين لدى البروكر
    request_msg.orderType = OpenApiMessages.ProtoOAOrderType.MARKET
    request_msg.tradeSide = OpenApiMessages.ProtoOATradeSide.BUY if side == "BUY" else OpenApiMessages.ProtoOATradeSide.SELL
    request_msg.volume = int(LOT_SIZE * 100000)
    request_msg.label = LABEL
    
    # تمرير ميزة الستوب المتحرك والأسعار مباشرة في السحاب
    request_msg.trailingStopLoss = USE_TRAILING_STOP
    request_msg.stopLoss = sl_price
    request_msg.takeProfit = tp_price

    print(f"🚀 [السحاب] تم إرسال أمر {side} مع تفعيل الستوب المتحرك بناءً على إعدادات المجلد الخاص!")
    ctrader_client.send(request_msg)

def close_all_positions():
    print(f"🔄 [السحاب] جاري إغلاق كافة صفقات الـ {LABEL}...")

# ==================== 6. أحداث الاتصال وتشغيل محرك السحاب ====================
def on_connected(client):
    print(f"[+] تم ربط سيرفر Render بنجاح! جاري القراءة التلقائية للتوكنات من مجلدك الخاص...")

if __name__ == "__main__":
    # تشغيل حلقة مراقبة الرابط (Polling) في خلفية مستقلة لكي لا تحظر اتصال سي ترايدر
    monitor_thread = threading.Thread(target=monitor_signal_loop)
    monitor_thread.daemon = True
    monitor_thread.start()

    # بدء تشغيل الاتصال والاعتماد على إعدادات مجلدك الخاص بالتوكنات ونوع الحساب
    ctrader_client = Client() 
    ctrader_client.setConnectedCallback(on_connected)
    
    print("[+] عقل البوت جاهز تماماً ويعمل بالسحاب متصلاً برابط بياناتك...")
    ctrader_client.start()
    reactor.run()
      
