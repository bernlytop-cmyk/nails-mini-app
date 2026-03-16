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
TOKEN = '8632440554:AAG_fvQkmiOYQTJ4W6ML1jCVfdQKxyBD0kQ'
ADMIN_ID = 869161851
ADMIN_USERNAME = "Nilov_Nikita_S_L"
MASTER_NAME = "София"
MASTER_ADDRESS = "ул. Ленина, д. 1"
MASTER_PHONE = "+7 (999) 123-45-67"

# ⚠️ ЭТОТ URL ДОЛЖЕН БЫТЬ ТВОИМ АКТУАЛЬНЫМ
MINI_APP_URL = "https://nails-mini-app-zkjs.onrender.com"

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

# ===== НОВЫЙ ПРАЙС-ЛИСТ С ДЛИТЕЛЬНОСТЬЮ =====
# Каждая услуга: name, price, duration_minutes
SERVICES = [
    # БРОВИ
    {"name": "👁️ Окрашивание + коррекция бровей", "price": 1300, "duration": 60},
    {"name": "👁️ Окрашивание бровей", "price": 1100, "duration": 30},
    {"name": "👁️ Д/у + окрашивание + коррекция бровей", "price": 1700, "duration": 60},
    {"name": "👁️ Д/у + окрашивание/коррекция бровей", "price": 1500, "duration": 40},
    {"name": "👁️ Окрашивание ресниц", "price": 400, "duration": 20},
    {"name": "👁️ Коррекция бровей", "price": 700, "duration": 30},
    {"name": "👁️ Депиляция зоны над губой/нос", "price": 300, "duration": 5},
    
    # МАКИЯЖ
    {"name": "💄 Макияж дневной (без акцента)", "price": 1700, "duration": 40},
    {"name": "💄 Макияж дневной (с акцентом + декольте)", "price": 3000, "duration": 60},
    {"name": "💇‍♀️ Легкие локоны/голливудская волна/мальвинка", "price": 2000, "duration": 60},
    {"name": "✨ Полный образ (макияж + локоны)", "price": 4800, "duration": 120},
]

# Словарь для быстрого доступа
SERVICES_DICT = {s["name"]: s for s in SERVICES}

