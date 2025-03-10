import logging

from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.handlers.states import BrandCreationStates
from bot.handlers.main_menu import show_main_menu
from bot.services.brand_ask_ai import get_parsed_response

brand_router = Router()



async def generate_message_and_keyboard(answer: str, options: list[dict], prefix: str) -> tuple[str, InlineKeyboardMarkup]:
    """
    Формирует текст сообщения и инлайн-кнопки с динамическим префиксом callback_data.

    :param answer: Текст комментария (подводка)
    :param options: Список вариантов (этапы 1, 2, 3)
    :param prefix: Префикс для callback_data (например, "choose_stage1", "choose_stage2", "choose_stage3")
    :return: Кортеж (текст сообщения, клавиатура)
    """

    # Формируем текст сообщения с комментариями и вариантами
    detailed_message = f"\n{answer}\n\n<b>Варианты:</b>\n"
    for opt in options:
        detailed_message += f"• {opt['full']}\n"
    logging.info(f"Передаваемые данные в generate_message_and_keyboard: options={options}")

    # Создаем инлайн-кнопки с динамическим префиксом
    buttons = [
        [InlineKeyboardButton(text=opt['short'], callback_data=f"{prefix}:{i}")]
        for i, opt in enumerate(options)
    ]

    # Извлекаем номер этапа из префикса (например, "choose_stage1" -> 1)
    stage_number = prefix.split("stage")[-1]

    # Добавляем кнопки "Еще 3 варианта" и "Свой вариант"
    buttons.append([
        InlineKeyboardButton(text="🔄 Еще 3 варианта", callback_data="repeat_brand"),
        InlineKeyboardButton(text="✏️ Свой вариант", callback_data=f"custom_input:{stage_number}")
    ])

    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    return detailed_message, keyboard

@brand_router.callback_query(lambda c: c.data.startswith("custom_input:"))
async def handle_custom_input_request(query: types.CallbackQuery, state: FSMContext):
    stage_number = query.data.split(":")[1]  # Получаем номер этапа из callback_data
    await state.update_data(current_custom_stage=stage_number)  # Сохраняем этап в данные состояния
    await query.message.answer("✏️ Введите свой вариант:")
    await state.set_state(BrandCreationStates.waiting_for_custom_input)
    await query.answer()  # Подтверждаем обработку callback


@brand_router.message(BrandCreationStates.waiting_for_custom_input)
async def handle_custom_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    stage_number = data.get("current_custom_stage")

    if not stage_number:
        await message.answer("❌ Ошибка: этап не определен.")
        await state.clear()
        return

    # Сохраняем введенный текст в соответствующий этап
    custom_input = message.text.strip()
    stage_key = f"stage{stage_number}_choice"
    await state.update_data({stage_key: {"full": custom_input, "short": custom_input}})

    # Логируем ввод пользователя
    logging.info(f"Пользователь ввел свой вариант: {custom_input}")

    # Определяем следующий этап
    match stage_number:
        case "1":
            await stage2_audience(message, state)  # Передаем message, а не query
        case "2":
            await stage3_shape(message, state)  # Передаем message, а не query
        case "3":
            await show_final_profile(message, state)  # Переход к финальному профилю
        case _:
            await message.answer("❌ Ошибка перехода. Возврат в меню.")
            await show_main_menu(message)

