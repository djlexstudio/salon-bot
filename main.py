import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware 
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://theseven.ru"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

# === WEBHOOK ===
@app.post(settings.WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500)

# === API ДЛЯ MINI APP ===
@app.get("/api/masters")
async def api_get_masters():
    return [{"id": m[0], "name": m[1]} for m in await db.get_masters()]

@app.get("/api/services")
async def api_get_services():
    return [{"id": s[0], "name": s[1], "duration": s[2], "price": s[3]} for s in await db.get_services()]

@app.post("/api/check-slot")
async def api_check_slot(request: Request):
    data = await request.json()
    return {"available": await db.is_slot_free(data["master_id"], data["time"])}

@app.post("/api/book")
async def api_book_appointment(request: Request):
    data = await request.json()
    aid = await db.create_appointment(
        user_id=data["user_id"], user_name=data["user_name"],
        master_id=data["master_id"], service_id=data["service_id"],
        appointment_time=data["appointment_time"]
    )
    # Получаем детали: id, user_id, user_name, master_id, service_id, time, status, created_at, master_chat_id, master_name, service_name, price, duration
    row = await db.get_appointment_details(aid)
    if not row: return {"status": "error"}
    
    msg = (
        f"✨ <b>Новая запись #{row[0]}!</b>\n\n"
        f"👤 Клиент: {row[2]}\n"
        f"💇 Мастер: {row[9]}\n"
        f"✂️ Услуга: {row[10]} ({row[12]} мин)\n"
        f"💰 Стоимость: {row[11]} ₽\n"
        f"🕐 Время: {datetime.fromisoformat(row[5]).strftime('%d.%m.%Y в %H:%M')}"
    )
    
    # Уведомления
    try: await bot.send_message(settings.ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except: pass
    if row[8]: 
        try: await bot.send_message(row[8], msg, parse_mode="HTML")
        except: pass
    try: await bot.send_message(data["user_id"], f"✅ <b>Вы записаны!</b>\n\n{msg}", parse_mode="HTML")
    except: pass
    
    return {"status": "success", "appointment_id": aid}

# === TELEGRAM HANDLERS ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📅 Записаться онлайн", web_app=WebAppInfo(url=settings.WEBAPP_URL))
    ]])
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Нажмите кнопку ниже, чтобы записаться в наш салон красоты.\n"
        "Выберите мастера, услугу и удобное время",
        reply_markup=kb
    )

# === ВРЕМЕННЫЙ ЭНДПОИНТ (удалите после настройки) ===
@app.get("/init-data")
async def init_test_data():
    if await db.get_masters():
        return {"status": "info", "message": "Данные уже есть"}
    
    await db.add_master("Анна", 5934756806, '["1","2","3"]')
    await db.add_service("Стрижка женская", 45, 1500)
    await db.add_service("Окрашивание", 120, 3500)
    await db.add_service("Укладка", 30, 800)
    return {"status": "success", "message": "✅ Тестовые данные добавлены"}

# === STARTUP/SHUTDOWN ===
@app.on_event("startup")
async def on_startup():
    await db.init_db()
    
    # Автоматически добавляем тестовые данные, если их нет
    masters = await db.get_masters()
    if not masters:
        await db.add_master("Анна", 5934756806, '["1","2","3"]') 
        await db.add_service("Стрижка женская", 45, 1500)
        await db.add_service("Окрашивание", 120, 3500)
        await add_service("Укладка", 30, 800)
        logger.info("✅ Тестовые данные добавлены")
    
    url = f"{settings.DOMAIN}{settings.WEBHOOK_PATH}"
    await bot.set_webhook(url, drop_pending_updates=True)
    logger.info(f"✅ Webhook: {url}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()
