import telebot
from telebot import types
import sqlite3
import datetime
import time
import os
from flask import Flask, request
import threading

# Создаем Flask приложение для healthcheck
server = Flask(__name__)

@server.route('/health')
def health():
    return "OK", 200

# Запускаем Flask в отдельном потоке
def run_flask():
    port = int(os.environ.get('PORT', 8000))
    server.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ===== НАСТРОЙКИ =====
TOKEN = '8632440554:AAG_fvQkmiOYQTJ4W6ML1jCVfdQKxyBD0kQ'
ADMIN_ID = 869161851
ADMIN_USERNAME = "Nilov_Nikita_S_L"
MASTER_NAME = "Анна"
MASTER_ADDRESS = "ул. Ленина, д. 1"
MASTER_PHONE = "+7 (999) 123-45-67"

# URL твоего Mini App (замени на свой после деплоя)
MINI_APP_URL = "https://nails-mini-app.onrender.com"
# =====================

bot = telebot.TeleBot(TOKEN)


# ----- БАЗА ДАННЫХ -----
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

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")


init_db()


# ----- ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ -----
def add_slots_for_day(date_str):
    """Добавляет слоты на весь день"""
    times = ["10:00", "11:00", "12:00", "13:00", "14:00",
             "15:00", "16:00", "17:00", "18:00", "19:00"]

    conn = get_db()
    c = conn.cursor()

    # Удаляем старые слоты на эту дату
    c.execute("DELETE FROM slots WHERE date = ?", (date_str,))

    # Добавляем новые
    for t in times:
        c.execute("INSERT INTO slots (date, time) VALUES (?, ?)", (date_str, t))

    conn.commit()
    conn.close()
    return len(times)


def delete_slot(date_str, time_str):
    """Удаляет конкретный слот"""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM slots WHERE date = ? AND time = ?", (date_str, time_str))
    conn.commit()
    conn.close()


def get_slots_by_date(date_str):
    """Возвращает все слоты на дату"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT time FROM slots WHERE date = ? ORDER BY time", (date_str,))
    slots = [s[0] for s in c.fetchall()]
    conn.close()
    return slots


def get_busy_slots(date_str):
    """Возвращает занятые слоты на дату"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT time FROM bookings WHERE date = ?", (date_str,))
    busy = [b[0] for b in c.fetchall()]
    conn.close()
    return busy