# 📍 Этап 1: Какую проблему или потребность решает эта идея?
async def stage1_problem(event: types.Message | types.CallbackQuery, state: FSMContext):
    """
    Универсальная функция для Этапа 1, поддерживающая и Message, и CallbackQuery.
    """
    data = await state.get_data()
    username = data.get("username")
    context = data.get("context")  # Исходная идея пользователя

    if not username:
        await event.answer("❌ Ошибка: не передано имя проекта. Попробуйте снова.", reply_markup=back_to_menu_kb())
        await state.clear()
        return

    # Проверяем, есть ли контекст
    if not context:
        from bot.handlers.main_menu import back_to_menu_kb
        logging.warning("⚠️ Context отсутствует в FSM! Проверьте, передаётся ли он в начале.")
        await event.answer("❌ Ошибка: не удалось получить исходную концепцию. Начните заново.",
                           reply_markup=back_to_menu_kb())
        await state.clear()
        return

    # Определяем, какой метод использовать для отправки сообщений
    send_message = event.message.answer if isinstance(event, types.CallbackQuery) else event.answer

    # Отправляем сообщение пользователю перед генерацией
    await send_message("⏳ Переходим к определению проблемного поля проекта..")

    prompt = f"""
    Исходный контекст: {context}, выбрано название {username}.
    Проанализируй название и контекст с точки зрения смысловых ассоциаций и потенциального позиционирования.
    Каким 3 различным вариантам проблемы или потребностей может быть адресован такой проект?

    Ответ выведи строго по формату:
    Комментарий: [краткий комментарий к выбору {username} и подводящий вопрос. 1-2 предложения.]

    1. **[эмодзи]** [Проблема/Потребность 1]: [Описание]
    2. **[эмодзи]** [Проблема/Потребность 2]: [Описание]
    3. **[эмодзи]** [Проблема/Потребность 3]: [Описание]
    """

    parsed_response = get_parsed_response(prompt)

    if not parsed_response["options"]:
        await send_message("❌ Ошибка при генерации форматов. Попробуйте снова.")
        return

    await state.update_data(stage1_options=parsed_response["options"])

    # После получения parsed_response
    stage_text = "<b>Этап 1: суть.</b>\n"
    final_answer = stage_text + parsed_response["answer"]

    msg_text, kb = await generate_message_and_keyboard(
        answer=final_answer,
        options=parsed_response["options"],
        prefix="choose_stage1"
    )

    kb.inline_keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="start")])

    await send_message(msg_text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(BrandCreationStates.waiting_for_stage1)


@brand_router.callback_query(lambda c: c.data.startswith("choose_stage1:"))
async def process_stage1(query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stage1_options = data.get("stage1_options", [])
    index_str = query.data.split(":", 1)[1]

    try:
        index = int(index_str)
    except ValueError:
        await query.message.answer("❌ Ошибка: некорректный формат.")
        return

    if index < 0 or index >= len(stage1_options):
        await query.message.answer("❌ Ошибка: выбран некорректный формат.")
        return

    stage1_choice = stage1_options[index]
    await state.update_data(stage1_choice=stage1_choice)

    await query.answer()

    # Переход к следующему этапу
    from handlers.brand_gen import stage2_audience
    await stage2_audience(query, state)


# 📍 Этап 2: Определение аудитории проекта
async def stage2_audience(event: types.Message | types.CallbackQuery, state: FSMContext):
    # Определяем метод отправки сообщений
    if isinstance(event, types.CallbackQuery):
        send_message = event.message.answer
        query = event
    else:
        send_message = event.answer
        query = None

    data = await state.get_data()
    username = data.get("username")
    context = data.get("context")
    stage1_choice = data.get("stage1_choice")

    # Логируем данные для отладки
    logging.info(f"Данные для этапа 2: username={username}, context={context}, stage1_choice={stage1_choice}")

    # Отправляем сообщение пользователю перед генерацией
    await send_message("⏳ Переходим к определению целевой аудитории ...")

    # Формируем промпт с учётом введённого пользователем текста
    prompt = f"""
    Пользователь изначально указал: {context}.
    Пользователь выбрал название {username} и указал на проблему/потребность {stage1_choice}.
    Исходя из выявленной проблемы, с учетом контекста и выбранного названия предложи 3 варианта целевой аудитории, которая получит наибольшую выгоду от решения.

    Ответ выведи строго по формату:
    Комментарий: [краткий комментарий к выбору {stage1_choice} (отметь выбор в тексте) и краткий вопрос-подводка к вариантам. 1-2 предложения]
1. [эмодзи] [Название аудитории 1]: [Описание, почему именно эта аудитория заинтересована и какие выгоды она получит (1-2 предложения)]
2. [эмодзи] [Название аудитории 2]: [Описание, почему именно эта аудитория заинтересована и какие выгоды она получит (1-2 предложения)]
3. [эмодзи] [Название аудитории 3]: [Описание, почему именно эта аудитория заинтересована и какие выгоды она получит (1-2 предложения)]
    """

    parsed_response = get_parsed_response(prompt)

    if not parsed_response["options"]:
        await send_message("❌ Ошибка при генерации аудитории. Попробуйте снова.")
        return

    await state.update_data(stage2_options=parsed_response["options"])

    stage_text = "<b>Этап 2: для кого?</b>\n"
    final_answer = stage_text + parsed_response["answer"]

    msg_text, kb = await generate_message_and_keyboard(
        answer=final_answer,
        options=parsed_response["options"],
        prefix="choose_stage2"
    )

    kb.inline_keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="start")])

    await send_message(msg_text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(BrandCreationStates.waiting_for_stage2)

# 📍 Обработка выбора аудитории
@brand_router.callback_query(lambda c: c.data.startswith("choose_stage2:"))
async def process_stage2(query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор аудитории проекта пользователем.
    Сохраняет выбор в состоянии FSM и переходит к следующему этапу.
    """
    data = await state.get_data()
    stage2_options = data.get("stage2_options", [])
    index_str = query.data.split(":", 1)[1]

    try:
        index = int(index_str)
    except ValueError:
        await query.message.answer("❌ Ошибка: некорректная аудитория.")
        return

    if index < 0 or index >= len(stage2_options):
        await query.message.answer("❌ Ошибка: выбрана некорректная аудитория. Попробуйте снова.")
        return

    stage2_choice = stage2_options[index]
    await state.update_data(stage2_choice=stage2_choice)

    await query.answer()

    # Переход к следующему этапу (сути и ценности проекта)
    await stage3_shape(query, state)


# 📍 Этап 3: Каким образом можно конкретно реализовать эту идею, чтобы обеспечить её качественную ценность?
async def stage3_shape(event: types.Message | types.CallbackQuery, state: FSMContext):
    """
    Генерирует варианты этапа 3 на основе контекста, username, проблемы и аудитории.
    Отправляет пользователю сообщение с комментарием и инлайн-кнопками выбора.
    """
    # Определяем метод отправки сообщений
    if isinstance(event, types.CallbackQuery):
        send_message = event.message.answer
        query = event
    else:
        send_message = event.answer
        query = None

    data = await state.get_data()
    username = data.get("username")
    context = data.get("context")
    stage1_choice = data.get("stage1_choice")
    stage2_choice = data.get("stage2_choice")

    # Логируем данные для отладки
    logging.info(f"Данные для этапа 3: username={username}, context={context}, stage1_choice={stage1_choice}, stage2_choice={stage2_choice}")

    # Отправляем сообщение пользователю перед генерацией
    await send_message("⏳ Переходим к самому интересному - в каком формате это будет...")

    prompt = f"""
    Исходный контекст: {context}, выбрано имя "{username}".
    Проблема/потребность "{stage1_choice}" и целевая аудитория "{stage2_choice}" (результаты предыдущих этапов).
    С учетом всего этого, какой конкретно можно реализовать проект, чтобы эффективно решать указанную проблему и приносить качественную ценность для аудитории?

    Ответ выведи строго по формату:
    Комментарий: [краткий комментарий к выбору {stage2_choice} (отметь выбор в тексте) и краткий вопрос-подводка к вариантам. 1-2 предложения]
    1. [эмодзи] [Краткое определение]: [1-2 предложения, поясняющие формат]
    2. [эмодзи] [Краткое определение]: [1-2 предложения, поясняющие формат]
    3. [эмодзи] [Краткое определение]: [1-2 предложения, поясняющие формат]
    """

    parsed_response = get_parsed_response(prompt)

    if not parsed_response["options"]:
        await send_message("❌ Ошибка при генерации сути проекта. Попробуйте снова.")
        return

    await state.update_data(stage3_options=parsed_response["options"])

    # После получения parsed_response
    stage_text = "<b>Этап 3: формат</b>\n"
    final_answer = stage_text + parsed_response["answer"]

    msg_text, kb = await generate_message_and_keyboard(
        answer=final_answer,
        options=parsed_response["options"],
        prefix="choose_stage3"
    )

    kb.inline_keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="start")])
    await send_message(msg_text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(BrandCreationStates.waiting_for_stage3)
# 📍 Обработка выбора Этапа 3
@brand_router.callback_query(lambda c: c.data.startswith("choose_stage3:"))
async def process_stage3_choice(query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор третьего этапа (формата проекта) и выводит финальный экран.
    """
    data = await state.get_data()
    stage3_options = data.get("stage3_options", [])
    index_str = query.data.split(":", 1)[1]

    try:
        index = int(index_str)
    except ValueError:
        await query.message.answer("❌ Ошибка: некорректный формат выбора.")
        return

    if index < 0 or index >= len(stage3_options):
        await query.message.answer("❌ Ошибка: выбран некорректный вариант формата.")
        return

    # Сохраняем выбранный объект (словарь с 'short' и 'full')
    stage3_choice = stage3_options[index]
    await state.update_data(stage3_choice=stage3_choice)

    await query.answer()

    # Вызываем функцию, которая выводит финальный экран (без отдельного декоратора)
    await show_final_profile(query, state)


async def show_final_profile(event: types.Message | types.CallbackQuery, state: FSMContext):
    """
    Выводит сообщение с кнопкой "📜 Собрать проект", используя данные из состояния.
    """
    if isinstance(event, types.CallbackQuery):
        send_message = event.message.answer
        query = event
    else:
        send_message = event.answer
        query = None

    data = await state.get_data()
    username = data.get("username", "Неизвестный проект")

    msg_text = f"✅ Проект <b>{username}</b> успешно разработан!\nНажмите на кнопку ниже, чтобы всё собрать вместе."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 Собрать проект", callback_data="get_project")],
            [InlineKeyboardButton(text="🏠 Вернуться в меню", callback_data="start")]
        ]
    )

    await send_message(msg_text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(BrandCreationStates.project_ready)

@brand_router.callback_query(lambda c: c.data == "get_project")
async def send_project_profile(event: types.Message | types.CallbackQuery, state: FSMContext):
    """
    Отправляет пользователю полный профиль проекта после нажатия на "📜 Забрать проект".
    """
    # Определяем метод отправки сообщений
    if isinstance(event, types.CallbackQuery):
        send_message = event.message.answer
        query = event
    else:
        send_message = event.answer
        query = None

    data = await state.get_data()
    username = data.get("username")
    context = data.get("context")

    # Применяем ту же логику, что и для stage1_choice и stage2_choice
    stage1_choice = data.get("stage1_choice", {})
    stage2_choice = data.get("stage2_choice", {})
    stage3_choice = data.get("stage3_choice", {})

    if isinstance(stage1_choice, dict):
        stage1_choice = stage1_choice.get("short", "Не выбрано")
    if isinstance(stage2_choice, dict):
        stage2_choice = stage2_choice.get("short", "Не выбрано")
    if isinstance(stage3_choice, dict):
        stage3_choice = stage3_choice.get("short", "Не выбрано")

    # Отправляем сообщение пользователю перед генерацией
    await send_message("⏳ Собираю всё вместе...")


    # Генерируем тэглайн и примеры существующих проектов
    prompt = f"""
    Пользователь создал концепцию проекта:
    - Мысль: {context}
    - Название: {username}
    - Проблема: {stage1_choice}
    - Аудитория: {stage2_choice}
    - Формат: {stage3_choice}

    Сформулируй:
    2. **Краткое описание проекта** – 2-3 предложения, объясняющие суть проекта.
    3. **3 реально существующих проекта** в этой сфере, с кратким описанием каждого.

    Учитывай изначальную мысль пользователя.
    Сформулируй и выведи в формате:
    Тэглайн: [короткое, яркое описание сути проекта одно предложение]
    Описание: [краткое, чёткое описание проекта, в 1-2 предложения] 
    Примеры похожих проектов:
    1. **[Название проекта]** – [1 предложение о сути и цели проекта]
    2. **[Название проекта]** – [1 предложение о сути и цели проекта]
    3. **[Название проекта]** – [1 предложение о сути и цели проекта]
    """

    parsed_response = get_parsed_response(prompt)
    tagline = parsed_response.get("answer", "Не удалось сгенерировать тэглайн")
    description = parsed_response.get("description", "Не удалось сгенерировать описание")
    references = parsed_response.get("options", [])

    # Формируем текст сообщения
    profile_text = f"""
📝 <b>Профиль проекта</b>

<b>{username}</b>  
<strong>{tagline}</strong>

<b>Описание проекта:</b>
{description}

<b>Концепция проекта:</b>
🔹 <b>Проблема:</b> {stage1_choice}  
🔹 <b>Аудитория:</b> {stage2_choice}  
🔹 <b>Формат:</b> {stage3_choice}  

<b>Похожие проекты:</b>
"""

    if references:
        for ref in references:
            profile_text += f"🔹 {ref['full']}\n"
    else:
        profile_text += "❌ Нет найденных похожих проектов.\n"

    profile_text += f"\n<i>{context}</i>"

    # **Создаём инлайн-клавиатуру**
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Вернуться в меню", callback_data="start")],
        [InlineKeyboardButton(text="📢 Поделиться проектом", callback_data="forward_project")],
        [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="leave_feedback")]
    ])

    # Отправляем итоговый профиль
    await send_message(profile_text, parse_mode="HTML", reply_markup=keyboard)

    # Очищаем состояние FSM
    await state.clear()