# ===== БАЗА ДАННЫХ =====
DB_NAME = 'database_new.db'

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Таблица слотов - теперь храним 15-минутные интервалы
    c.execute('''CREATE TABLE IF NOT EXISTS slots
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT,
                  time TEXT,
                  is_available INTEGER DEFAULT 1)''')
    
    # Таблица записей
    c.execute('''CREATE TABLE IF NOT EXISTS bookings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  user_name TEXT,
                  user_phone TEXT,
                  services TEXT,
                  total_price INTEGER,
                  total_duration INTEGER,
                  date TEXT,
                  start_time TEXT,
                  end_time TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    print(f"✅ База данных создана: {DB_NAME}")

init_db()

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С ВРЕМЕНЕМ =====
def time_to_minutes(time_str):
    """Переводит время '10:00' в минуты от начала дня (600)"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def minutes_to_time(minutes):
    """Переводит минуты обратно в строку времени"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def get_time_slots():
    """Генерирует все 15-минутные слоты с 10:00 до 19:00"""
    slots = []
    for hour in range(10, 19):
        for minute in [0, 15, 30, 45]:
            slots.append(f"{hour:02d}:{minute:02d}")
    return slots

def get_busy_intervals(date_str):
    """Возвращает занятые интервалы для даты в формате (start_min, end_min)"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT start_time, end_time FROM bookings WHERE date = ?", (date_str,))
    busy = []
    for row in c.fetchall():
        start_min = time_to_minutes(row[0])
        end_min = time_to_minutes(row[1])
        busy.append((start_min, end_min))
    conn.close()
    return busy

def find_available_slots(date_str, duration):
    """Находит все доступные слоты для услуги заданной длительности"""
    all_slots = get_time_slots()
    busy_intervals = get_busy_intervals(date_str)
    
    available = []
    all_minutes = [time_to_minutes(t) for t in all_slots]
    
    for start_min in all_minutes:
        end_min = start_min + duration
        # Проверяем, не выходит ли за пределы рабочего дня
        if end_min > 19*60:  # 19:00 = 1140 минут
            continue
        
        # Проверяем, пересекается ли с занятыми интервалами
        is_free = True
        for busy_start, busy_end in busy_intervals:
            if not (end_min <= busy_start or start_min >= busy_end):
                is_free = False
                break
        
        if is_free:
            available.append(minutes_to_time(start_min))
    
    return available

def is_combination_possible(date_str, services, start_time):
    """Проверяет, можно ли разместить комбинацию услуг, начиная с start_time"""
    start_min = time_to_minutes(start_time)
    total_duration = sum(SERVICES_DICT[s]["duration"] for s in services)
    end_min = start_min + total_duration
    
    # Проверка на выход за рабочий день
    if end_min > 19*60:
        return False
    
    # Проверка пересечений с другими записями
    busy_intervals = get_busy_intervals(date_str)
    for busy_start, busy_end in busy_intervals:
        if not (end_min <= busy_start or start_min >= busy_end):
            return False
    
    return True

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ =====
def add_slots_for_day(date_str):
    """Добавляет все 15-минутные слоты на день"""
    all_slots = get_time_slots()
    
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM slots WHERE date = ?", (date_str,))
    for t in all_slots:
        c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, t))
    conn.commit()
    conn.close()
    return len(all_slots)

def get_all_dates():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT date FROM slots ORDER BY date")
    return [d[0] for d in c.fetchall()]

def get_slots_by_date(date_str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT time FROM slots WHERE date = ? ORDER BY time", (date_str,))
    return [s[0] for s in c.fetchall()]

def get_free_slots(date_str, duration):
    """Возвращает свободные слоты для услуги заданной длительности"""
    return find_available_slots(date_str, duration)

def create_booking(data):
    """Создает запись с несколькими услугами и временем начала/конца"""
    services = data['services']  # список услуг
    total_duration = sum(SERVICES_DICT[s]["duration"] for s in services)
    start_min = time_to_minutes(data['start_time'])
    end_min = start_min + total_duration
    end_time = minutes_to_time(end_min)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO bookings 
                 (user_id, username, user_name, user_phone, services, total_price, total_duration, date, start_time, end_time)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (data['user_id'], data.get('username', ''), data['name'], data['phone'],
               ', '.join(services), data['total_price'], total_duration,
               data['date'], data['start_time'], end_time))
    booking_id = c.lastrowid
    conn.commit()
    conn.close()
    return booking_id

def get_user_bookings(user_id):
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT id, date, start_time, end_time, services, total_price 
                 FROM bookings WHERE user_id = ? AND date >= ? ORDER BY date, start_time''', 
              (user_id, today))
    return c.fetchall()

def cancel_booking(booking_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT date, start_time, end_time, user_id, username, user_name FROM bookings WHERE id = ?", (booking_id,))
    result = c.fetchone()
    if result:
        date, start_time, end_time, user_id, username, user_name = result
        c.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
        conn.close()
        return date, start_time, end_time, user_id, username, user_name
    conn.close()
    return None, None, None, None, None, None

def get_today_bookings():
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT start_time, end_time, user_name, user_phone, username, services, total_price 
                 FROM bookings WHERE date = ? ORDER BY start_time''', (today,))
    return c.fetchall()

def get_all_future_bookings():
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT date, start_time, end_time, user_name, user_phone, username, services, total_price 
                 FROM bookings WHERE date >= ? ORDER BY date, start_time''', (today,))
    return c.fetchall()