def get_all_dates():
    """Возвращает все даты, на которые есть слоты"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT date FROM slots ORDER BY date")
    dates = [d[0] for d in c.fetchall()]
    conn.close()
    return dates


def get_today_bookings():
    """Возвращает записи на сегодня"""
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT time, user_name, user_phone, services, total_price 
                 FROM bookings WHERE date = ? ORDER BY time''', (today,))
    bookings = c.fetchall()
    conn.close()
    return bookings


def get_all_future_bookings():
    """Возвращает все будущие записи"""
    conn = get_db()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute('''SELECT date, time, user_name, user_phone, services, total_price 
                 FROM bookings WHERE date >= ? ORDER BY date, time''', (today,))
    bookings = c.fetchall()
    conn.close()
    return bookings


def get_booking_stats():
    """Возвращает статистику по записям"""
    conn = get_db()
    c = conn.cursor()

    # Общее количество
    c.execute("SELECT COUNT(*) FROM bookings")
    total = c.fetchone()[0]

    # На сегодня
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM bookings WHERE date = ?", (today,))
    today_count = c.fetchone()[0]

    # По услугам
    c.execute("SELECT services, COUNT(*) FROM bookings GROUP BY services")
    services_stats = c.fetchall()

    conn.close()
    return total, today_count, services_stats


# ----- АДМИН-МЕНЮ (ПОЛНАЯ ВЕРСИЯ) -----
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
        # Для клиентов - кнопка с Mini App
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


# ----- ОБРАБОТКА АДМИНСКИХ КОМАНД -----
@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID)
def admin_commands(message):
    user_id = message.from_user.id
    text = message.text

    # 📅 Управление слотами
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

    # 📋 Записи на сегодня
    elif text == '📋 Записи на сегодня':
        bookings = get_today_bookings()

        if bookings:
            msg = "📋 ЗАПИСИ НА СЕГОДНЯ:\n\n"
            for b in bookings:
                msg += f"⏰ {b[0]} - {b[1]}\n📞 {b[2]}\n💅 {b[3]}\n💰 {b[4]}₽\n➖➖➖\n"
        else:
            msg = "✅ На сегодня записей нет"

        bot.send_message(user_id, msg)

    # 📊 Все записи
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

    # 📈 Статистика
    elif text == '📈 Статистика':
        total, today_count, services_stats = get_booking_stats()

        msg = f"📊 СТАТИСТИКА\n\n"
        msg += f"📝 Всего записей: {total}\n"
        msg += f"📅 Сегодня: {today_count}\n\n"
        msg += f"🔥 По услугам:\n"

        if services_stats:
            for s, count in services_stats:
                msg += f"  • {s}: {count}\n"
        else:
            msg += "  • Нет данных"

        bot.send_message(user_id, msg)

    # ➕ Добавить слоты на день
    elif text == '➕ Добавить слоты на день':
        msg = bot.send_message(
            user_id,
            "Введите дату в формате ГГГГ-ММ-ДД\n"
            "Например: 2024-12-25\n\n"
            "Будут добавлены слоты:\n"
            "10:00, 11:00, 12:00, 13:00, 14:00, 15:00, 16:00, 17:00, 18:00, 19:00"
        )
        bot.register_next_step_handler(msg, add_slots_step)

    # ❌ Удалить все слоты
    elif text == '❌ Удалить все слоты':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Да, удалить все", callback_data="delete_all"))
        markup.add(types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel"))
        bot.send_message(user_id, "⚠️ Вы уверены, что хотите удалить ВСЕ слоты?", reply_markup=markup)

    # 📱 Открыть Mini App
    elif text == '📱 Открыть Mini App':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "📱 ОТКРЫТЬ MINI APP",
            web_app=types.WebAppInfo(url=MINI_APP_URL)
        ))
        bot.send_message(user_id, "Нажмите кнопку для открытия Mini App:", reply_markup=markup)

    # 🔄 Перезагрузить
    elif text == '🔄 Перезагрузить':
        bot.send_message(user_id, "🔄 Перезагрузка меню...", reply_markup=show_admin_menu())


# ----- ОБРАБОТКА INLINE КНОПОК -----
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id

    try:
        # Управление конкретной датой
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
                            callback_data=f"busy_{date_str}_{time}"
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
                f"📅 Управление слотами на {date_show}:\n\n"
                f"🟢 - свободен (нажмите чтобы удалить)\n"
                f"⚪ - нет слота (нажмите чтобы добавить)\n"
                f"🔴 - занят клиентом",
                user_id,
                call.message.message_id,
                reply_markup=markup
            )

        # Добавить слот
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

            # Обновляем отображение
            new_call = type('Call', (), {'data': f"manage_{date_str}", 'message': call.message, 'id': call.id})
            callback_handler(new_call)

        # Удалить слот
        elif call.data.startswith("delete_"):
            _, date_str, time_str = call.data.split("_", 2)

            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM slots WHERE date = ? AND time = ?", (date_str, time_str))
            conn.commit()
            conn.close()

            bot.answer_callback_query(call.id, "❌ Слот удален")

            # Обновляем отображение
            new_call = type('Call', (), {'data': f"manage_{date_str}", 'message': call.message, 'id': call.id})
            callback_handler(new_call)

        # Занятый слот (информация о клиенте)
        elif call.data.startswith("busy_"):
            _, date_str, time_str = call.data.split("_", 2)

            conn = get_db()
            c = conn.cursor()
            c.execute('''SELECT user_name, user_phone, services, total_price 
                         FROM bookings WHERE date = ? AND time = ?''', (date_str, time_str))
            booking = c.fetchone()
            conn.close()

            if booking:
                msg = f"📋 ИНФОРМАЦИЯ О ЗАПИСИ:\n\n"
                msg += f"👤 Имя: {booking[0]}\n"
                msg += f"📞 Телефон: {booking[1]}\n"
                msg += f"💅 Услуги: {booking[2]}\n"
                msg += f"💰 Сумма: {booking[3]}₽"
            else:
                msg = "❌ Информация не найдена"

            bot.answer_callback_query(call.id, msg, show_alert=True)

        # Назад к списку дат
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

            bot.edit_message_text(
                "📅 Выберите дату для управления:",
                user_id,
                call.message.message_id,
                reply_markup=markup
            )

        # Удалить все слоты
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


# ----- ОБРАБОТЧИК ДОБАВЛЕНИЯ СЛОТОВ -----
def add_slots_step(message):
    date_str = message.text.strip()
    user_id = message.from_user.id

    try:
        # Проверяем формат даты
        datetime.datetime.strptime(date_str, "%Y-%m-%d")

        added = add_slots_for_day(date_str)
        bot.send_message(
            user_id,
            f"✅ Добавлено {added} слотов на {date_str}",
            reply_markup=show_admin_menu()
        )
    except ValueError:
        bot.send_message(
            user_id,
            "❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД",
            reply_markup=show_admin_menu()
        )


# ----- ЗАПУСК БОТА -----
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН!")
    print("=" * 50)
    print(f"👤 Админ: @{ADMIN_USERNAME}")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"🌐 Mini App URL: {MINI_APP_URL}")
    print("=" * 50)

    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(5)
            print("🔄 Перезапуск...")