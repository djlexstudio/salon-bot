import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings
import database as db

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация
app = FastAPI()
bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

# Состояния для FSM (если понадобится расширить логику бота)
class BookingStates(StatesGroup):
    selecting_service = State()
    selecting_master = State()
    selecting_time = State()

# === TELEGRAM WEBHOOK ===
@app.post(settings.WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Обработчик вебхуков от Telegram"""
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500)

# === MINI APP API ===
@app.get("/api/masters")
async def api_get_masters():
    """API: список мастеров для Mini App"""
    masters = await db.get_masters()
    return [{"id": m[0], "name": m[1]} for m in masters]

@app.get("/api/services")
async def api_get_services():
    """API: список услуг для Mini App"""
    services = await db.get_services()
    return [{"id": s[0], "name": s[1], "duration": s[2], "price": s[3]} for s in services]

@app.post("/api/check-slot")
async def api_check_slot(request: Request):
    """API: проверка занятости слота"""
    data = await request.json()
    master_id = data.get("master_id")
    appointment_time = data.get("time")  # ISO формат: "2024-01-15T14:00:00"
    
    is_free = await db.is_slot_free(master_id, appointment_time)
    return {"available": is_free}

@app.post("/api/book")
async def api_book_appointment(request: Request):
    """API: создание записи"""
    data = await request.json()
    
    # Создаём запись в БД
    appointment_id = await db.create_appointment(
        user_id=data["user_id"],
        user_name=data["user_name"],
        master_id=data["master_id"],
        service_id=data["service_id"],
        appointment_time=data["appointment_time"]
    )
    
    # Получаем детали для уведомления
    details = await db.get_appointment_details(appointment_id)
    
    # Формируем сообщение
    service_name = details[7]  # service_name из JOIN
    master_name = details[6]   # master_name
    price = details[8]         # price
    appt_time = datetime.fromisoformat(details[4]).strftime("%d.%m.%Y в %H:%M")
    
    message = (
        f"✨ <b>Новая запись!</b>\n\n"
        f"👤 Клиент: {details[2]}\n"
        f"💇 Мастер: {master_name}\n"
        f"✂️ Услуга: {service_name} ({details[9]} мин)\n"
        f"💰 Стоимость: {price} ₽\n"
        f"🕐 Время: {appt_time}\n\n"
        f"ID записи: #{appointment_id}"
    )
    
    # Отправляем админу
    try:
        await bot.send_message(settings.ADMIN_CHAT_ID, message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")
    
    # Отправляем мастеру (если указан chat_id)
    master_chat_id = details[5]  # chat_id мастера из таблицы masters
    if master_chat_id:
        try:
            await bot.send_message(master_chat_id, message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление мастеру: {e}")
    
    # Отправляем подтверждение клиенту (если бот может ему написать)
    try:
        await bot.send_message(
            data["user_id"],
            f"✅ <b>Вы записаны!</b>\n\n{master_name}, {service_name}\n🕐 {appt_time}\n💰 {price} ₽",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить подтверждение клиенту: {e}")
    
    return {"status": "success", "appointment_id": appointment_id}

# === TELEGRAM BOT COMMANDS ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start — главная кнопка для открытия Mini App"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📅 Записаться онлайн",
            web_app=WebAppInfo(url=settings.WEBAPP_URL)
        )]
    ])
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Нажмите кнопку ниже, чтобы записаться в наш салон красоты.\n"
        "Выберите мастера, услугу и удобное время — всё за 1 минуту ⚡",
        reply_markup=kb
    )

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Админ-команды (только для вашего chat_id)"""
    if message.from_user.id != settings.ADMIN_CHAT_ID:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="admin_add_master")],
        [InlineKeyboardButton(text="➕ Добавить услугу", callback_data="admin_add_service")],
        [InlineKeyboardButton(text="📋 Все записи", callback_data="admin_bookings")]
    ])
    await message.answer("🔧 Панель администратора", reply_markup=kb)

# === ЗАПУСК ===
@app.on_event("startup")
async def on_startup():
    """Инициализация БД и установка вебхука при старте"""
    await db.init_db()
    
    # Установка вебхука (только если домен уже с HTTPS)
    webhook_url = f"{settings.DOMAIN}{settings.WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"✅ Webhook установлен: {webhook_url}")

@app.on_event("shutdown")
async def on_shutdown():
    """Очистка вебхука при остановке"""
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🔌 Бот остановлен")