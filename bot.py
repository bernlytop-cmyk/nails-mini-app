import telebot
from telebot import types
import sqlite3
import datetime
import time
import os
import threading
from flask import Flask, render_template, request, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===== НАСТРОЙКИ =====
TOKEN = '8686090602:AAFcFqJPPafTXKHRa0CcwB6q8AwOAVB4Kdo'
ADMIN_ID = 869161851
ADMIN_USERNAME = "Nilov_Nikita_S_L"
MASTER_NAME = "Анна"
MASTER_ADDRESS = "ул. Ленина, д. 1"
MASTER_PHONE = "+7 (999) 123-45-67"

# URL Mini App
MINI_APP_URL = "https://nails-mini-app-1.onrender.com"

# ===== НАСТРОЙКА СЕССИИ =====
session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

telebot.apihelper.CONNECT_TIMEOUT = 30
telebot.apihelper.READ_TIMEOUT = 30
telebot.apihelper.session = session

# ===== УНИКАЛЬНОЕ ИМЯ БАЗЫ ДАННЫХ (СТАРЫЕ ФАЙЛЫ БОЛЬШЕ НЕ ИСПОЛЬЗУЮТСЯ) =====
DB_NAME = 'database_new.db'  # Новое имя, старые файлы игнорируются

print("🔍 Проверка наличия старых баз данных...")
for old_db in ['database.db', 'database.db-journal', 'database_new.db-journal']:
    if os.path.exists(old_db):
        try:
            os.remove(old_db)
            print(f"🗑️ Удален старый файл: {old_db}")
        except:
            pass


# ===== БАЗА ДАННЫХ =====
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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
    print(f"✅ НОВАЯ база данных создана: {DB_NAME}")


init_db()

# ===== FLASK ПРИЛОЖЕНИЕ =====
app = Flask(__name__)

# Услуги с ценами
SERVICES = [
    {"name": "💅 Маникюр + покрытие", "price": 2000},
    {"name": "💅 Наращивание ногтей", "price": 3000},
    {"name": "💅 Коррекция ногтей", "price": 2500},
    {"name": "🎨 Дизайн ногтей (1 ноготь)", "price": 500},
    {"name": "🎨 Дизайн ногтей (все)", "price": 1500},
    {"name": "🔨 Снятие покрытия", "price": 500},
    {"name": "🦶 Педикюр", "price": 2500}
]


# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ =====
def add_slots_for_day(date_str):
    times = ["10:00", "11:00", "12:00", "13:00", "14:00",
             "15:00", "16:00", "17:00", "18:00", "19:00"]

    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM slots WHERE date = ?", (date_str,))
    for t in times:
        c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, t))
    conn.commit()
    conn.close()
    return len(times)


def get_all_dates():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT date FROM slots ORDER BY date")
    dates = [d[0] for d in c.fetchall()]
    conn.close()
    return dates


def get_slots_by_date(date_str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT time FROM slots WHERE date = ? ORDER BY time", (date_str,))
    slots = [s[0] for s in c.fetchall()]
    conn.close()
    return slots


def get_free_slots(date_str):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT time FROM slots 
                 WHERE date = ? AND is_available = 1
                 AND time NOT IN (SELECT time FROM bookings WHERE date = ?)''',
              (date_str, date_str))
    slots = [s[0] for s in c.fetchall()]
    conn.close()
    return slots


def create_booking(data):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO bookings 
                 (user_id, user_name, user_phone, services, total_price, date, time)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (data['user_id'], data['name'], data['phone'],
               data['services'], data['total_price'],
               data['date'], data['time']))
    booking_id = c.lastrowid
    conn.commit()
    conn.close()
    return booking_id


def get_today_bookings():
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT time, user_name, user_phone, services, total_price 
                 FROM bookings WHERE date = ? ORDER BY time''', (today,))
    bookings = c.fetchall()
    conn.close()
    return bookings


def get_all_future_bookings():
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT date, time, user_name, user_phone, services, total_price 
                 FROM bookings WHERE date >= ? ORDER BY date, time''', (today,))
    bookings = c.fetchall()
    conn.close()
    return bookings


def get_busy_slots(date_str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT time FROM bookings WHERE date = ?", (date_str,))
    busy = [b[0] for b in c.fetchall()]
    conn.close()
    return busy


def get_booking_info(date_str, time_str):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT user_name, user_phone, services, total_price 
                 FROM bookings WHERE date = ? AND time = ?''', (date_str, time_str))
    info = c.fetchone()
    conn.close()
    return info


# ===== FLASK МАРШРУТЫ =====
@app.route('/')
def index():
    return render_template('index.html',
                           master_name=MASTER_NAME,
                           address=MASTER_ADDRESS,
                           phone=MASTER_PHONE)


@app.route('/api/services')
def get_services():
    return jsonify(SERVICES)


