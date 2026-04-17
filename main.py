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
    allow_origins=[
        "https://app.theseven.ru",
        "https://theseven.ru",  # ✅ Добавили основной домен
        "https://*.theseven.ru"  # И все поддомены
    ],
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
    try:
        data = await request.json()
        logger.info(f"📥 Получен запрос на запись: {data}")
        
        # Проверяем, существуют ли мастер и услуга
        masters = await db.get_masters()
        services = await db.get_services()
        
        master_exists = any(m[0] == data["master_id"] for m in masters)
        service_exists = any(s[0] == data["service_id"] for s in services)
        
        if not master_exists:
            logger.error(f"❌ Мастер с id={data['master_id']} не найден. Доступные: {masters}")
            return {"status": "error", "message": f"Мастер не найден. Доступные ID: {[m[0] for m in masters]}"}
        
        if not service_exists:
            logger.error(f"❌ Услуга с id={data['service_id']} не найден. Доступные: {services}")
            return {"status": "error", "message": f"Услуга не найдена. Доступные ID: {[s[0] for s in services]}"}
        
        # Создаём запись
        aid = await db.create_appointment(
            user_id=data["user_id"],
            user_name=data["user_name"],
            master_id=data["master_id"],
            service_id=data["service_id"],
            appointment_time=data["appointment_time"]
        )
        logger.info(f"✅ Запись создана с id={aid}")
        
        # Получаем детали для уведомления (упрощённо)
        async with aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute('''
                SELECT m.name, s.name, s.price, s.duration 
                FROM appointments a
                JOIN masters m ON a.master_id = m.id
                JOIN services s ON a.service_id = s.id
                WHERE a.id = ?
            ''', (aid,)) as cursor:
                row = await cursor.fetchone()
        
        if not row:
            logger.error(f"❌ Не удалось получить детали записи #{aid}")
            return {"status": "error", "message": "Не удалось получить детали записи"}
        
        master_name, service_name, price, duration = row
        appt_time = datetime.fromisoformat(data["appointment_time"]).strftime("%d.%m.%Y в %H:%M")
        
        # Формируем сообщение
        msg = (
            f"✨ <b>Новая запись #{aid}!</b>\n\n"
            f"👤 Клиент: {data['user_name']}\n"
            f"💇 Мастер: {master_name}\n"
            f"✂️ Услуга: {service_name} ({duration} мин)\n"
            f"💰 Стоимость: {price} ₽\n"
            f"🕐 Время: {appt_time}"
        )
        
        # Отправляем уведомления
        try:
            await bot.send_message(settings.ADMIN_CHAT_ID, msg, parse_mode="HTML")
            logger.info("✅ Уведомление админу отправлено")
        except Exception as e:
            logger.error(f"⚠️ Не удалось отправить админу: {e}")
        
        # Мастеру (если указан chat_id)
        async with aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute(
                "SELECT chat_id FROM masters WHERE id = ?", 
                (data["master_id"],)
            ) as cursor:
                master_row = await cursor.fetchone()
        
        if master_row and master_row[0]:
            try:
                await bot.send_message(master_row[0], msg, parse_mode="HTML")
                logger.info("✅ Уведомление мастеру отправлено")
            except Exception as e:
                logger.error(f"⚠️ Не удалось отправить мастеру: {e}")
        
        # Клиенту
        try:
            await bot.send_message(
                data["user_id"],
                f"✅ <b>Вы записаны!</b>\n\n{master_name}, {service_name}\n🕐 {appt_time}\n💰 {price} ₽",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"⚠️ Не удалось отправить клиенту: {e}")
        
        return {"status": "success", "appointment_id": aid}
        
    except Exception as e:
        logger.error(f"💥 Критическая ошибка в /api/book: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
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
        await db.add_master("Анна", 5934756806, '["1","2","3"]')  # замените на ваш chat_id
        await db.add_service("Стрижка женская", 45, 1500)
        await db.add_service("Окрашивание", 120, 3500)
        await db.add_service("Укладка", 30, 800)  # ✅ ИСПРАВЛЕНО: добавлен db.
        logger.info("✅ Тестовые данные добавлены")
    
    url = f"{settings.DOMAIN}{settings.WEBHOOK_PATH}"
    await bot.set_webhook(url, drop_pending_updates=True)
    logger.info(f"✅ Webhook: {url}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()
