"""旅遊小工具 Telegram Bot：串接 Google Maps 路線規劃與導航。

指令：
  /route 起點 | 終點        規劃路線（只給終點時，起點用你分享的位置或手機目前位置）
  /trip A | B | C | ...      多站行程（依序經過每一站）
  /near 關鍵字               在 Google Maps 搜尋附近地點
  傳送「位置」               記住你的位置，當作之後路線的起點

環境變數：
  TRAVEL_BOT_TOKEN       Telegram Bot Token（必填）
  GOOGLE_MAPS_API_KEY    Google Routes API 金鑰（選填；沒有時只提供導航連結，不顯示距離/時間/步驟）
  TRAVEL_ALLOWED_USER_IDS  允許使用的使用者 ID，逗號分隔（選填；留空代表所有人可用）
"""
import logging
import os
from urllib.parse import urlencode

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("TRAVEL_BOT_TOKEN", "")
MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
ALLOWED_USER_IDS = [int(x) for x in os.environ.get("TRAVEL_ALLOWED_USER_IDS", "").split(",") if x.strip()]

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MAX_STEPS = 15

# 交通方式：(按鈕文字, Google Maps 網址參數, Routes API travelMode)
MODES = {
    "driving": ("🚗 開車", "driving", "DRIVE"),
    "transit": ("🚇 大眾運輸", "transit", "TRANSIT"),
    "walking": ("🚶 步行", "walking", "WALK"),
    "bicycling": ("🚲 單車", "bicycling", "BICYCLE"),
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def is_authorized(update: Update) -> bool:
    return not ALLOWED_USER_IDS or update.effective_user.id in ALLOWED_USER_IDS


def parse_stops(text: str) -> list[str]:
    return [s.strip() for s in text.split("|") if s.strip()]


def maps_directions_url(origin: str | None, destination: str, waypoints: list[str], mode: str) -> str:
    """產生 Google Maps 導航網址，手機點開會直接進入 Google Maps App 導航。"""
    params = {"api": "1", "destination": destination, "travelmode": MODES[mode][1]}
    if origin:
        params["origin"] = origin
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    if not origin:
        # 沒有指定起點 → 從目前位置直接開始導航
        params["dir_action"] = "navigate"
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def maps_search_url(query: str) -> str:
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query})


def to_waypoint(stop: str) -> dict:
    """Routes API 的地點格式：「緯度,經度」轉座標，其他當地址。"""
    parts = stop.split(",")
    if len(parts) == 2:
        try:
            lat, lng = float(parts[0]), float(parts[1])
            return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
        except ValueError:
            pass
    return {"address": stop}


async def compute_route(origin: str, destination: str, waypoints: list[str], mode: str) -> str | None:
    """呼叫 Google Routes API 取得距離、時間與逐步指引；沒有金鑰或失敗時回傳 None。"""
    if not MAPS_API_KEY:
        return None
    travel_mode = MODES[mode][2]
    body = {
        "origin": to_waypoint(origin),
        "destination": to_waypoint(destination),
        "travelMode": travel_mode,
        "languageCode": "zh-TW",
        "units": "METRIC",
    }
    if waypoints:
        if travel_mode == "TRANSIT":
            return "⚠️ 大眾運輸模式不支援中途停靠點，請改用其他交通方式或點下方連結查看。"
        body["intermediates"] = [to_waypoint(w) for w in waypoints]
    if travel_mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    headers = {
        "X-Goog-Api-Key": MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "routes.localizedValues,"
            "routes.legs.localizedValues,"
            "routes.legs.steps.navigationInstruction,"
            "routes.legs.steps.localizedValues,"
            "routes.legs.steps.transitDetails"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(ROUTES_URL, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Routes API 失敗：%s", e)
        return "⚠️ 無法取得路線資訊，請直接點下方連結於 Google Maps 查看。"

    routes = data.get("routes")
    if not routes:
        return "😕 找不到路線，請確認地點名稱是否正確。"
    return format_route(routes[0])


def format_route(route: dict) -> str:
    total = route.get("localizedValues", {})
    lines = [f"📏 {total.get('distance', {}).get('text', '?')}　⏱ {total.get('duration', {}).get('text', '?')}"]
    legs = route.get("legs", [])
    step_count = 0
    for i, leg in enumerate(legs, 1):
        if len(legs) > 1:
            leg_vals = leg.get("localizedValues", {})
            lines.append(
                f"\n📍 第 {i} 段（{leg_vals.get('distance', {}).get('text', '?')}，"
                f"{leg_vals.get('duration', {}).get('text', '?')}）"
            )
        else:
            lines.append("")
        for step in leg.get("steps", []):
            if step_count >= MAX_STEPS:
                lines.append("…（其餘步驟請開啟 Google Maps 查看）")
                return "\n".join(lines)
            step_count += 1
            transit = step.get("transitDetails")
            if transit:
                line = transit.get("transitLine", {})
                stops = transit.get("stopDetails", {})
                name = line.get("nameShort") or line.get("name", "")
                text = (
                    f"搭乘 {name}：{stops.get('departureStop', {}).get('name', '')} → "
                    f"{stops.get('arrivalStop', {}).get('name', '')}（{transit.get('stopCount', '?')} 站）"
                )
            else:
                text = step.get("navigationInstruction", {}).get("instructions", "")
            if not text:
                continue
            dist = step.get("localizedValues", {}).get("distance", {}).get("text", "")
            lines.append(f"{step_count}. {text}" + (f"（{dist}）" if dist else ""))
    return "\n".join(lines)


def route_keyboard(url: str, current_mode: str) -> InlineKeyboardMarkup:
    mode_buttons = [
        InlineKeyboardButton(("✅ " if key == current_mode else "") + label, callback_data=f"mode:{key}")
        for key, (label, _, _) in MODES.items()
    ]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧭 開啟 Google Maps 導航", url=url)],
        mode_buttons[:2],
        mode_buttons[2:],
    ])


