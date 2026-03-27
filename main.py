import asyncio
import logging
import sqlite3
import pandas as pd
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# --- Настройки ---
TOKEN = "8794568508:AAHY_uhp2GcZmZaWULMIfv1naSUfZGEZ0tw"
ADMIN_ID = 8071127858
bot = Bot(token=TOKEN)
dp = Dispatcher()


# --- Работа с БД ---
def init_db():
    conn = sqlite3.connect("survey_results.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            phone TEXT,
            gender TEXT,
            age TEXT,
            city TEXT,
            focus TEXT,
            interest TEXT,
            barrier TEXT,
            child_age TEXT,
            child_goal TEXT,
            child_barrier TEXT,
            preferences TEXT,
            reg_date TEXT
        )
    ''')
    conn.commit()
    conn.close()


def update_user_db(user_id, column, value):
    conn = sqlite3.connect("survey_results.db")
    cursor = conn.cursor()
    # Проверяем, есть ли юзер, если нет - создаем
    cursor.execute("INSERT OR IGNORE INTO users (user_id, reg_date) VALUES (?, ?)",
                   (user_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
    cursor.execute(f"UPDATE users SET {column} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


class Survey(StatesGroup):
    gender = State()
    age = State()
    city = State()
    city_other = State()
    focus = State()
    # Ветка А
    adult_q1 = State() # Множественный выбор (интересы)
    adult_q2 = State() # Барьеры
    adult_q2_other = State()
    adult_q3 = State() # Формат контента
    # Ветка Б
    child_q1 = State() # Возраст ребенка
    child_q2 = State() # Актуальность
    child_q3 = State() # Барьеры ребенка
    child_q3_other = State()
    child_q4 = State()
    # Финал
    raffle_choice = State()
    awaiting_phone = State()


# --- КОМАНДА ВЫГРУЗКИ (Только для админа) ---
@dp.message(Command("export"))
async def export_data(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect("survey_results.db")
    df = pd.read_sql_query("SELECT * FROM users", conn)
    conn.close()

    file_path = "results_export.xlsx"
    df.to_excel(file_path, index=False)

    await message.answer_document(types.FSInputFile(file_path), caption="📊 Все ответы пользователей на текущий момент.")


@dp.message(Command("clear_db"))
async def clear_database(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect("survey_results.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users")  # Удаляет все строки из таблицы
    conn.commit()
    conn.close()

    await message.answer("🧹 Таблица успешно очищена! Все данные удалены.")


# --- ЛОГИКА ОПРОСА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Начать анкетирование!", callback_data="step_gender"))

    text = '''Здравствуйте! Я Ольга Водянова, создатель Семейной языковой онлайн-школы Lingva Family.

Спасибо, что вы с нами!
Нам важно создавать для вас полезный контент, поэтому давайте познакомимся поближе. 

Это честный разговор без рекламы и попытки что то продать.🙌

