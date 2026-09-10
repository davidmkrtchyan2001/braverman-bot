# -*- coding: utf-8 -*-
"""
Telegram-бот: тест Бравермана на определение вероятного дефицита
нейромедиаторов (дофамин, ацетилхолин, ГАМК, серотонин) с
рекомендациями в конце.

Запуск:
    1) pip install -r requirements.txt
    2) задать переменную окружения BOT_TOKEN (или вписать в .env)
    3) python bot.py
"""

import asyncio
import logging
import os
import random
import sys

# На Windows консоль/редирект может быть в cp1251 и падать на эмодзи —
# принудительно переключаем stdout/stderr на UTF-8, чтобы процесс не
# вылетал с UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from dotenv import load_dotenv

load_dotenv()

from image_card import generate_result_image
from test_data import (
    CATEGORIES,
    CATEGORY_ICON,
    CATEGORY_INTRO,
    CATEGORY_SHORT,
    DISCLAIMER,
    MAX_SCORE_PER_CATEGORY,
    QUESTIONS,
    RECOMMENDATIONS,
    SCALE_LABELS,
    status_for,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME: str | None = None  # заполняется в main() через bot.get_me()

router = Router()


class TestState(StatesGroup):
    running = State()


def answer_keyboard(idx: int) -> InlineKeyboardMarkup:
    # idx "вшит" в callback_data, чтобы случайный тап по кнопке СТАРОГО
    # (уже отвеченного) вопроса не засчитывался как ответ на текущий.
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"ans:{value}:{idx}")]
        for label, value in SCALE_LABELS
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✨ Начать тест", callback_data="start_test")]]
    )


def build_order() -> list[int]:
    """Группирует вопросы по категориям (порядок категорий и вопросы
    внутри каждой — перемешаны), чтобы можно было показывать заставки
    блоков и прогресс по разделам."""
    by_category: dict[str, list[int]] = {}
    for i, (_, category) in enumerate(QUESTIONS):
        by_category.setdefault(category, []).append(i)

    cats = list(by_category.keys())
    random.shuffle(cats)

    order: list[int] = []
    for cat in cats:
        indices = by_category[cat][:]
        random.shuffle(indices)
        order.extend(indices)
    return order


def progress_bar(current: int, total: int, length: int = 12) -> str:
    filled = round(length * current / total)
    filled = max(0, min(length, filled))
    return "▰" * filled + "▱" * (length - filled)


async def ask_question(message: Message, state: FSMContext, bot: Bot | None = None):
    data = await state.get_data()
    order = data["order"]
    idx = data["idx"]

    if idx >= len(order):
        await finish_test(message, state, bot)
        return

    q_index = order[idx]
    question_text, category = QUESTIONS[q_index]
    total = len(order)

    # заставка нового блока, если категория сменилась
    prev_category = data.get("prev_category")
    if category != prev_category:
        icon = CATEGORY_ICON[category]
        name = CATEGORY_SHORT[category]
        intro = CATEGORY_INTRO[category]
        if bot:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(0.4)
        await message.answer(
            f"{icon} <b>Блок: {name}</b>\n<i>{intro}</i>\n"
            "━━━━━━━━━━━━━━━",
        )
        await state.update_data(prev_category=category)

    if bot:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await asyncio.sleep(0.3)

    bar = progress_bar(idx, total)
    await message.answer(
        f"{bar}  {idx + 1}/{total}\n\n"
        f"<b>{question_text}</b>\n\n"
        "<i>Как часто это про тебя? Выбери один из вариантов ниже 👇</i>",
        reply_markup=answer_keyboard(idx),
    )


