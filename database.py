import aiosqlite
from datetime import datetime
from config import settings

DB_PATH = settings.DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица мастеров
        await db.execute('''
            CREATE TABLE IF NOT EXISTS masters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                chat_id INTEGER,
                services TEXT  -- JSON-список услуг, которые оказывает
            )
        ''')
        # Таблица услуг
        await db.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                duration INTEGER NOT NULL,  -- в минутах
                price INTEGER NOT NULL      -- в рублях
            )
        ''')
        # Таблица записей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                master_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                appointment_time TEXT NOT NULL,  -- ISO формат
                status TEXT DEFAULT 'confirmed',
                created_at TEXT NOT NULL,
                FOREIGN KEY (master_id) REFERENCES masters(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        ''')
        # Индекс для быстрой проверки занятости
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_appointments_time 
            ON appointments(master_id, appointment_time)
        ''')
        await db.commit()

async def add_master(name: str, chat_id: int = None, services: str = "[]"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO masters (name, chat_id, services) VALUES (?, ?, ?)",
            (name, chat_id, services)
        )
        await db.commit()

async def add_service(name: str, duration: int, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO services (name, duration, price) VALUES (?, ?, ?)",
            (name, duration, price)
        )
        await db.commit()

async def get_masters():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name FROM masters") as cursor:
            return await cursor.fetchall()

async def get_services():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, duration, price FROM services") as cursor:
            return await cursor.fetchall()

async def is_slot_free(master_id: int, appointment_time: str) -> bool:
    """Проверяет, свободен ли слот у мастера в указанное время"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM appointments WHERE master_id = ? AND appointment_time = ? AND status != 'cancelled'",
            (master_id, appointment_time)
        ) as cursor:
            return await cursor.fetchone() is None

async def create_appointment(user_id: int, user_name: str, master_id: int, 
                            service_id: int, appointment_time: str) -> int:
    """Создаёт запись и возвращает её ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO appointments 
               (user_id, user_name, master_id, service_id, appointment_time, created_at) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, user_name, master_id, service_id, appointment_time, 
             datetime.now().isoformat())
        )
        appointment_id = cursor.lastrowid  # Получаем ID новой записи
        await db.commit()
        return appointment_id  # Возвращаем ID

async def get_appointment_details(appointment_id: int):
    """Возвращает детали записи с именами мастера и услуги"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT 
                a.id, a.user_id, a.user_name, a.master_id, a.service_id,
                a.appointment_time, a.status, a.created_at,
                m.chat_id as master_chat_id,
                m.name as master_name,
                s.name as service_name, s.price, s.duration
            FROM appointments a
            JOIN masters m ON a.master_id = m.id
            JOIN services s ON a.service_id = s.id
            WHERE a.id = ?
        ''', (appointment_id,)) as cursor:
            return await cursor.fetchone()