@app.route('/api/dates')
def get_dates():
    dates = []
    today = datetime.datetime.now().date()

    for i in range(14):
        date = today + datetime.timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        slots = get_free_slots(date_str)
        if slots:
            dates.append({
                'date': date_str,
                'display': date.strftime("%d.%m.%Y"),
                'slots': slots
            })

    return jsonify(dates)


@app.route('/api/slots/<date>')
def get_slots(date):
    slots = get_free_slots(date)
    return jsonify(slots)


@app.route('/api/book', methods=['POST'])
def book():
    data = request.json
    booking_id = create_booking(data)

    try:
        admin_text = f"""
🔔 НОВАЯ ЗАПИСЬ!
👤 Имя: {data['name']}
📞 Телефон: {data['phone']}
💅 Услуги: {data['services']}
💰 Сумма: {data['total_price']}₽
📅 Дата: {data['date']}
⏰ Время: {data['time']}
        """
        bot.send_message(ADMIN_ID, admin_text)
    except:
        pass

    return jsonify({'success': True, 'id': booking_id})


@app.route('/health')
def health():
    return "OK", 200


# ===== ЗАПУСК FLASK В ОТДЕЛЬНОМ ПОТОКЕ =====
def run_flask():
    port = int(os.environ.get('PORT', 8000))
    print(f"🚀 Flask сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)


flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()
print("✅ Flask сервер запущен в фоне")

# ===== БОТ =====
bot = telebot.TeleBot(TOKEN)


# ----- АДМИН-МЕНЮ -----
def show_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('📅 Управление слотами', '📋 Записи на сегодня')
    markup.row('📊 Все записи', '📈 Статистика')
    markup.row('➕ Добавить слоты на день', '❌ Удалить все слоты')
    markup.row('📱 Открыть Mini App', '🔄 Перезагрузить')
    return markup


# ----- КОМАНДА СТАРТ -----
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        bot.send_message(
            user_id,
            f"👋 Здравствуйте, {MASTER_NAME}!\n\n"
            f"📍 {MASTER_ADDRESS}\n"
            f"📞 {MASTER_PHONE}\n\n"
            f"Вы в админ-панели:",
            reply_markup=show_admin_menu()
        )
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "📱 ЗАПИСАТЬСЯ",
            web_app=types.WebAppInfo(url=MINI_APP_URL)
        ))

        bot.send_message(
            user_id,
            f"👋 Добро пожаловать!\n\n"
            f"✨ Мастер: {MASTER_NAME}\n"
            f"📍 {MASTER_ADDRESS}\n"
            f"📞 {MASTER_PHONE}\n\n"
            f"Нажмите кнопку ниже для записи:",
            reply_markup=markup
        )


# ----- АДМИНСКИЕ КОМАНДЫ -----
@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID)
def admin_commands(message):
    user_id = message.from_user.id
    text = message.text

    if text == '📅 Управление слотами':
        dates = get_all_dates()
        if not dates:
            bot.send_message(user_id, "❌ Нет добавленных дат. Сначала добавьте слоты.")
            return

        markup = types.InlineKeyboardMarkup(row_width=2)
        for date_str in dates:
            date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            slots = get_slots_by_date(date_str)
            markup.add(types.InlineKeyboardButton(
                f"{date_show} ({len(slots)} сл.)",
                callback_data=f"manage_{date_str}"
            ))
        bot.send_message(user_id, "📅 Выберите дату для управления:", reply_markup=markup)

    elif text == '📋 Записи на сегодня':
        bookings = get_today_bookings()
        if bookings:
            msg = "📋 ЗАПИСИ НА СЕГОДНЯ:\n\n"
            for b in bookings:
                msg += f"⏰ {b[0]} - {b[1]}\n📞 {b[2]}\n💅 {b[3]}\n💰 {b[4]}₽\n➖➖➖\n"
        else:
            msg = "✅ На сегодня записей нет"
        bot.send_message(user_id, msg)

    elif text == '📊 Все записи':
        bookings = get_all_future_bookings()
        if bookings:
            msg = "📊 ВСЕ БУДУЩИЕ ЗАПИСИ:\n\n"
            current_date = ""
            for b in bookings:
                if current_date != b[0]:
                    current_date = b[0]
                    date_show = datetime.datetime.strptime(b[0], "%Y-%m-%d").strftime("%d.%m.%Y")
                    msg += f"\n📅 {date_show}:\n"
                msg += f"   ⏰ {b[1]} - {b[2]}\n   📞 {b[3]}\n   💅 {b[4]}\n   ➖➖➖\n"
        else:
            msg = "📭 Нет будущих записей"
        bot.send_message(user_id, msg)

    elif text == '📈 Статистика':
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM bookings")
        total = c.fetchone()[0]
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM bookings WHERE date = ?", (today,))
        today_count = c.fetchone()[0]
        conn.close()

        msg = f"📊 СТАТИСТИКА\n\n"
        msg += f"📝 Всего записей: {total}\n"
        msg += f"📅 Сегодня: {today_count}\n"
        bot.send_message(user_id, msg)

    elif text == '➕ Добавить слоты на день':
        msg = bot.send_message(
            user_id,
            "Введите дату в формате ГГГГ-ММ-ДД\n"
            "Например: 2024-12-25"
        )
        bot.register_next_step_handler(msg, add_slots_step)

    elif text == '❌ Удалить все слоты':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Да, удалить все", callback_data="delete_all"))
        markup.add(types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel"))
        bot.send_message(user_id, "⚠️ Вы уверены?", reply_markup=markup)

    elif text == '📱 Открыть Mini App':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "📱 ОТКРЫТЬ MINI APP",
            web_app=types.WebAppInfo(url=MINI_APP_URL)
        ))
        bot.send_message(user_id, "Нажмите кнопку для открытия:", reply_markup=markup)

    elif text == '🔄 Перезагрузить':
        bot.send_message(user_id, "🔄 Перезагрузка...", reply_markup=show_admin_menu())