async def finish_test(message: Message, state: FSMContext, bot: Bot | None = None):
    data = await state.get_data()
    scores = data["scores"]

    await state.clear()

    if bot:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await asyncio.sleep(0.6)

    percentages = {}
    for cat in CATEGORIES:
        score = scores.get(cat, 0)
        percentages[cat] = round(100 * score / MAX_SCORE_PER_CATEGORY)

    # ---- карточка результата ----
    card = [
        "🎉 <b>Тест завершён!</b>",
        "Вот твой профиль по четырём веществам:",
        "",
        "<i>Процент — это не «уровень вещества в организме», а то, "
        "насколько сильно у тебя выражены симптомы его нехватки по "
        "ответам. Чем МЕНЬШЕ процент — тем лучше.</i>",
        "",
    ]
    for cat in CATEGORIES:
        pct = percentages[cat]
        icon = CATEGORY_ICON[cat]
        name = CATEGORY_SHORT[cat]
        bar = progress_bar(pct, 100, length=10)
        status_icon, status_label = status_for(pct)
        card.append(f"{icon} <b>{name}</b>")
        card.append(f"{bar}  <b>{pct}%</b>")
        card.append(f"{status_icon} {status_label}")
        card.append("")

    await message.answer("\n".join(card).rstrip())

    # ---- шаринг-карточка (PNG для сторис) ----
    if bot:
        try:
            await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
            png_bytes = generate_result_image(percentages, BOT_USERNAME or "")
            await message.answer_photo(
                BufferedInputFile(png_bytes, filename="braverman_result.png"),
                caption=(
                    "📸 Сохрани и покажи в сторис — пусть друзья тоже "
                    f"пройдут тест: t.me/{BOT_USERNAME}"
                ),
            )
        except Exception:
            log.exception("Не удалось сгенерировать/отправить карточку-картинку")

    # ---- рекомендации ----
    ranked = sorted(percentages.items(), key=lambda x: x[1], reverse=True)
    top = [cat for cat, pct in ranked[:2] if pct >= 40]

    if bot:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await asyncio.sleep(0.6)

    if not top:
        await message.answer(
            "✅ <b>Выраженного дефицита не выявлено</b>\n"
            "Баланс выглядит неплохо! Продолжай заботиться о режиме сна, "
            "питании и физической активности 🙂"
            + DISCLAIMER
        )
    else:
        header = "🎯 <b>Больше всего тебе сейчас может не хватать:</b>"
        blocks = "\n\n".join(
            f"<blockquote>{RECOMMENDATIONS[cat]}</blockquote>" for cat in top
        )
        await message.answer(f"{header}\n\n{blocks}{DISCLAIMER}")

    await message.answer(
        "Спасибо, что прошёл(-ла) тест! 💛\nХочешь пройти ещё раз?",
        reply_markup=start_keyboard(),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await asyncio.sleep(0.5)
    await message.answer(
        "✨ <b>Тест Бравермана</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Привет! 👋 Рад(а) тебя видеть.\n\n"
        "В 1990-х американский врач <b>Эрик Браверман</b> заметил: "
        "за нашей энергией, настроением, памятью и спокойствием стоят "
        "четыре ключевых нейромедиатора — вещества, которые мозг "
        "вырабатывает сам. Когда одного из них не хватает, это "
        "проявляется в повседневных мелочах: усталость без причины, "
        "тревожность, рассеянность, апатия.\n\n"
        "Браверман разработал тест по симптомам, чтобы понять, "
        "<b>какого именно вещества тебе сейчас не хватает больше "
        "всего</b> — и что конкретно можно с этим сделать."
    )

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await asyncio.sleep(0.9)
    await message.answer(
        "Тест смотрит на четыре направления:\n\n"
        "⚡️ <b>Дофамин</b> — энергия и мотивация\n"
        "🧩 <b>Ацетилхолин</b> — память и фокус\n"
        "🌿 <b>ГАМК</b> — спокойствие\n"
        "☀️ <b>Серотонин</b> — настроение и сон\n\n"
        f"🕐 {len(QUESTIONS)} вопросов, ~5-7 минут. Отвечай честно и "
        "по первому впечатлению, не задумываясь надолго — так результат "
        "будет точнее.\n\n"
        "⚠️ <i>Это ознакомительный тест, а не медицинская диагностика. "
        "Перед приёмом БАДов и добавок консультируйтесь с врачом.</i>\n\n"
        "Желаю приятного прохождения — заодно немного узнаешь себя 🙂",
        reply_markup=start_keyboard(),
    )


@router.callback_query(F.data == "start_test")
async def start_test(callback: CallbackQuery, state: FSMContext, bot: Bot):
    order = build_order()

    await state.set_state(TestState.running)
    await state.update_data(order=order, idx=0, scores={}, prev_category=None)

    await callback.message.edit_reply_markup(reply_markup=None)
    await ask_question(callback.message, state, bot)
    await callback.answer("Поехали! 🚀")


@router.callback_query(TestState.running, F.data.startswith("ans:"))
async def handle_answer(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split(":")
    value = int(parts[1])
    btn_idx = int(parts[2]) if len(parts) > 2 else None

    data = await state.get_data()
    order = data["order"]
    idx = data["idx"]
    scores = data["scores"]

    # Кнопка относится не к текущему вопросу (например, тапнули по
    # старому сообщению выше в чате) — игнорируем, не засчитываем.
    if btn_idx is not None and btn_idx != idx:
        await callback.answer(
            "Это старый вопрос — ответь на текущий, он ниже 👇",
            show_alert=True,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    q_index = order[idx]
    _, category = QUESTIONS[q_index]
    scores[category] = scores.get(category, 0) + value

    await state.update_data(idx=idx + 1, scores=scores)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await ask_question(callback.message, state, bot)


@router.callback_query(F.data.startswith("ans:"))
async def handle_stale_answer(callback: CallbackQuery):
    """Срабатывает, если бот перезапускался и потерял прогресс теста
    (кнопки на экране пользователя остались, а состояния уже нет)."""
    await callback.answer("Сессия сброшена, начните заново", show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "Похоже, бот перезапускался и прогресс теста не сохранился. "
        "Пожалуйста, начните тест заново.",
        reply_markup=start_keyboard(),
    )


@router.message(TestState.running)
async def ignore_text_during_test(message: Message):
    # Пользователь написал текст вместо нажатия на кнопку — напоминаем.
    await message.answer("Пожалуйста, выбери один из вариантов кнопками выше 👆")


@router.message()
async def fallback_message(message: Message):
    # Любое сообщение вне теста (не команда /start) — не даём чату
    # выглядеть "мёртвым": подсказываем, что нажать.
    await message.answer(
        "Привет! 👋 Чтобы начать тест, нажми кнопку ниже или отправь /start.",
        reply_markup=start_keyboard(),
    )


@router.errors()
async def on_error(event: ErrorEvent):
    log.exception(
        "Необработанная ошибка при обработке апдейта", exc_info=event.exception
    )
    return True


async def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "Не найден BOT_TOKEN. Задайте переменную окружения BOT_TOKEN "
            "(см. .env.example) перед запуском."
        )

    # Диагностика: какой шрифт для картинки-результата реально нашёлся
    # на этом сервере (помогает понять, почему текст на PNG "квадратиками").
    from image_card import _BOLD_PATH, _REGULAR_PATH, _THIS_DIR

    log.info("image_card: рабочая директория = %s", _THIS_DIR)
    log.info("image_card: обычный шрифт = %s", _REGULAR_PATH)
    log.info("image_card: жирный шрифт = %s", _BOLD_PATH)
    try:
        log.info("image_card: содержимое директории = %s", os.listdir(_THIS_DIR))
        fonts_dir = os.path.join(_THIS_DIR, "fonts")
        if os.path.isdir(fonts_dir):
            log.info("image_card: содержимое fonts/ = %s", os.listdir(fonts_dir))
        else:
            log.info("image_card: папки fonts/ не существует")
    except Exception:
        log.exception("image_card: не удалось прочитать директорию")

    global BOT_USERNAME

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    me = await bot.get_me()
    BOT_USERNAME = me.username
    log.info("Бот запущен: @%s", BOT_USERNAME)

    # Меню команд (значок "/" рядом с полем ввода в Telegram) — иначе
    # новый пользователь видит пустой чат без единой подсказки.
    await bot.set_my_commands(
        [BotCommand(command="start", description="Начать тест Бравермана")]
    )

    # Для бесплатных хостингов типа Replit, которые "усыпляют" процесс
    # без открытого порта. Включается переменной окружения KEEP_ALIVE=1
    # (на Railway/VPS не нужно — там ничего не заснёт).
    if os.getenv("KEEP_ALIVE") == "1":
        from keep_alive import keep_alive

        keep_alive(int(os.getenv("PORT", "8080")))
        log.info("keep_alive сервер запущен")

    # На случай непредвиденных сетевых обрывов не даём процессу упасть
    # насовсем — перезапускаем polling с небольшой паузой.
    while True:
        try:
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Polling упал, перезапуск через 5 секунд")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
