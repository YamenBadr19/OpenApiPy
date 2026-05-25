import os
import asyncio
import json
import re
from telethon import TelegramClient, events, functions

# إعدادات الاتصال (سيتم سحبها من المتغيرات في Render)
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# إنشاء جلسة البوت
tg = TelegramClient('yamen_session', API_ID, API_HASH)

def parse_to_json(msg):
    msg_lower = msg.lower()
    
    # 1. تحديد الاتجاه (Action)
    action = None
    if any(word in msg_lower for word in ["شراء", "buy", "long", "دخول"]): action = "BUY"
    elif any(word in msg_lower for word in ["بيع", "sell", "short"]): action = "SELL"
    elif any(word in msg_lower for word in ["تأمين", "break even", "be"]): action = "BREAK_EVEN"
    elif any(word in msg_lower for word in ["إغلاق", "close"]): action = "CLOSE"
    
    if not action: return None
    
    # 2. تحليل الأصول (Symbol)
    symbol = "XAUUSD"
    if any(w in msg_lower for w in ["البيتكوين", "btc", "bitcoin"]): symbol = "BTCUSD"
    
    # 3. تحليل اللوت، الأهداف، والستوب لوز
    lot = float(re.search(r'(\d+(\.\d+)?)\s*(lot|لوت|l)', msg_lower).group(1)) if re.search(r'(\d+(\.\d+)?)\s*(lot|لوت|l)', msg_lower) else 0.01
    sl = float(re.search(r'(sl|ستوب لوز|وقف الخسارة)[:\s]*([\d.]+)', msg_lower).group(2)) if re.search(r'(sl|ستوب لوز|وقف الخسارة)[:\s]*([\d.]+)', msg_lower) else 0.0
    target = float(re.search(r'(هدف|target)[:\s]*([\d.]+)', msg_lower).group(2)) if re.search(r'(هدف|target)[:\s]*([\d.]+)', msg_lower) else 0.0
    pips = int(re.search(r'(\d+)\s*(نقطة|بيب|pip)', msg_lower).group(1)) if re.search(r'(\d+)\s*(نقطة|بيب|pip)', msg_lower) else 0
    
    # 4. بناء هيكل الإشارة
    return json.dumps({
        "ACTION": action,
        "SYMBOL": symbol,
        "LOT": lot,
        "SL": sl,
        "TARGET": target,
        "PIPS": pips,
        "MANAGEMENT": {"BREAK_EVEN_TRIGGER": 0.75, "PROFIT_MARGIN": 1.0}
    })

@tg.on(events.NewMessage)
async def handle_signal(event):
    # الفلترة الذكية (مجلد AutoTrade)
    dialog_filters = await tg(functions.messages.GetDialogFiltersRequest())
    is_in_autotrade = any(f.title == "AutoTrade" and event.chat_id in [p.channel_id for p in f.include_peers if hasattr(p, 'channel_id')] for f in dialog_filters)
    
    if not is_in_autotrade: return

    signal_json = parse_to_json(event.raw_text)
    if signal_json:
        print(f"📡 إشارة تم استخراجها: {signal_json}")
        # هنا سيتم لاحقاً ربط الإخراج بـ cTrader API
        await tg.send_message('me', f"✅ إشارة معالجة:\n`{signal_json}`")

async def main():
    await tg.start()
    print("🚀 محرك المترجم (Listener) يعمل بكفاءة...")
    await tg.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