def get_busy_slots(date_str):
    """Возвращает занятые интервалы для отображения в админке"""
    busy_intervals = get_busy_intervals(date_str)
    busy_times = []
    for start_min, end_min in busy_intervals:
        busy_times.append((minutes_to_time(start_min), minutes_to_time(end_min)))
    return busy_times

def get_booking_info(date_str, time_str):
    """Ищет запись по времени начала"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT user_name, user_phone, username, services, total_price 
                 FROM bookings WHERE date = ? AND start_time = ?''', (date_str, time_str))
    return c.fetchone()

# ===== FLASK ПРИЛОЖЕНИЕ =====
app = Flask(__name__)

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
        slots = get_slots_by_date(date_str)
        if slots:
            dates.append({
                'date': date_str,
                'display': date.strftime("%d.%m.%Y")
            })
    return jsonify(dates)

@app.route('/api/slots/<date>')
def get_slots(date):
    """Возвращает все свободные слоты с учетом длительности (для фронтенда)"""
    # Для простоты вернем все слоты, а фронтенд будет проверять доступность
    all_slots = get_slots_by_date(date)
    return jsonify(all_slots)

@app.route('/api/check-availability', methods=['POST'])
def check_availability():
    """Проверяет доступность комбинации услуг в указанное время"""
    data = request.json
    date = data['date']
    start_time = data['start_time']
    services = data['services']
    
    is_possible = is_combination_possible(date, services, start_time)
    return jsonify({'available': is_possible})

@app.route('/api/book', methods=['POST'])
def book():
    data = request.json
    booking_id = create_booking(data)
    
    username = data.get('username', '')
    user_link = f"@{username}" if username else f"ID: {data['user_id']}"
    services_list = '\n'.join([f"  • {s}" for s in data['services']])
    total_duration = sum(SERVICES_DICT[s]["duration"] for s in data['services'])
    
    try:
        admin_text = f"""
🔔 НОВАЯ ЗАПИСЬ!
👤 Имя: {data['name']}
📞 Телефон: {data['phone']}
📱 Username: {user_link}
💅 Услуги:
{services_list}
💰 Сумма: {data['total_price']}₽
⏱️ Длительность: {total_duration} мин
📅 Дата: {data['date']}
⏰ Время: {data['start_time']} - {minutes_to_time(time_to_minutes(data['start_time']) + total_duration)}
        """
        bot.send_message(ADMIN_ID, admin_text)
    except:
        pass
    
    try:
        client_text = f"""
✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!

📅 Дата: {data['date']}
⏰ Время: {data['start_time']} - {minutes_to_time(time_to_minutes(data['start_time']) + total_duration)}
💅 Услуги:
{services_list}
💰 Итого: {data['total_price']}₽

👤 Мастер: {MASTER_NAME}
📍 Адрес: {MASTER_ADDRESS}
📞 Телефон: {MASTER_PHONE}

