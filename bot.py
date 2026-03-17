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

# ⚠️ ТВОЙ URL
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

# ===== ПРАЙС-ЛИСТ =====
SERVICES = [
    {"name": "👁️ Окрашивание + коррекция бровей", "price": 1300, "duration": 60},
    {"name": "👁️ Окрашивание бровей", "price": 1100, "duration": 30},
    {"name": "👁️ Д/у + окрашивание + коррекция бровей", "price": 1700, "duration": 60},
    {"name": "👁️ Д/у + окрашивание/коррекция бровей", "price": 1500, "duration": 40},
    {"name": "👁️ Окрашивание ресниц", "price": 400, "duration": 20},
    {"name": "👁️ Коррекция бровей", "price": 700, "duration": 30},
    {"name": "👁️ Депиляция зоны над губой/нос", "price": 300, "duration": 5},
    {"name": "💄 Макияж дневной (без акцента)", "price": 1700, "duration": 40},
    {"name": "💄 Макияж дневной (с акцентом + декольте)", "price": 3000, "duration": 60},
    {"name": "💇‍♀️ Легкие локоны/голливудская волна/мальвинка", "price": 2000, "duration": 60},
    {"name": "✨ Полный образ (макияж + локоны)", "price": 4800, "duration": 120},
]

SERVICES_DICT = {s["name"]: s for s in SERVICES}

# ===== БАЗА ДАННЫХ (БЕЗ АВТОУДАЛЕНИЯ) =====
DB_NAME = 'database_new.db'

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
                  time TEXT)''')
    
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
                  morning_notification_sent INTEGER DEFAULT 0,
                  hour_notification_sent INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    print(f"✅ База данных инициализирована: {DB_NAME} (данные сохраняются)")

# Только создаем таблицы, ничего не удаляем
init_db()

# ===== ФУНКЦИИ ВРЕМЕНИ =====
def time_to_minutes(time_str):
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def minutes_to_time(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def get_hourly_slots():
    """Часовые слоты для отображения клиентам"""
    return [f"{hour:02d}:00" for hour in range(10, 19)]

def get_admin_time_slots():
    """15-минутные слоты для админки"""
    slots = []
    for hour in range(10, 19):
        for minute in [0, 15, 30, 45]:
            slots.append(f"{hour:02d}:{minute:02d}")
    return slots

def get_busy_intervals(date_str):
    """Возвращает занятые интервалы с учетом 5-минутного буфера"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT start_time, end_time FROM bookings WHERE date = ?", (date_str,))
    busy = []
    for row in c.fetchall():
        start_min = time_to_minutes(row[0])
        end_min = time_to_minutes(row[1])
        # Добавляем 5 минут буфера после записи
        busy.append((start_min, end_min + 5))
    conn.close()
    return busy

def get_next_available_time(date_str, desired_start):
    """
    Возвращает ближайшее доступное время, начиная с desired_start
    Учитывает все существующие записи и буфер 5 минут
    """
    start_min = time_to_minutes(desired_start)
    busy_intervals = get_busy_intervals(date_str)
    
    # Сортируем занятые интервалы по времени начала
    busy_intervals.sort()
    
    current_min = start_min
    
    for busy_start, busy_end in busy_intervals:
        # Если текущее время попадает в занятый интервал
        if current_min < busy_end and (current_min + 5) > busy_start:
            # Перескакиваем на конец занятого интервала
            current_min = busy_end
        # Если мы уже после всех занятых интервалов
        elif current_min < busy_start:
            break
    
    # Проверяем, не вышли ли за конец рабочего дня
    if current_min + 5 > 19*60:
        return None
    
    return minutes_to_time(current_min)

def get_available_hours(date_str):
    """
    Возвращает список доступных часов для отображения клиенту
    Каждый час проверяется и сдвигается, если нужно
    """
    hourly_slots = get_hourly_slots()
    available = []
    
    for hour_slot in hourly_slots:
        next_time = get_next_available_time(date_str, hour_slot)
        if next_time:
            # Показываем только если время не позже следующего часа
            next_min = time_to_minutes(next_time)
            hour_min = time_to_minutes(hour_slot)
            if next_min < hour_min + 60:  # Не позже чем через час
                available.append(next_time)
    
    # Убираем дубликаты и сортируем
    available = sorted(list(set(available)))
    return available

def is_combination_possible(date_str, services, start_time):
    """Проверяет возможность записи"""
    start_min = time_to_minutes(start_time)
    total_duration = sum(SERVICES_DICT[s]["duration"] for s in services)
    end_min = start_min + total_duration
    
    if end_min > 19*60:
        return False
    
    busy_intervals = get_busy_intervals(date_str)
    for busy_start, busy_end in busy_intervals:
        if not (end_min <= busy_start or start_min >= busy_end):
            return False
    return True

# ===== ОСНОВНЫЕ ФУНКЦИИ БД =====
def add_slots_for_day(date_str):
    """Добавляет 15-минутные слоты для админки"""
    all_slots = get_admin_time_slots()
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
    dates = [d[0] for d in c.fetchall()]
    conn.close()
    return dates

def get_slots_by_date(date_str):
    """Для админки - 15-минутные слоты"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT time FROM slots WHERE date = ? ORDER BY time", (date_str,))
    return [s[0] for s in c.fetchall()]

def create_booking(data):
    services = data['services']
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
    c.execute('''SELECT id, user_id, user_name, username, date, start_time, end_time, services, total_price,
                 morning_notification_sent, hour_notification_sent
                 FROM bookings WHERE date >= ? ORDER BY date, start_time''', (today,))
    return c.fetchall()

def get_busy_slots(date_str):
    """Для админки - занятые интервалы"""
    busy_intervals = get_busy_intervals(date_str)
    return [(minutes_to_time(start), minutes_to_time(end)) for start, end in busy_intervals]

def get_booking_info(date_str, time_str):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT user_name, user_phone, username, services, total_price 
                 FROM bookings WHERE date = ? AND start_time = ?''', (date_str, time_str))
    return c.fetchone()

