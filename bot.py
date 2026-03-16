import telebot
from telebot import types
import sqlite3
import datetime
import time
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===== НАСТРОЙКИ =====
TOKEN = '8632440554:AAG_fvQkmiOYQTJ4W6ML1jCVfdQKxyBD0kQ'
ADMIN_ID = 869161851
ADMIN_USERNAME = "Nilov_Nikita_S_L"
MASTER_NAME = "Анна"
MASTER_ADDRESS = "ул. Ленина, д. 1"
MASTER_PHONE = "+7 (999) 123-45-67"

# URL твоего Mini App
LOCAL_URL = "https://be5e9036066d2ff2-94-125-14-34.serveousercontent.com"
MINI_APP_URL = LOCAL_URL
# =====================

# ===== НАСТРОЙКА БОТА С УВЕЛИЧЕННЫМИ ТАЙМАУТАМИ =====
# Создаем кастомную сессию для бота
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Увеличиваем таймауты
telebot.apihelper.CONNECT_TIMEOUT = 30
telebot.apihelper.READ_TIMEOUT = 30
telebot.apihelper.session = session

bot = telebot.TeleBot(TOKEN)


# ----- БАЗА ДАННЫХ -----
def init_db():
    conn = sqlite3.connect('database.db', check_same_thread=False)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS slots
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT,
                  time TEXT,
                  is_available INTEGER DEFAULT 1)''')

    c.execute('''CREATE TABLE IF NOT EXISTS bookings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  user_name TEXT,
                  user_phone TEXT,
                  services TEXT,
                  total_price INTEGER,
                  date TEXT,
                  time TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")


init_db()


# ----- ФУНКЦИИ ДЛЯ MINI APP (API) -----
def get_available_dates():
    """Возвращает список доступных дат на ближайшие 14 дней"""
    conn = sqlite3.connect('database.db', check_same_thread=False)
    c = conn.cursor()

    dates = []
    today = datetime.datetime.now().date()

    for i in range(14):
        date = today + datetime.timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")

        c.execute('''SELECT time FROM slots 
                     WHERE date = ? AND is_available = 1
                     AND time NOT IN (SELECT time FROM bookings WHERE date = ?)''',
                  (date_str, date_str))
        slots = c.fetchall()

        if slots:
            dates.append({
                'date': date_str,
                'display': date.strftime("%d.%m.%Y"),
                'slots': [s[0] for s in slots]
            })

    conn.close()
    return dates


def get_slots_for_date(date_str):
    """Возвращает свободные слоты на конкретную дату"""
    conn = sqlite3.connect('database.db', check_same_thread=False)
    c = conn.cursor()

    c.execute('''SELECT time FROM slots 
                 WHERE date = ? AND is_available = 1
                 AND time NOT IN (SELECT time FROM bookings WHERE date = ?)''',
              (date_str, date_str))
    slots = [s[0] for s in c.fetchall()]

    conn.close()
    return slots


def create_booking(data):
    """Создает новую запись"""
    conn = sqlite3.connect('database.db', check_same_thread=False)
    c = conn.cursor()

    c.execute('''SELECT id FROM bookings 
                 WHERE date = ? AND time = ?''',
              (data['date'], data['time']))
    if c.fetchone():
        conn.close()
        return False, "Слот уже занят"

    c.execute('''INSERT INTO bookings 
                 (user_id, user_name, user_phone, services, total_price, date, time)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (data['user_id'], data['name'], data['phone'],
               data['services'], data['total_price'],
               data['date'], data['time']))

    booking_id = c.lastrowid
    conn.commit()
    conn.close()
    return True, booking_id


# ----- КОМАНДЫ БОТА -----
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "📱 ОТКРЫТЬ MINI APP",
        web_app=types.WebAppInfo(url=MINI_APP_URL)
    ))

    if user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton(
            "📊 Управление слотами",
            callback_data="admin"
        ))

    try:
        bot.send_message(
            user_id,
            f"👋 Добро пожаловать!\n\n"
            f"✨ Мастер: {MASTER_NAME}\n"
            f"📍 {MASTER_ADDRESS}\n"
            f"📞 {MASTER_PHONE}\n\n"
            f"Нажмите кнопку ниже для быстрой записи:",
            reply_markup=markup,
            timeout=30
        )
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")


# ----- АДМИН-ПАНЕЛЬ -----
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id

    try:
        if call.data == "admin":
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "➕ Добавить слоты на день",
                callback_data="add_slots"
            ))
            markup.add(types.InlineKeyboardButton(
                "📋 Все записи",
                callback_data="view_bookings"
            ))

            bot.edit_message_text(
                "Админ-панель:",
                user_id,
                call.message.message_id,
                reply_markup=markup
            )

        elif call.data == "add_slots":
            msg = bot.send_message(
                user_id,
                "Введите дату в формате ГГГГ-ММ-ДД (например: 2024-12-25):"
            )
            bot.register_next_step_handler(msg, add_slots_step)

        elif call.data == "view_bookings":
            conn = sqlite3.connect('database.db', check_same_thread=False)
            c = conn.cursor()
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            c.execute('''SELECT date, time, user_name, services, total_price 
                         FROM bookings WHERE date >= ? ORDER BY date, time''', (today,))
            bookings = c.fetchall()
            conn.close()

            if bookings:
                text = "📋 БЛИЖАЙШИЕ ЗАПИСИ:\n\n"
                for b in bookings:
                    text += f"📅 {b[0]} {b[1]} - {b[2]}\n💅 {b[3]}\n💰 {b[4]}₽\n➖➖➖\n"
            else:
                text = "📭 Нет записей"

            bot.send_message(user_id, text)

    except Exception as e:
        print(f"❌ Ошибка в callback: {e}")


def add_slots_step(message):
    date_str = message.text.strip()
    user_id = message.from_user.id

    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")

        times = ["10:00", "11:00", "12:00", "13:00", "14:00",
                 "15:00", "16:00", "17:00", "18:00", "19:00"]

        conn = sqlite3.connect('database.db', check_same_thread=False)
        c = conn.cursor()

        c.execute("DELETE FROM slots WHERE date = ?", (date_str,))

        for t in times:
            c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, t))

        conn.commit()
        conn.close()

        bot.send_message(user_id, f"✅ Добавлено {len(times)} слотов на {date_str}")
    except ValueError:
        bot.send_message(user_id, "❌ Неверный формат даты")
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка: {e}")


# ----- ЗАПУСК С ЗАЩИТОЙ ОТ ОШИБОК -----
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН!")
    print("=" * 50)
    print(f"👤 Админ: @{ADMIN_USERNAME}")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"🌐 Mini App URL: {MINI_APP_URL}")
    print("=" * 50)
    print("⏱️ Таймауты увеличены до 30 секунд")
    print("🔄 Автоматические повторные попытки")
    print("=" * 50)

    # Бесконечный цикл с перезапуском при ошибках
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"❌ Ошибка бота: {e}")
            print("🔄 Перезапуск через 10 секунд...")
            time.sleep(10)