Чтобы отменить запись, нажмите /start и выберите "Мои записи"
        """
        bot.send_message(data['user_id'], client_text)
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

# ----- КЛАВИАТУРЫ -----
def show_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('📅 Управление слотами', '📋 Записи на сегодня')
    markup.row('📊 Все записи', '📈 Статистика')
    markup.row('➕ Добавить слоты на день', '❌ Удалить все слоты')
    markup.row('📱 Открыть Mini App', '🔄 Перезагрузить')
    return markup

def show_client_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📅 Записаться", web_app=types.WebAppInfo(url=MINI_APP_URL)),
        types.InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings"),
        types.InlineKeyboardButton("📍 Контакты", callback_data="contacts")
    )
    bot.send_message(
        user_id,
        f"👋 Добро пожаловать!\n\n"
        f"✨ Мастер: {MASTER_NAME}\n"
        f"📍 {MASTER_ADDRESS}\n"
        f"📞 {MASTER_PHONE}\n\n"
        f"Выберите действие:",
        reply_markup=markup
    )

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
        show_client_menu(user_id)

# ===== УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ВСЕХ КНОПОК =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    try:
        # ----- КЛИЕНТСКИЕ КНОПКИ -----
        if data == "my_bookings":
            bookings = get_user_bookings(user_id)
            if not bookings:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "📅 Записаться", 
                    web_app=types.WebAppInfo(url=MINI_APP_URL)
                ))
                bot.edit_message_text(
                    "📭 У вас нет активных записей",
                    user_id, message_id,
                    reply_markup=markup
                )
            else:
                markup = types.InlineKeyboardMarkup()
                for b in bookings:
                    b_id, date, start, end, services, total = b
                    date_show = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
                    markup.add(types.InlineKeyboardButton(
                        f"❌ {date_show} {start}-{end} ({services[:20]}...) {total}₽", 
                        callback_data=f"cancel_{b_id}"
                    ))
                markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
                bot.edit_message_text(
                    "📋 Ваши записи (нажмите чтобы отменить):",
                    user_id, message_id,
                    reply_markup=markup
                )
            bot.answer_callback_query(call.id)

        elif data == "contacts":
            text = f"📍 {MASTER_ADDRESS}\n📞 {MASTER_PHONE}\n⏰ Пн-Сб 10:00-20:00"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
            bot.edit_message_text(text, user_id, message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)

        elif data == "back_to_menu":
            bot.delete_message(user_id, message_id)
            show_client_menu(user_id)
            bot.answer_callback_query(call.id)

        elif data.startswith("cancel_"):
            booking_id = int(data.replace("cancel_", ""))
            result = cancel_booking(booking_id)
            if result[0]:
                bot.send_message(
                    ADMIN_ID,
                    f"❌ Клиент {result[5]} отменил запись на {result[0]} {result[1]}-{result[2]}"
                )
            bot.answer_callback_query(call.id, "✅ Запись отменена")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "📅 Записаться", 
                web_app=types.WebAppInfo(url=MINI_APP_URL)
            ))
            bot.edit_message_text(
                "✅ Запись успешно отменена!",
                user_id, message_id,
                reply_markup=markup
            )

        # ----- АДМИНСКИЕ КНОПКИ -----
        elif data == "back_to_dates":
            dates = get_all_dates()
            markup = types.InlineKeyboardMarkup(row_width=2)
            for date_str in dates:
                date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
                slots = get_slots_by_date(date_str)
                markup.add(types.InlineKeyboardButton(
                    f"{date_show} ({len(slots)} сл.)", 
                    callback_data=f"manage_{date_str}"
                ))
            bot.edit_message_text(
                "📅 Выберите дату для управления:",
                user_id, message_id,
                reply_markup=markup
            )
            bot.answer_callback_query(call.id)

        elif data.startswith("manage_"):
            date_str = data.replace("manage_", "")
            slots = get_slots_by_date(date_str)
            busy_intervals = get_busy_slots(date_str)
            date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            
            markup = types.InlineKeyboardMarkup(row_width=4)
            all_times = get_time_slots()
            
            for time in all_times:
                # Проверяем, входит ли этот слот в какой-то занятый интервал
                is_busy = False
                busy_for_time = None
                for start, end in busy_intervals:
                    if time >= start and time < end:
                        is_busy = True
                        busy_for_time = f"{start}-{end}"
                        break
                
                if is_busy:
                    markup.add(types.InlineKeyboardButton(
                        f"🔴 {time}", 
                        callback_data=f"info_{date_str}_{time}"
                    ))
                elif time in slots:
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
                f"📅 Управление слотами на {date_show}:\n\n"
                f"🟢 - свободен (нажмите чтобы удалить)\n"
                f"⚪ - нет слота (нажмите чтобы добавить)\n"
                f"🔴 - занят (нажмите для информации)",
                user_id, message_id,
                reply_markup=markup
            )
            bot.answer_callback_query(call.id)

        elif data.startswith("add_"):
            parts = data.split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]
                
                conn = get_db()
                c = conn.cursor()
                try:
                    c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, time_str))
                    conn.commit()
                    bot.answer_callback_query(call.id, "✅ Слот добавлен")
                except sqlite3.IntegrityError:
                    bot.answer_callback_query(call.id, "❌ Слот уже существует")
                except Exception as e:
                    bot.answer_callback_query(call.id, f"❌ Ошибка")
                conn.close()
                
                # Обновляем меню управления
                new_data = f"manage_{date_str}"
                class NewCall:
                    def __init__(self, data, message, id):
                        self.data = data
                        self.message = message
                        self.id = id
                new_call = NewCall(new_data, call.message, call.id)
                callback_handler(new_call)

        elif data.startswith("delete_"):
            parts = data.split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]
                
                conn = get_db()
                c = conn.cursor()
                c.execute("DELETE FROM slots WHERE date = ? AND time = ?", (date_str, time_str))
                conn.commit()
                conn.close()
                bot.answer_callback_query(call.id, "❌ Слот удален")
                
                new_data = f"manage_{date_str}"
                class NewCall:
                    def __init__(self, data, message, id):
                        self.data = data
                        self.message = message
                        self.id = id
                new_call = NewCall(new_data, call.message, call.id)
                callback_handler(new_call)

        elif data.startswith("info_"):
            parts = data.split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]
                info = get_booking_info(date_str, time_str)
                if info:
                    user_link = f"@{info[2]}" if info[2] else "нет username"
                    msg = f"📋 ЗАПИСЬ:\n👤 {info[0]}\n📞 {info[1]}\n👤 {user_link}\n💅 {info[3]}\n💰 {info[4]}₽"
                else:
                    msg = "❌ Информация не найдена"
                bot.answer_callback_query(call.id, msg, show_alert=True)

        elif data == "delete_all":
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM slots")
            c.execute("DELETE FROM bookings")
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ Все слоты и записи удалены")
            bot.delete_message(user_id, message_id)

        elif data == "cancel":
            bot.answer_callback_query(call.id, "❌ Отменено")
            bot.delete_message(user_id, message_id)

    except Exception as e:
        print(f"Ошибка в callback_handler: {e}")
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка")
        except:
            pass

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
                user_link = f"@{b[4]}" if b[4] else "нет username"
                msg += f"⏰ {b[0]}-{b[1]} - {b[2]}\n📞 {b[3]}\n👤 {user_link}\n💅 {b[5]}\n💰 {b[6]}₽\n➖➖➖\n"
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
                user_link = f"@{b[5]}" if b[5] else "нет username"
                msg += f"   ⏰ {b[1]}-{b[2]} - {b[3]}\n   📞 {b[4]}\n   👤 {user_link}\n   💅 {b[6]}\n   ➖➖➖\n"
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
            "Например: 2024-12-25\n\n"
            "Будут созданы 15-минутные слоты с 10:00 до 19:00"
        )
        bot.register_next_step_handler(msg, add_slots_step)

    elif text == '❌ Удалить все слоты':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Да, удалить все", callback_data="delete_all"))
        markup.add(types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel"))
        bot.send_message(user_id, "⚠️ Вы уверены? Это удалит ВСЕ слоты и ВСЕ записи!", reply_markup=markup)

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
        bot.send_message(user_id, f"✅ Добавлено {added} 15-минутных слотов на {date_str}")
    except ValueError:
        bot.send_message(user_id, "❌ Неверный формат даты")

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
    print("📋 Услуги загружены:")
    for s in SERVICES:
        print(f"   • {s['name']} - {s['price']}₽ ({s['duration']} мин)")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            if "409" in str(e):
                print("⚠️ Конфликт с другим экземпляром бота. Жду 5 секунд...")
                time.sleep(5)
            else:
                print(f"❌ Ошибка: {e}")
                time.sleep(10)