def get_user_bookings(user_id):
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT id, date, start_time, end_time, services, total_price 
                 FROM bookings WHERE user_id = ? AND date >= ? ORDER BY date, start_time''', 
              (user_id, today))
    return c.fetchall()

def update_notification_status(booking_id, notification_type):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE bookings SET {notification_type} = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

# ===== СИСТЕМА УВЕДОМЛЕНИЙ =====
def send_morning_reminder(booking_id, user_id, user_name, date, start_time, services, total_price):
    date_show = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
    
    client_text = f"""
☀️ ДОБРОЕ УТРО!

{user_name}, сегодня в {start_time} у вас запись к мастеру {MASTER_NAME}.

💅 Услуги: {services}
💰 Сумма: {total_price}₽
📅 Дата: {date_show}
⏰ Время: {start_time}
📍 Адрес: {MASTER_ADDRESS}
📞 Телефон: {MASTER_PHONE}

До встречи! ✨
    """
    
    admin_text = f"""
📅 НАПОМИНАНИЕ МАСТЕРУ

Сегодня в {start_time} запись:
👤 Клиент: {user_name}
💅 Услуги: {services}
💰 Сумма: {total_price}₽
    """
    
    try:
        bot.send_message(user_id, client_text)
        bot.send_message(ADMIN_ID, admin_text)
        update_notification_status(booking_id, 'morning_notification_sent')
        print(f"✅ Утреннее напоминание отправлено для записи #{booking_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки утреннего напоминания: {e}")

def send_hour_reminder(booking_id, user_id, user_name, date, start_time, services, total_price):
    date_show = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
    
    client_text = f"""
⏰ НАПОМИНАНИЕ ЗА ЧАС!

{user_name}, через час в {start_time} у вас запись к мастеру {MASTER_NAME}.

💅 Услуги: {services}
💰 Сумма: {total_price}₽
📅 Дата: {date_show}
⏰ Время: {start_time}
📍 Адрес: {MASTER_ADDRESS}
📞 Телефон: {MASTER_PHONE}

Пожалуйста, не опаздывайте! 
    """
    
    admin_text = f"""
⏰ НАПОМИНАНИЕ МАСТЕРУ

Через час, в {start_time}, запись:
👤 Клиент: {user_name}
💅 Услуги: {services}
💰 Сумма: {total_price}₽
    """
    
    try:
        bot.send_message(user_id, client_text)
        bot.send_message(ADMIN_ID, admin_text)
        update_notification_status(booking_id, 'hour_notification_sent')
        print(f"✅ Напоминание за час отправлено для записи #{booking_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки напоминания за час: {e}")

def check_reminders():
    print("🕒 Система уведомлений запущена")
    
    while True:
        try:
            now = datetime.datetime.now()
            current_date = now.strftime("%Y-%m-%d")
            current_time_minutes = now.hour * 60 + now.minute
            
            bookings = get_all_future_bookings()
            
            for booking in bookings:
                (booking_id, user_id, user_name, username, date, 
                 start_time, end_time, services, total_price, 
                 morning_sent, hour_sent) = booking
                
                if date < current_date:
                    continue
                
                start_minutes = time_to_minutes(start_time)
                
                if date == current_date and not morning_sent:
                    if 475 <= current_time_minutes <= 485:  # 7:55 - 8:05
                        send_morning_reminder(booking_id, user_id, user_name, date, 
                                            start_time, services, total_price)
                
                if date == current_date and not hour_sent:
                    hour_before = start_minutes - 60
                    if hour_before - 5 <= current_time_minutes <= hour_before + 5:
                        send_hour_reminder(booking_id, user_id, user_name, date,
                                         start_time, services, total_price)
            
            time.sleep(60)
        except Exception as e:
            print(f"❌ Ошибка в уведомлениях: {e}")
            time.sleep(60)

reminder_thread = threading.Thread(target=check_reminders, daemon=True)
reminder_thread.start()
print("✅ Система уведомлений активирована")

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
    
    all_dates = get_all_dates()
    
    for date_str in all_dates:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_obj >= today:
            # Проверяем, есть ли хоть одно доступное время
            available = get_available_hours(date_str)
            if available:
                dates.append({
                    'date': date_str,
                    'display': date_obj.strftime("%d.%m.%Y")
                })
    
    dates.sort(key=lambda x: x['date'])
    return jsonify(dates)

@app.route('/api/available-times/<date>')
def get_available_times(date):
    """Возвращает доступное время для клиента"""
    available = get_available_hours(date)
    return jsonify(available)

@app.route('/api/check-time', methods=['POST'])
def check_time():
    """Проверяет, доступно ли выбранное время для выбранных услуг"""
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
    end_time = minutes_to_time(time_to_minutes(data['start_time']) + total_duration)
    
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
⏰ Время: {data['start_time']} - {end_time}
        """
        bot.send_message(ADMIN_ID, admin_text)
    except:
        pass
    
    try:
        client_text = f"""
✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!

📅 Дата: {data['date']}
⏰ Время: {data['start_time']} - {end_time}
💅 Услуги:
{services_list}
💰 Итого: {data['total_price']}₽

👤 Мастер: {MASTER_NAME}
📍 Адрес: {MASTER_ADDRESS}
📞 Телефон: {MASTER_PHONE}

⏰ В 8:00 утра в день записи вы получите напоминание
⏰ За час до записи придет еще одно напоминание

Чтобы отменить запись, нажмите /start и выберите "Мои записи"
        """
        bot.send_message(data['user_id'], client_text)
    except:
        pass
    
    return jsonify({'success': True, 'id': booking_id})

@app.route('/health')
def health():
    return "OK", 200

# ===== ЗАПУСК FLASK =====
def run_flask():
    port = int(os.environ.get('PORT', 8000))
    print(f"🚀 Flask сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()
print("✅ Flask сервер запущен в фоне")

# ===== БОТ =====
bot = telebot.TeleBot(TOKEN)

# ----- МЕНЮ -----
def show_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('📅 Управление слотами', '📋 Записи на сегодня')
    markup.row('📊 Все записи', '📈 Статистика')
    markup.row('➕ Добавить слоты на день', '❌ Удалить все слоты')
    markup.row('🗑️ ПОЛНАЯ ОЧИСТКА БД', '📱 Открыть Mini App', '🔄 Перезагрузить')
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
        f"👋 Добро пожаловать!\n\n✨ Мастер: {MASTER_NAME}\n📍 {MASTER_ADDRESS}\n📞 {MASTER_PHONE}\n\nВыберите действие:",
        reply_markup=markup
    )

# ----- СТАРТ -----
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        bot.send_message(user_id, f"👋 Здравствуйте, {MASTER_NAME}!\n\n📍 {MASTER_ADDRESS}\n📞 {MASTER_PHONE}\n\nВы в админ-панели:", reply_markup=show_admin_menu())
    else:
        show_client_menu(user_id)

# ===== ОБРАБОТЧИК КНОПОК =====
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
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📅 Записаться", web_app=types.WebAppInfo(url=MINI_APP_URL)))
                bot.edit_message_text("📭 У вас нет активных записей", user_id, message_id, reply_markup=markup)
            else:
                markup = types.InlineKeyboardMarkup()
                for b in bookings:
                    b_id, date, start, end, services, total = b
                    date_show = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
                    markup.add(types.InlineKeyboardButton(f"❌ {date_show} {start}-{end} ({services[:20]}...) {total}₽", callback_data=f"cancel_{b_id}"))
                markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
                bot.edit_message_text("📋 Ваши записи (нажмите чтобы отменить):", user_id, message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)

        elif data == "contacts":
            text = f"📍 {MASTER_ADDRESS}\n📞 {MASTER_PHONE}\n⏰ Пн-Сб 10:00-20:00"
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
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
                bot.send_message(ADMIN_ID, f"❌ Клиент {result[5]} отменил запись на {result[0]} {result[1]}-{result[2]}")
            bot.answer_callback_query(call.id, "✅ Запись отменена")
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📅 Записаться", web_app=types.WebAppInfo(url=MINI_APP_URL)))
            bot.edit_message_text("✅ Запись успешно отменена!", user_id, message_id, reply_markup=markup)

        # ----- АДМИНСКИЕ КНОПКИ -----
        elif data == "admin_purge_database":
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM slots")
            c.execute("DELETE FROM bookings")
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ База данных полностью очищена!")
            bot.edit_message_text("✅ Все слоты и записи удалены.", user_id, message_id)

        elif data == "back_to_dates":
            dates = get_all_dates()
            markup = types.InlineKeyboardMarkup(row_width=2)
            for date_str in dates:
                date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
                slots = get_slots_by_date(date_str)
                markup.add(types.InlineKeyboardButton(f"{date_show} ({len(slots)} сл.)", callback_data=f"manage_{date_str}"))
            bot.edit_message_text("📅 Выберите дату для управления:", user_id, message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)

        elif data.startswith("manage_"):
            date_str = data.replace("manage_", "")
            slots = get_slots_by_date(date_str)
            busy_intervals = get_busy_slots(date_str)
            date_show = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            
            markup = types.InlineKeyboardMarkup(row_width=4)
            for time in get_admin_time_slots():
                is_busy = any(time >= start and time < end for start, end in busy_intervals)
                if is_busy:
                    markup.add(types.InlineKeyboardButton(f"🔴 {time}", callback_data=f"info_{date_str}_{time}"))
                elif time in slots:
                    markup.add(types.InlineKeyboardButton(f"🟢 {time}", callback_data=f"delete_{date_str}_{time}"))
                else:
                    markup.add(types.InlineKeyboardButton(f"⚪ {time}", callback_data=f"add_{date_str}_{time}"))
            
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_dates"))
            bot.edit_message_text(f"📅 Управление слотами на {date_show}:", user_id, message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)

        elif data.startswith("add_"):
            parts = data.split("_")
            if len(parts) >= 3:
                date_str, time_str = parts[1], parts[2]
                conn = get_db()
                c = conn.cursor()
                try:
                    c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, time_str))
                    conn.commit()
                    bot.answer_callback_query(call.id, "✅ Слот добавлен")
                except:
                    bot.answer_callback_query(call.id, "❌ Ошибка")
                conn.close()
                new_call = type('Call', (), {'data': f"manage_{date_str}", 'message': call.message, 'id': call.id})
                callback_handler(new_call)

        elif data.startswith("delete_"):
            parts = data.split("_")
            if len(parts) >= 3:
                date_str, time_str = parts[1], parts[2]
                conn = get_db()
                c = conn.cursor()
                c.execute("DELETE FROM slots WHERE date = ? AND time = ?", (date_str, time_str))
                conn.commit()
                conn.close()
                bot.answer_callback_query(call.id, "❌ Слот удален")
                new_call = type('Call', (), {'data': f"manage_{date_str}", 'message': call.message, 'id': call.id})
                callback_handler(new_call)

        elif data.startswith("info_"):
            parts = data.split("_")
            if len(parts) >= 3:
                date_str, time_str = parts[1], parts[2]
                info = get_booking_info(date_str, time_str)
                if info:
                    user_link = f"@{info[2]}" if info[2] else "нет username"
                    bot.answer_callback_query(call.id, f"👤 {info[0]}\n📞 {info[1]}\n👤 {user_link}\n💅 {info[3]}\n💰 {info[4]}₽", show_alert=True)
                else:
                    bot.answer_callback_query(call.id, "❌ Информация не найдена", show_alert=True)

        elif data == "delete_all":
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM slots")
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ Все слоты удалены")
            bot.delete_message(user_id, message_id)

        elif data == "cancel":
            bot.answer_callback_query(call.id, "❌ Отменено")
            bot.delete_message(user_id, message_id)

    except Exception as e:
        print(f"Ошибка: {e}")

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
            markup.add(types.InlineKeyboardButton(f"{date_show} ({len(slots)} сл.)", callback_data=f"manage_{date_str}"))
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
                date = b[4]
                start = b[5]
                end = b[6]
                user_name = b[2]
                user_phone = "—"
                username = b[3]
                services = b[7]
                total = b[8]
                
                if current_date != date:
                    current_date = date
                    date_show = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
                    msg += f"\n📅 {date_show}:\n"
                user_link = f"@{username}" if username else "нет username"
                msg += f"   ⏰ {start}-{end} - {user_name}\n   👤 {user_link}\n   💅 {services}\n   ➖➖➖\n"
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
        bot.send_message(user_id, f"📊 СТАТИСТИКА\n\n📝 Всего записей: {total}\n📅 Сегодня: {today_count}")

    elif text == '➕ Добавить слоты на день':
        msg = bot.send_message(user_id, "Введите дату в формате ГГГГ-ММ-ДД\nНапример: 2024-12-25")
        bot.register_next_step_handler(msg, add_slots_step)

    elif text == '❌ Удалить все слоты':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Да, удалить все", callback_data="delete_all"))
        markup.add(types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel"))
        bot.send_message(user_id, "⚠️ Вы уверены? Это удалит ВСЕ слоты!", reply_markup=markup)

    elif text == '🗑️ ПОЛНАЯ ОЧИСТКА БД':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⚠️ ДА, УДАЛИТЬ ВСЁ", callback_data="admin_purge_database"))
        markup.add(types.InlineKeyboardButton("❌ НЕТ, ОТМЕНА", callback_data="cancel"))
        bot.send_message(user_id, "⚠️ ВНИМАНИЕ! Это полностью очистит ВСЕ слоты и ВСЕ записи. База станет пустой. Вы уверены?", reply_markup=markup)

    elif text == '📱 Открыть Mini App':
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📱 ОТКРЫТЬ MINI APP", web_app=types.WebAppInfo(url=MINI_APP_URL)))
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

# ===== ЗАПУСК =====
if __name__ == "__main__":
    print("="*60)
    print("🚀 БОТ ЗАПУЩЕН!")
    print("="*60)
    print(f"👤 Админ: @{ADMIN_USERNAME}")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"🌐 Mini App URL: {MINI_APP_URL}")
    print("="*60)
    print("📋 Услуги загружены:")
    for s in SERVICES:
        print(f"   • {s['name']} - {s['price']}₽ ({s['duration']} мин)")
    print("="*60)
    print("⏰ УМНОЕ РАСПИСАНИЕ:")
    print("   • Клиенты видят только целые часы")
    print("   • Система автоматически подбирает ближайшее доступное время")
    print("   • Учитывается буфер 5 минут между записями")
    print("="*60)
    print("💾 База данных СОХРАНЯЕТСЯ при перезапусках")
    print("🗑️ Для полной очистки используйте кнопку в админ-меню")
    print("="*60)
    
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            if "409" in str(e):
                print("⚠️ Конфликт с другим ботом. Жду 10 секунд...")
                time.sleep(10)
            else:
                print(f"❌ Ошибка: {e}")
                time.sleep(10)