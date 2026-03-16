from flask import Flask, render_template, request, jsonify
import sqlite3
import datetime
import threading
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# ===== НАСТРОЙКИ =====
BOT_TOKEN = '8632440554:AAG_fvQkmiOYQTJ4W6ML1jCVfdQKxyBD0kQ'
ADMIN_ID = 869161851
MASTER_NAME = "Анна"
MASTER_ADDRESS = "ул. Ленина, д. 1"
MASTER_PHONE = "+7 (999) 123-45-67"


# =====================

# ===== НАСТРОЙКА СЕССИИ С БОЛЬШИМИ ТАЙМАУТАМИ =====
def create_telegram_session():
    """Создает сессию с увеличенными таймаутами для Telegram"""
    session = requests.Session()

    # Настройка повторных попыток
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


telegram_session = create_telegram_session()

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


# ----- ФУНКЦИИ ДЛЯ РАБОТЫ С БД -----
def get_db():
    conn = sqlite3.connect('database.db', check_same_thread=False)
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

    # Добавляем тестовые слоты на 7 дней вперед, если их нет
    c.execute("SELECT COUNT(*) FROM slots")
    if c.fetchone()[0] == 0:
        today = datetime.datetime.now().date()
        times = ["10:00", "11:00", "12:00", "13:00", "14:00",
                 "15:00", "16:00", "17:00", "18:00", "19:00"]

        for i in range(7):
            date = today + datetime.timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            for t in times:
                c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, t))
        print("✅ Добавлены тестовые слоты на 7 дней")

    conn.commit()
    conn.close()
    print("✅ База данных Mini App готова")


init_db()


# ----- МАРШРУТЫ -----
@app.route('/')
def index():
    """Главная страница Mini App"""
    return render_template('index.html',
                           master_name=MASTER_NAME,
                           address=MASTER_ADDRESS,
                           phone=MASTER_PHONE)


@app.route('/api/services')
def get_services():
    """Возвращает список услуг"""
    return jsonify(SERVICES)


@app.route('/api/dates')
def get_dates():
    """Возвращает доступные даты"""
    conn = get_db()
    c = conn.cursor()

    dates = []
    today = datetime.datetime.now().date()

    for i in range(14):
        date = today + datetime.timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")

        # Проверяем свободные слоты
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
    return jsonify(dates)


@app.route('/api/slots/<date>')
def get_slots(date):
    """Возвращает свободные слоты на конкретную дату"""
    conn = get_db()
    c = conn.cursor()

    c.execute('''SELECT time FROM slots 
                 WHERE date = ? AND is_available = 1
                 AND time NOT IN (SELECT time FROM bookings WHERE date = ?)''',
              (date, date))
    slots = [s[0] for s in c.fetchall()]

    conn.close()
    return jsonify(slots)


def send_telegram_message(chat_id, text, max_retries=3):
    """Отправляет сообщение в Telegram с повторными попытками"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for attempt in range(max_retries):
        try:
            response = telegram_session.post(
                url,
                json={
                    'chat_id': chat_id,
                    'text': text
                },
                timeout=15  # Увеличенный таймаут
            )
            if response.status_code == 200:
                print(f"✅ Сообщение отправлено в чат {chat_id}")
                return True
            else:
                print(f"⚠️ Ошибка Telegram API: {response.status_code}")
        except requests.exceptions.Timeout:
            print(f"⏱️ Таймаут {attempt + 1}/{max_retries}, повтор через 2 сек...")
            time.sleep(2)
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")
            time.sleep(2)

    print(f"❌ Не удалось отправить сообщение в чат {chat_id} после {max_retries} попыток")
    return False


@app.route('/api/book', methods=['POST'])
def create_booking():
    """Создает новую запись"""
    data = request.json

    conn = get_db()
    c = conn.cursor()

    # Проверяем, свободен ли слот
    c.execute('''SELECT id FROM bookings 
                 WHERE date = ? AND time = ?''',
              (data['date'], data['time']))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Слот уже занят'})

    # Сохраняем запись
    c.execute('''INSERT INTO bookings 
                 (user_id, user_name, user_phone, services, total_price, date, time)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (data['user_id'], data['name'], data['phone'],
               data['services'], data['total_price'],
               data['date'], data['time']))

    booking_id = c.lastrowid
    conn.commit()
    conn.close()

    print(f"📝 Запись #{booking_id} сохранена в БД")

    # Отправляем уведомление админу (в фоне, чтобы не задерживать ответ)
    def send_notifications():
        admin_text = f"""
🔔 НОВАЯ ЗАПИСЬ (Mini App)!
👤 Имя: {data['name']}
📞 Телефон: {data['phone']}
💅 Услуги: {data['services']}
💰 Сумма: {data['total_price']}₽
📅 Дата: {data['date']}
⏰ Время: {data['time']}
        """
        send_telegram_message(ADMIN_ID, admin_text)

        # Отправляем подтверждение клиенту
        client_text = f"""
✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!

📅 Дата: {data['date']}
⏰ Время: {data['time']}
💅 Услуги: {data['services']}
💰 Итого: {data['total_price']}₽

👤 Мастер: {MASTER_NAME}
📍 Адрес: {MASTER_ADDRESS}
📞 Телефон: {MASTER_PHONE}

Если нужно отменить запись, напишите /start
        """
        send_telegram_message(data['user_id'], client_text)

    # Запускаем отправку в фоновом потоке
    threading.Thread(target=send_notifications).start()

    return jsonify({'success': True, 'id': booking_id})


if __name__ == '__main__':
    print("=" * 50)
    print("🚀 MINI APP СЕРВЕР ЗАПУЩЕН!")
    print("=" * 50)
    print(f"📍 Локальный адрес: http://localhost:5000")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print("=" * 50)
    print("📱 Открой в браузере для проверки интерфейса")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)