Пожалуйста, ответьте на несколько вопросов (2–3 минуты). В благодарность:
• Полезный гайд каждому участнику
• Вы автоматически участвуете в розыгрыше абонемента на занятия английским (итоги подведем 7 мая 2026 года)'''
    await message.answer(text, reply_markup=builder.as_markup())


@dp.callback_query(F.data == "step_gender")
async def ask_gender(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="👩 Женский", callback_data="g_жен"))
    builder.add(types.InlineKeyboardButton(text="👨 Мужской", callback_data="g_муж"))
    await callback.message.answer("Вопрос 1. Пол\n\nВаш пол:", reply_markup=builder.as_markup())
    await state.set_state(Survey.gender)


@dp.callback_query(Survey.gender)
async def ask_age(callback: types.CallbackQuery, state: FSMContext):
    update_user_db(callback.from_user.id, "gender", callback.data.replace("g_", ""))
    builder = InlineKeyboardBuilder()
    for a in ["📱18–24", "🧑25–34", "👨35–44", "👴45+"]:
        builder.row(types.InlineKeyboardButton(text=a, callback_data=f"age_{a}"))
    await callback.message.edit_text("Вопрос 2. Возраст\n\nВаш возраст?", reply_markup=builder.as_markup())
    await state.set_state(Survey.age)


@dp.callback_query(Survey.age)
async def ask_city(callback: types.CallbackQuery, state: FSMContext):
    update_user_db(callback.from_user.id, "age", callback.data.replace("age_", ""))
    builder = InlineKeyboardBuilder()

    # Изменили значение для 'other', чтобы оно не шло в city_other
    cities = {
        "🏙 Москва / МО": "Мск",
        "🌆 Санкт-Петербург / ЛО": "СПб",
        "🏢 Другой город-миллионник": "Миллионник",
        '🏡 Другой город России': 'РФ',
        "🌍 Другая страна": "Другая_страна"
    }

    for txt, val in cities.items():
        builder.row(types.InlineKeyboardButton(text=txt, callback_data=f"city_{val}"))

    await callback.message.edit_text("Вопрос 3. Местоположение\n\nГде вы живете?", reply_markup=builder.as_markup())
    await state.set_state(Survey.city)


@dp.callback_query(Survey.city)
async def process_city(callback: types.CallbackQuery, state: FSMContext):
    # Просто берем то, что в callback_data после "city_"
    city_val = callback.data.replace("city_", "")
    update_user_db(callback.from_user.id, "city", city_val)

    # Переходим к выбору фокуса (Для себя / Для ребенка)
    # Передаем сам callback, чтобы сработало редактирование сообщения
    await show_focus(callback, state)


async def show_focus(msg_obj, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👤 Для себя", callback_data="f_взрослый"))
    builder.row(types.InlineKeyboardButton(text="👶 Для ребенка", callback_data="f_ребенок"))

    text = """Вопрос 4. Кто в фокусе\n\nА теперь главное — для кого вам интересен английский?"""

    # ПРАВИЛЬНАЯ ЛОГИКА:
    if isinstance(msg_obj, types.CallbackQuery):
        # Если это кнопка, редактируем сообщение, к которому она прикреплена
        await msg_obj.message.edit_text(text, reply_markup=builder.as_markup())
    elif isinstance(msg_obj, types.Message):
        # Если это сообщение (текст), то редактировать его нельзя, шлем новое через answer
        await msg_obj.answer(text, reply_markup=builder.as_markup())

    await state.set_state(Survey.focus)


@dp.callback_query(Survey.focus, F.data == "f_взрослый")
async def adult_start(callback: types.CallbackQuery, state: FSMContext):
    update_user_db(callback.from_user.id, "focus", "взрослый")

    builder = InlineKeyboardBuilder()
    options = [
        ("✈️ Английский для путешествий", "int_travel"),
        ("💼 Английский для работы", "int_work"),
        ("🌍 Английский для переезда", "int_relocation"),
        ("🎓 Подготовка к экзаменам", "int_exams"),
        ("🗣 Разговорная практика", "int_speech"),
        ("📚 Грамматика и структура языка", "int_grammar"),
        ("🎥 Английский через фильмы", "int_movies"),
        ("👶 Как помочь ребенку с английским", "int_child_help"),
    ]
    for text, val in options:
        builder.row(types.InlineKeyboardButton(text=text, callback_data=val))

    # УБРАЛИ кнопку "ГОТОВО"
    await callback.message.edit_text("Что вам ближе всего в английском?", reply_markup=builder.as_markup())
    await state.set_state(Survey.adult_q1)


# Теперь это нажатие СРАЗУ ведет к вопросу А2
@dp.callback_query(Survey.adult_q1, F.data.startswith("int_"))
async def collect_interests(callback: types.CallbackQuery, state: FSMContext):
    interest_val = callback.data.replace("int_", "")
    update_user_db(callback.from_user.id, "interest", interest_val)  # Сохраняем только один

    # Сразу вызываем функцию следующего вопроса (А2)
    await adult_q2_start(callback, state)



@dp.callback_query(Survey.adult_q1, F.data == "finish_interests")
async def adult_q2_start(callback: types.CallbackQuery, state: FSMContext):
    # Здесь переходим к вопросу А2 "Что вас останавливает"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⏳ Не хватает времени", callback_data="stop_time"))
    builder.row(types.InlineKeyboardButton(text="💰 Сложно вписать в бюджет", callback_data="stop_money"))
    builder.row(types.InlineKeyboardButton(text="😰 Страшно начать", callback_data="stop_start"))
    builder.row(types.InlineKeyboardButton(text="😴 Не хватает мотивации", callback_data="stop_motivation"))
    builder.row(types.InlineKeyboardButton(text="❓ Не понимаю, какой формат мне подойдет", callback_data="stop_format"))
    builder.row(types.InlineKeyboardButton(text="🧐 Другое", callback_data="stop_other"))

    await callback.message.edit_text("Что вас останавливает?", reply_markup=builder.as_markup())
    await state.set_state(Survey.adult_q2)


# Если пользователь выбрал "Другое" — просим написать текст
@dp.callback_query(Survey.adult_q2, F.data == "stop_other")
async def adult_q2_other_input(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Напишите, пожалуйста, что именно вам мешает заниматься?")
    await state.set_state(Survey.adult_q2_other)


# Если пользователь выбрал любой готовый вариант (Одиночный выбор)
@dp.callback_query(Survey.adult_q2, F.data.startswith("stop_"))
async def adult_q2_process(callback: types.CallbackQuery, state: FSMContext):
    # Если нажали "Другое", уходим в ввод текста и НЕ идем дальше
    if callback.data == "stop_other":
        await callback.message.edit_text("Напишите, пожалуйста, что именно вам мешает заниматься?")
        await state.set_state(Survey.adult_q2_other)
        return

    # Если выбрали обычный вариант
    barrier_val = callback.data.replace("stop_", "")
    update_user_db(callback.from_user.id, "barrier", barrier_val)  # Сохраняем в БД

    # СРАЗУ выдаем подарок и идем к розыгрышу
    await callback.message.answer("🎁 Спасибо за честность! Ваш гайд для взрослых: [ССЫЛКА]")
    await ask_raffle(callback.message, state)


# Обработка текстового ввода для "Другое"
@dp.message(Survey.adult_q2_other)
async def adult_q2_text_process(message: types.Message, state: FSMContext):
    update_user_db(message.from_user.id, "barrier", f"Другое: {message.text}")

    # Выдаем подарок и идем к розыгрышу
    await message.answer("🎁 Спасибо! Ваш гайд для взрослых: [ССЫЛКА]")
    await ask_raffle(message, state)

# --- ВЕТКА Б. ДЛЯ РОДИТЕЛЕЙ ---
@dp.callback_query(Survey.focus, F.data.in_(["f_ребенок", "f_взрослый_и_ребенок"]))
async def child_start(callback: types.CallbackQuery, state: FSMContext):
    focus_val = "ребенок" if callback.data == "f_ребенок" else "взрослый_и_ребенок"
    update_user_db(callback.from_user.id, "focus", focus_val)

    builder = InlineKeyboardBuilder()
    ages = [("🧸 4–6 лет", "4-6"), ("📖 7–9 лет", "7-9"), ("📱 10–12 лет", "10-12"), ("🎓 13–15 лет", "13-15"),
            ("🎯 16–17 лет", "16-17")]
    for text, val in ages:
        builder.row(types.InlineKeyboardButton(text=text, callback_data=f"c_age_{val}"))

    await callback.message.edit_text("Вопрос Б1. Сколько лет вашему ребенку?", reply_markup=builder.as_markup())
    await state.set_state(Survey.child_q1)


@dp.callback_query(Survey.child_q1)
async def child_q2_start(callback: types.CallbackQuery, state: FSMContext):
    update_user_db(callback.from_user.id, "child_age", callback.data.replace("c_age_", ""))

    builder = InlineKeyboardBuilder()
    goals = [
        ("📚 Школьная программа", "c_goal_school"),
        ("🎓 Экзамены (ЕГЭ/ОГЭ)", "c_goal_exams"),
        ("🗣 Чтобы свободно говорил", "c_goal_speak"),
        ("🎮 Интерес через игры", "c_goal_games"),
        ("🌍 Переезд/Учеба", "c_goal_relocation"),
        ("🧠 Просто присматриваюсь", "c_goal_looking")
    ]
    for text, val in goals:
        builder.row(types.InlineKeyboardButton(text=text, callback_data=val))

    await callback.message.edit_text("Что для вас сейчас самое актуальное?", reply_markup=builder.as_markup())
    await state.set_state(Survey.child_q2)


# Сразу переходим к финалу после одного нажатия
@dp.callback_query(Survey.child_q2, F.data.startswith("c_goal_"))
async def collect_child_goals(callback: types.CallbackQuery, state: FSMContext):
    goal_val = callback.data.replace("c_goal_", "")
    update_user_db(callback.from_user.id, "child_goal", goal_val)
    await state.set_state(Survey.child_q22)





@dp.callback_query(Survey.child_q22)
async def child_finish(callback: types.CallbackQuery, state: FSMContext):
    # Здесь переходим к вопросу А2 "Что вас останавливает"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⏳ Не хватает времени", callback_data="stop_time"))
    builder.row(types.InlineKeyboardButton(text="💰 Сложно вписать в бюджет", callback_data="stop_money"))
    builder.row(types.InlineKeyboardButton(text="😰 Боюсь, что ребёнок потеряет интерес", callback_data="stop_start"))
    builder.row(types.InlineKeyboardButton(text="😴 Ребёнок не хочет", callback_data="stop_motivation"))
    builder.row(types.InlineKeyboardButton(text="❓ Затруднения с выбором формата", callback_data="stop_format"))
    builder.row(types.InlineKeyboardButton(text="🧐 Другое", callback_data="stop_other"))

    await callback.message.edit_text("Что вас останавливает?", reply_markup=builder.as_markup())
    await state.set_state(Survey.child_q3)


# Если пользователь выбрал "Другое" — просим написать текст
@dp.callback_query(Survey.child_q3, F.data == "stop_other")
async def child_q3_other_input(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Напишите, пожалуйста, что именно вам мешает заниматься?")
    await state.set_state(Survey.child_q3_other)


# Если пользователь выбрал любой готовый вариант (Одиночный выбор)
@dp.callback_query(Survey.child_q3, F.data.startswith("stop_"))
async def child_q3_process(callback: types.CallbackQuery, state: FSMContext):
    # Если нажали "Другое", уходим в ввод текста и НЕ идем дальше
    if callback.data == "stop_other":
        await callback.message.edit_text("Напишите, пожалуйста, что именно вам мешает заниматься?")
        await state.set_state(Survey.child_q3_other)
        return

    # Если выбрали обычный вариант
    barrier_val = callback.data.replace("stop_", "")
    update_user_db(callback.from_user.id, "child_barrier", barrier_val)  # Сохраняем в БД

    # СРАЗУ выдаем подарок и идем к розыгрышу
    await callback.message.answer("🎁 Спасибо за честность! Ваш гайд для взрослых: [ССЫЛКА]")
    await ask_raffle(callback.message, state)


# Обработка текстового ввода для "Другое"
@dp.message(Survey.child_q3_other)
async def adult_q2_text_process(message: types.Message, state: FSMContext):
    update_user_db(message.from_user.id, "child_barrier", f"Другое: {message.text}")

    # Выдаем подарок и идем к розыгрышу
    await message.answer("🎁 Спасибо! Ваш гайд для взрослых: [ССЫЛКА]")
    await ask_raffle(message, state)


async def ask_raffle(message: types.Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎲 Участвую!", callback_data="raffle_yes"))
    builder.row(types.InlineKeyboardButton(text="🙏 Нет", callback_data="raffle_no"))
    await message.answer("Участвуете в розыгрыше?", reply_markup=builder.as_markup())
    await state.set_state(Survey.raffle_choice)

@dp.callback_query(Survey.raffle_choice, F.data == "raffle_no")
async def raffle_phone(callback: types.CallbackQuery, state: FSMContext):
    builder = ReplyKeyboardBuilder()
    await callback.message.answer("Оставим конкурс на потом? Будем рады видеть вас снова 😊")

@dp.callback_query(Survey.raffle_choice, F.data == "raffle_yes")
async def raffle_phone(callback: types.CallbackQuery, state: FSMContext):
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="📱 Отправить номер", request_contact=True))
    await callback.message.answer("Нажмите кнопку ниже, чтобы подтвердить участие:",
                                  reply_markup=builder.as_markup(resize_keyboard=True, one_time_keyboard=True))
    await state.set_state(Survey.awaiting_phone)


@dp.message(Survey.awaiting_phone, F.contact)
async def finish(message: types.Message, state: FSMContext):
    update_user_db(message.from_user.id, "phone", message.contact.phone_number)
    update_user_db(message.from_user.id, "username", f"@{message.from_user.username}")
    await message.answer("❤️ Спасибо! Вы в списке участников.", reply_markup=types.ReplyKeyboardRemove())
    await state.clear()


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())