import logging
import pyotp
import time
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8806622977:AAFgfwsDzc4KFCdMA-qXE6RPqqToqfATBZY")
ALLOWED_USER_IDS = [int(x) for x in os.environ.get("ALLOWED_USER_IDS", "7993647811").split(",")]
ALLOWED_GROUP_IDS = [int(x) for x in os.environ.get("ALLOWED_GROUP_IDS", "-5189957612").split(",")]

ACCOUNTS = {
    "🐥": "PVQTQTCRHFKC6RKS",
    "金流": "NYU25ADKDD5KXFWOZ2I2P2FM",
    "派單": "FIYCUJRQI5KXCQKP",
    "XY": "PSIQKOI6ADQ3JQR4M7SKEXKPMM2A3MW7",
    "OL": "LKJMOZYCXYMFI6VQWAERGY7L6YI4W4C4",
    "LS": "Y4K7FV3QZFWODVQON46HRJPGF4AFLF5L",
    "XO": "KNFES2DQI5VXOVBW",
    "YS": "2NKUXLJYTHVSLDQD",
    "SH": "OEQZRIOSO27EZSKF",
    "XH": "4I55SP7RWZC7SWLFBO3GA5BDLQ5VZCA2",
    "AI監控": "4I55SP7RWZC7SWLFBO3GA5BDLQ5VZCA2",
 }

logging.basicConfig(level=logging.INFO)

def is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return user_id in ALLOWED_USER_IDS
    return chat_id in ALLOWED_GROUP_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ 無權限")
        return
    await update.message.reply_text("✅ Bot 啟動成功！\n發送 /otp 選擇帳號取得驗證碼")

async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ 無權限")
        return
    keyboard = []
    for name in ACCOUNTS.keys():
        keyboard.append([InlineKeyboardButton(name, callback_data=name)])
    keyboard.append([InlineKeyboardButton("📋 全部顯示", callback_data="__ALL__")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("請選擇帳號：", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = query.data
    remaining = int(30 - (time.time() % 30))
    if name == "__ALL__":
        msg = f"🔐 所有驗證碼（{remaining} 秒後更新）\n\n"
        for n, secret in ACCOUNTS.items():
            totp = pyotp.TOTP(secret)
            code = totp.now()
            msg += f"{n}：`{code}`\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    else:
        secret = ACCOUNTS.get(name)
        if secret:
            totp = pyotp.TOTP(secret)
            code = totp.now()
            await query.edit_message_text(
                f"🔐 {name}\n\n驗證碼：\n`{code}`\n\n⏱ {remaining} 秒後更新",
                parse_mode="Markdown"
            )

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("otp", get_otp))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ Bot 執行中...")
    app.run_polling()

if __name__ == "__main__":
    main()