# Обработчик всех кнопкок "повторить"
@brand_router.callback_query(lambda c: c.data == "repeat_brand")
async def repeat_generation(query: types.CallbackQuery, state: FSMContext):
    await query.answer()  # Подтверждаем callback

    current_state = await state.get_state()

    if current_state == BrandCreationStates.waiting_for_stage1:
        await stage1_problem(query, state)

    elif current_state == BrandCreationStates.waiting_for_stage2:
        await stage2_audience(query, state)

    elif current_state == BrandCreationStates.waiting_for_stage3:
        await stage3_shape(query, state)

    else:
        await query.message.answer("❌ Неизвестное состояние. Попробуйте снова или начните с начала.")


@brand_router.callback_query(lambda c: c.data == "repeat_brand")
async def cmd_start_from_callback(query: types.CallbackQuery, state: FSMContext):
    await query.answer()  # Подтверждаем callback
    await state.clear()  # Очищаем состояние FSM

    # Вызываем универсальную функцию отображения главного меню
    await show_main_menu(query.message)


from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

FEEDBACK_CHAT_ID = -4770810793  # ID закрытой группы

# Храним оценки пользователей
user_ratings = {}


@brand_router.callback_query(lambda c: c.data == "leave_feedback")
async def request_feedback(query: types.CallbackQuery, state: FSMContext):
    """
    Шаг 1: Запросить у пользователя оценку (1-5 звёзд).
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [  # Первая строка
            InlineKeyboardButton(text="⭐", callback_data="rate_1"),
            InlineKeyboardButton(text="⭐⭐", callback_data="rate_2"),
            InlineKeyboardButton(text="⭐⭐⭐", callback_data="rate_3"),
        ],
        [  # Вторая строка
            InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data="rate_4"),
            InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data="rate_5"),
        ]
    ])

    await query.message.answer("Оцените проект по шкале от 1 до 5 ⭐:", reply_markup=keyboard)
    await state.set_state(BrandCreationStates.waiting_for_rating)  # Устанавливаем состояние ожидания оценки


# Функция для отправки отзыва в закрытую группу
async def send_feedback_to_group(bot, rating: str, username: str, full_name: str, comment: str):
    feedback_text = (
        f"📩 <b>Новый отзыв!</b>\n\n"
        f"👤 <b>От:</b> @{username} ({full_name})\n"
        f"⭐ <b>Оценка:</b> {rating}/5\n\n"
        f"💬 <b>Отзыв:</b> {comment}"
    )
    # Отправляем отзыв в закрытую группу
    await bot.send_message(FEEDBACK_CHAT_ID, feedback_text, parse_mode="HTML")



@brand_router.callback_query(lambda c: c.data.startswith("rate_"), BrandCreationStates.waiting_for_rating)
async def receive_rating(query: types.CallbackQuery, state: FSMContext):
    """
    Шаг 2: Получает оценку пользователя и предлагает оставить комментарий.
    """
    rating = query.data.split("_")[1]  # Получаем число от 1 до 5

    # Сохраняем оценку в состояние FSM
    await state.update_data(user_rating=rating)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить без комментария", callback_data="skip_comment")]
    ])

    await query.message.answer(
        f"Спасибо за вашу оценку {rating}⭐!\nТеперь напишите ваш комментарий (по желанию) ⌨️",
        reply_markup=keyboard
    )
    await state.set_state(BrandCreationStates.waiting_for_feedback)  # Устанавливаем состояние ожидания комментария



# Обработчик для пропуска комментария
@brand_router.callback_query(lambda c: c.data == "skip_comment", BrandCreationStates.waiting_for_feedback)
async def skip_comment(query: types.CallbackQuery, state: FSMContext):
    """
    Шаг 3: Отправить отзыв без комментария и отправить в закрытую группу.
    """
    data = await state.get_data()
    rating = data.get("user_rating", "N/A")

    # Отправляем отзыв без комментария
    await send_feedback_to_group(
        bot=query.bot,
        rating=rating,
        username=query.from_user.username,
        full_name=query.from_user.full_name,
        comment="Нет комментария"
    )

    # Благодарим пользователя
    await query.answer("Спасибо за ваш отзыв! 🎉")

    # Очищаем состояние FSM
    await state.clear()

    # Переходим в главное меню
    await show_main_menu(query.message)



# Функция для обработки отзыва с комментарием
@brand_router.message(BrandCreationStates.waiting_for_feedback)
async def forward_feedback(message: types.Message, state: FSMContext):
    """
    Шаг 4: Получаем текст отзыва и отправляем его в закрытую группу.
    """
    data = await state.get_data()
    rating = data.get("user_rating", "N/A")

    # Если комментарий есть, используем его, иначе пишем "Нет комментария"
    comment = message.text if message.text else "Нет комментария"

    # Отправляем отзыв
    await send_feedback_to_group(
        bot=message.bot,
        rating=rating,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        comment=comment
    )

    # Благодарим пользователя
    await message.answer("Спасибо за ваш отзыв! 🎉")

    # Очищаем состояние FSM
    await state.clear()

    # Переходим в главное меню
    await show_main_menu(message)



# Функция для отправки отзыва в группу
async def send_feedback_to_group(bot, rating: str, username: str, full_name: str, comment: str):
    """
    Отправляет отзыв в закрытую группу.
    """
    feedback_text = (
        f"📩 <b>Новый отзыв!</b>\n\n"
        f"👤 <b>От:</b> @{username} ({full_name})\n"
        f"⭐ <b>Оценка:</b> {rating}/5\n\n"
        f"💬 <b>Отзыв:</b> {comment}"
    )

    # Отправляем отзыв в закрытую группу
    await bot.send_message(FEEDBACK_CHAT_ID, feedback_text, parse_mode="HTML")


# Функция для перехода в главное меню
async def show_main_menu(message: types.Message):
    """
    Переход в главное меню.
    """
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Главное меню"))

    await message.answer("Вы вернулись в главное меню.", reply_markup=keyboard)


GROUP_ID = -1002250762604  # ID твоей группы
THREAD_ID = 162  # Предполагаемый ID темы

@brand_router.callback_query(lambda c: c.data == "forward_project")
async def forward_project(query: types.CallbackQuery):
    """
    Пересылает последнее сообщение бота (профиль проекта) в указанную группу.
    """

    logging.info("🔄 Получен callback на пересылку проекта!")  # Логируем получение запроса

    try:
        # Пересылаем последнее сообщение от бота в группу
        forwarded_message = await query.message.forward(GROUP_ID, message_thread_id=THREAD_ID)

        # Отправляем пользователю уведомление
        await query.message.answer(
            f"✅ Проект успешно переслан в <a href='https://t.me/c/{str(GROUP_ID)[4:]}'><b>группу</b></a>!",
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        await query.message.answer(f"❌ Ошибка при пересылке: {e}")