def add_slots_step(message):
    date_str = message.text.strip()
    user_id = message.from_user.id

    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
        added = add_slots_for_day(date_str)
        bot.send_message(user_id, f"✅ Добавлено {added} слотов на {date_str}")
    except ValueError:
        bot.send_message(user_id, "❌ Неверный формат даты")


# ----- ОБРАБОТКА INLINE КНОПОК -----
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id

    try:
        if call.data.startswith("manage_"):
            date_str = call.data.replace("manage_", "")
            slots = get_slots_by_date(date_str)
            busy = get_busy_slots(date_str)
            date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

            markup = types.InlineKeyboardMarkup(row_width=4)
            for time in ["10:00", "11:00", "12:00", "13:00", "14:00",
                         "15:00", "16:00", "17:00", "18:00", "19:00"]:
                if time in slots:
                    if time in busy:
                        markup.add(types.InlineKeyboardButton(
                            f"🔴 {time}",
                            callback_data=f"info_{date_str}_{time}"
                        ))
                    else:
                        markup.add(types.InlineKeyboardButton(
                            f"🟢 {time}",
                            callback_data=f"delete_{date_str}_{time}"
                        ))
                else:
                    markup.add(types.InlineKeyboardButton(
                        f"⚪ {time}",
                        callback_data=f"add_{date_str}_{time}"
                    ))

            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_dates"))

            bot.edit_message_text(
                f"📅 Управление слотами на {date_show}:",
                user_id,
                call.message.message_id,
                reply_markup=markup
            )

        elif call.data.startswith("add_"):
            _, date_str, time_str = call.data.split("_", 2)
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, time_str))
                conn.commit()
                bot.answer_callback_query(call.id, "✅ Слот добавлен")
            except:
                bot.answer_callback_query(call.id, "❌ Слот уже существует")
            conn.close()

            new_call = type('Call', (), {'data': f"manage_{date_str}", 'message': call.message, 'id': call.id})
            callback_handler(new_call)

        elif call.data.startswith("delete_"):
            _, date_str, time_str = call.data.split("_", 2)
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM slots WHERE date = ? AND time = ?", (date_str, time_str))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "❌ Слот удален")

            new_call = type('Call', (), {'data': f"manage_{date_str}", 'message': call.message, 'id': call.id})
            callback_handler(new_call)

        elif call.data.startswith("info_"):
            _, date_str, time_str = call.data.split("_", 2)
            info = get_booking_info(date_str, time_str)
            if info:
                msg = f"📋 ЗАПИСЬ:\n👤 {info[0]}\n📞 {info[1]}\n💅 {info[2]}\n💰 {info[3]}₽"
            else:
                msg = "❌ Информация не найдена"
            bot.answer_callback_query(call.id, msg, show_alert=True)

        elif call.data == "back_to_dates":
            dates = get_all_dates()
            markup = types.InlineKeyboardMarkup(row_width=2)
            for date_str in dates:
                date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
                slots = get_slots_by_date(date_str)
                markup.add(types.InlineKeyboardButton(
                    f"{date_show} ({len(slots)} сл.)",
                    callback_data=f"manage_{date_str}"
                ))
            bot.edit_message_text("📅 Выберите дату:", user_id, call.message.message_id, reply_markup=markup)

        elif call.data == "delete_all":
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM slots")
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ Все слоты удалены")
            bot.delete_message(user_id, call.message.message_id)

        elif call.data == "cancel":
            bot.answer_callback_query(call.id, "❌ Отменено")
            bot.delete_message(user_id, call.message.message_id)

    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")


# ===== ЗАПУСК БОТА =====
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН!")
    print("=" * 50)
    print(f"👤 Админ: @{ADMIN_USERNAME}")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"🌐 Mini App URL: {MINI_APP_URL}")
    print(f"📁 База данных: {DB_NAME}")
    print("=" * 50)

    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            if "409" in str(e):
                print("⚠️ Конфликт с другим экземпляром бота. Это нормально, бот работает.")
                time.sleep(5)
            else:
                print(f"❌ Ошибка: {e}")
                time.sleep(10)