async def build_route_reply(route: dict) -> tuple[str, InlineKeyboardMarkup]:
    origin, destination, waypoints, mode = route["origin"], route["destination"], route["waypoints"], route["mode"]
    title_stops = [origin or "📍 目前位置", *waypoints, destination]
    text = "🗺 " + " → ".join(title_stops) + f"\n交通方式：{MODES[mode][0]}\n"
    if origin:
        summary = await compute_route(origin, destination, waypoints, mode)
        if summary:
            text += "\n" + summary
    else:
        text += "\n（未指定起點，將從手機目前位置開始導航。傳送你的位置可預覽距離與時間）"
    url = maps_directions_url(origin, destination, waypoints, mode)
    return text, route_keyboard(url, mode)


async def send_route(update: Update, context: ContextTypes.DEFAULT_TYPE, stops: list[str]):
    saved_location = context.user_data.get("location")
    if len(stops) == 1:
        origin, destination, waypoints = saved_location, stops[0], []
    else:
        origin, destination, waypoints = stops[0], stops[-1], stops[1:-1]
    route = {"origin": origin, "destination": destination, "waypoints": waypoints, "mode": "driving"}
    context.user_data["route"] = route
    text, keyboard = await build_route_reply(route)
    await update.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ 無權限")
        return
    await update.message.reply_text(
        "🧳 旅遊小幫手\n\n"
        "/route 台北車站 | 九份老街 — 規劃路線\n"
        "/route 九份老街 — 從你目前位置出發\n"
        "/trip 台北車站 | 十分老街 | 九份老街 — 多站行程\n"
        "/near 咖啡廳 — 搜尋附近地點\n"
        "📎 傳送「位置」可設定起點"
    )


async def route_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ 無權限")
        return
    stops = parse_stops(" ".join(context.args))
    if not stops:
        await update.message.reply_text("用法：/route 起點 | 終點\n或：/route 終點（從目前位置出發）")
        return
    await send_route(update, context, stops)


async def trip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ 無權限")
        return
    stops = parse_stops(" ".join(context.args))
    if len(stops) < 2:
        await update.message.reply_text("用法：/trip 第一站 | 第二站 | 第三站 ...（至少兩站）")
        return
    await send_route(update, context, stops)


async def near_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ 無權限")
        return
    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("用法：/near 關鍵字，例如 /near 拉麵")
        return
    location = context.user_data.get("location")
    query = f"{keyword} near {location}" if location else keyword
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"🔍 在 Google Maps 搜尋「{keyword}」", url=maps_search_url(query))]])
    await update.message.reply_text(f"🔍 搜尋：{keyword}", reply_markup=keyboard)


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    loc = update.message.location
    context.user_data["location"] = f"{loc.latitude},{loc.longitude}"
    await update.message.reply_text("📍 已記住你的位置！現在輸入 /route 目的地 即可規劃路線。")


async def mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    route = context.user_data.get("route")
    mode = query.data.split(":", 1)[1]
    if not route or mode not in MODES:
        await query.edit_message_text("⏰ 路線已過期，請重新輸入 /route")
        return
    if mode == route["mode"]:
        return
    route["mode"] = mode
    text, keyboard = await build_route_reply(route)
    await query.edit_message_text(text, reply_markup=keyboard, disable_web_page_preview=True)


def main():
    if not BOT_TOKEN:
        raise SystemExit("請設定環境變數 TRAVEL_BOT_TOKEN")
    if not MAPS_API_KEY:
        logger.warning("未設定 GOOGLE_MAPS_API_KEY，只會提供 Google Maps 導航連結")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("route", route_cmd))
    app.add_handler(CommandHandler("trip", trip_cmd))
    app.add_handler(CommandHandler("near", near_cmd))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(CallbackQueryHandler(mode_handler, pattern=r"^mode:"))
    print("✅ 旅遊 Bot 執行中...")
    app.run_polling()


if __name__ == "__main__":
    main()
