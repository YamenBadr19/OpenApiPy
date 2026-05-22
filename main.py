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

# ==================== 4. عميل تيليجرام ====================
async def start_telegram():
    tg = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)
    await tg.start()
    send_log("🤖 تيليجرام جاهز (للاستماع فقط)")
    await tg.run_until_disconnected()

def run_telegram():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_telegram())

# ==================== 5. اتصال cTrader ====================
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

            # 🧪 اختبار أبسط أمر شراء
            def send_test_order():
                try:
                    req = OpenApiMessages.ProtoOANewOrderReq()
                    req.ctidTraderAccountId = account_id
                    req.symbolId = 1   # الذهب
                    req.orderType = 1   # MARKET
                    req.tradeSide = 1   # BUY
                    req.volume = 1000   # 0.01 لوت
                    req.label = "TestSimple"

                    client.send(req)
                    print("🚀 [اختبار] تم إرسال أمر شراء بسيط للذهب. تحقق من المنصة.")
                    send_log("🚀 [اختبار] تم إرسال أمر شراء بسيط للذهب. تحقق من المنصة.")
                except Exception as e:
                    print(f"❌ [اختبار] فشل إرسال الأمر: {e}")
                    send_log(f"❌ [اختبار] فشل إرسال الأمر: {e}")

            # نرسل الأمر بعد 3 ثوانٍ من الجاهزية
            reactor.callLater(3, send_test_order)

        client.send(acc_auth).addCallback(on_acc).addErrback(on_error)
    client.send(app_auth).addCallback(on_app).addErrback(on_error)

def disconnected(client_instance, reason):
    send_log(f"❌ انفصال: {reason}")
    reactor.callLater(10, client.startService)

def on_error(failure):
    send_log(f"🚨 خطأ cTrader: {failure}")

# ==================== 6. التشغيل ====================
if __name__ == "__main__":
    if not all([client_id, client_secret, token, account_id]):
        print("❌ متغيرات ناقصة")
        sys.exit(1)

    threading.Thread(target=run_health, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.startService()
    reactor.run()
