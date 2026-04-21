import json
import time
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.recurring_db import (
    get_recurring_messages, get_recurring_message,
    create_recurring_message, update_recurring_message,
    delete_recurring_message
)
from bot.handlers.admin import is_admin, safe_edit
from config import BOT_ADMINS

logger = logging.getLogger(__name__)
router = Router()


class RecurringState(StatesGroup):
    waiting_text = State()
    waiting_media = State()
    waiting_url_buttons = State()
    waiting_start_time = State()
    waiting_end_time = State()


def _moscow_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=3)))


def _calc_next_send(start_time_str: str, interval_hours: int, end_time_str: str = "23:00") -> float:
    now = _moscow_now()
    try:
        sh, sm = map(int, start_time_str.split(":"))
        eh, em = map(int, end_time_str.split(":"))
    except Exception:
        sh, sm = 9, 0
        eh, em = 23, 0

    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em
    now_minutes = now.hour * 60 + now.minute

    if interval_hours < 24:
        base = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        if base > now:
            base -= timedelta(days=1)
        # Двигаемся вперёд кратными интервалами
        while base <= now:
            base += timedelta(hours=interval_hours)

        # Если попали вне окна — переносим на следующий start_time
        candidate_minutes = base.hour * 60 + base.minute
        if candidate_minutes < start_minutes or candidate_minutes > end_minutes:
            # Переносим на следующий день в start_time
            base = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
            if base <= now:
                base += timedelta(days=1)

        return base.timestamp()

    # Интервал 24ч — просто следующий start_time
    candidate = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _format_next_send(next_send_at: float) -> str:
    if not next_send_at:
        return "не запланировано"
    dt = datetime.fromtimestamp(next_send_at, tz=timezone(timedelta(hours=3)))
    return dt.strftime("%d %b %Y г., %H:%M")


def _msg_preview(msg: dict) -> str:
    text = msg.get("text") or ""
    media_type = msg.get("media_type") or ""
    buttons_raw = msg.get("url_buttons") or "[]"
    try:
        buttons = json.loads(buttons_raw)
    except Exception:
        buttons = []

    has_text = "✅" if text else "❌"
    has_media = "✅" if media_type else "❌"
    has_buttons = "✅" if buttons else "❌"

    return (
        f"📝 Текст {has_text}\n"
        f"🖼 Медиа {has_media}\n"
        f"🔗 URL-кнопки {has_buttons}"
    )


def recurring_list_keyboard(chat_id: int, messages: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for msg in messages:
        status = "✅" if msg["enabled"] else "❌"
        interval = f"каждые {msg['interval_hours']}ч."
        label = f"🌟 {status} • Время: {msg['start_time']} • {interval}"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"rec_open:{msg['id']}")
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить сообщение", callback_data=f"rec_add:{chat_id}")
    ])
    buttons.append([
        InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def recurring_item_keyboard(msg: dict) -> InlineKeyboardMarkup:
    enabled = bool(msg["enabled"])
    delete_prev = bool(msg["delete_previous"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'🟢 Включено' if enabled else '🔴 Выключено'}",
            callback_data=f"rec_toggle:{msg['id']}"
        )],
        [InlineKeyboardButton(text="✍️ Настроить сообщение", callback_data=f"rec_content:{msg['id']}")],
        [
            InlineKeyboardButton(text="🕐 Начало", callback_data=f"rec_time:{msg['id']}"),
            InlineKeyboardButton(text="🕙 Конец", callback_data=f"rec_endtime:{msg['id']}"),
            InlineKeyboardButton(text="🔁 Повторение", callback_data=f"rec_interval:{msg['id']}"),
        ],
        [InlineKeyboardButton(
            text=f"🗑 Удалять последнее: {'✅' if delete_prev else '❌'}",
            callback_data=f"rec_delprev:{msg['id']}"
        )],
        [InlineKeyboardButton(text="🗑 Удалить это сообщение", callback_data=f"rec_delete:{msg['id']}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"rec_list:{msg['chat_id']}")],
    ])


def recurring_content_keyboard(msg: dict) -> InlineKeyboardMarkup:
    text = msg.get("text") or ""
    media = msg.get("media_file_id") or ""
    buttons_raw = msg.get("url_buttons") or "[]"
    try:
        buttons = json.loads(buttons_raw)
    except Exception:
        buttons = []

    has_text = "✅" if text else "❌"
    has_media = "✅" if media else "❌"
    has_buttons = "✅" if buttons else "❌"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"📝 Текст {has_text}", callback_data=f"rec_set_text:{msg['id']}"),
            InlineKeyboardButton(text="👁 Просмотр", callback_data=f"rec_preview_text:{msg['id']}"),
        ],
        [
            InlineKeyboardButton(text=f"🖼 Медиа {has_media}", callback_data=f"rec_set_media:{msg['id']}"),
            InlineKeyboardButton(text="👁 Просмотр", callback_data=f"rec_preview_media:{msg['id']}"),
        ],
        [
            InlineKeyboardButton(text=f"🔗 URL-кнопки {has_buttons}", callback_data=f"rec_set_buttons:{msg['id']}"),
            InlineKeyboardButton(text="👁 Просмотр", callback_data=f"rec_preview_buttons:{msg['id']}"),
        ],
        [InlineKeyboardButton(text="👁 Полный просмотр", callback_data=f"rec_full_preview:{msg['id']}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"rec_open:{msg['id']}")],
    ])


def interval_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    options = [1, 2, 3, 4, 6, 8, 12, 24]
    buttons = []
    row = []
    for h in options:
        row.append(InlineKeyboardButton(text=str(h), callback_data=f"rec_set_interval:{msg_id}:{h}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"rec_open:{msg_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("rec_list:"))
async def show_recurring_list(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        await call.answer("⛔ Нет прав!", show_alert=True)
        return
    messages = await get_recurring_messages(chat_id)
    text = (
        f"🔁 <b>Повторяющиеся сообщения</b>\n\n"
        f"В этом меню вы можете настроить сообщения, которые будут "
        f"отправляться в группу повторно каждые несколько часов.\n\n"
        f"Текущее время: <b>{_moscow_now().strftime('%d %b %Y г., %H:%M')}</b>"
    )
    await safe_edit(call, text, recurring_list_keyboard(chat_id, messages))


@router.callback_query(F.data.startswith("rec_open:"))
async def open_recurring_message(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        await call.answer("Сообщение не найдено", show_alert=True)
        return
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        await call.answer("⛔ Нет прав!", show_alert=True)
        return
    delete_prev = "✅" if msg["delete_previous"] else "❌"
    next_send = _format_next_send(msg["next_send_at"])
    text = (
        f"🔁 <b>Повторяющееся сообщение #{msg_id}</b>\n\n"
        f"💡 Статус: {'Включено ✅' if msg['enabled'] else 'Выключено ❌'}\n"
        f"🕐 Время работы: <b>{msg['start_time']} — {msg['end_time']}</b>\n"
        f"🔁 Повторение: каждые <b>{msg['interval_hours']} ч.</b>\n"
        f"🗑 Удалять последнее: <b>{delete_prev}</b>\n\n"
        f"🚀 Следующая отправка: <b>{next_send}</b>"
    )
    await safe_edit(call, text, recurring_item_keyboard(msg))


@router.callback_query(F.data.startswith("rec_add:"))
async def add_recurring_message(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        await call.answer("⛔ Нет прав!", show_alert=True)
        return
    msg_id = await create_recurring_message(chat_id)
    msg = await get_recurring_message(msg_id)
    await call.answer("✅ Сообщение создано")
    await safe_edit(
        call,
        f"🔁 <b>Новое повторяющееся сообщение #{msg_id}</b>\n\nНастройте содержимое и расписание.",
        recurring_item_keyboard(msg)
    )


@router.callback_query(F.data.startswith("rec_toggle:"))
async def toggle_recurring(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    new_enabled = 0 if msg["enabled"] else 1
    next_send = _calc_next_send(msg["start_time"], msg["interval_hours"], msg.get("end_time", "23:00")) if new_enabled else 0.0
    await update_recurring_message(msg_id, enabled=new_enabled, next_send_at=next_send)
    await call.answer("✅ Включено" if new_enabled else "❌ Выключено")
    msg = await get_recurring_message(msg_id)
    delete_prev = "✅" if msg["delete_previous"] else "❌"
    next_label = _format_next_send(msg["next_send_at"])
    text = (
        f"🔁 <b>Повторяющееся сообщение #{msg_id}</b>\n\n"
        f"💡 Статус: {'Включено ✅' if msg['enabled'] else 'Выключено ❌'}\n"
        f"🕐 Время работы: <b>{msg['start_time']} — {msg['end_time']}</b>\n"
        f"🔁 Повторение: каждые <b>{msg['interval_hours']} ч.</b>\n"
        f"🗑 Удалять последнее: <b>{delete_prev}</b>\n\n"
        f"🚀 Следующая отправка: <b>{next_label}</b>"
    )
    await safe_edit(call, text, recurring_item_keyboard(msg))


@router.callback_query(F.data.startswith("rec_delprev:"))
async def toggle_delete_previous(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    new_val = 0 if msg["delete_previous"] else 1
    await update_recurring_message(msg_id, delete_previous=new_val)
    await call.answer("Удалять последнее: " + ("✅" if new_val else "❌"))
    msg = await get_recurring_message(msg_id)
    delete_prev = "✅" if msg["delete_previous"] else "❌"
    next_label = _format_next_send(msg["next_send_at"])
    text = (
        f"🔁 <b>Повторяющееся сообщение #{msg_id}</b>\n\n"
        f"💡 Статус: {'Включено ✅' if msg['enabled'] else 'Выключено ❌'}\n"
        f"🕐 Время работы: <b>{msg['start_time']} — {msg['end_time']}</b>\n"
        f"🔁 Повторение: каждые <b>{msg['interval_hours']} ч.</b>\n"
        f"🗑 Удалять последнее: <b>{delete_prev}</b>\n\n"
        f"🚀 Следующая отправка: <b>{next_label}</b>"
    )
    await safe_edit(call, text, recurring_item_keyboard(msg))


@router.callback_query(F.data.startswith("rec_delete:"))
async def delete_recurring(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    chat_id = msg["chat_id"]
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await delete_recurring_message(msg_id)
    await call.answer("🗑 Удалено", show_alert=True)
    messages = await get_recurring_messages(chat_id)
    text = (
        f"🔁 <b>Повторяющиеся сообщения</b>\n\n"
        f"Текущее время: <b>{_moscow_now().strftime('%d %b %Y г., %H:%M')}</b>"
    )
    await safe_edit(call, text, recurring_list_keyboard(chat_id, messages))


@router.callback_query(F.data.startswith("rec_content:"))
async def show_content_menu(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer(
        f"✍️ <b>Настройка сообщения #{msg_id}</b>\n\n{_msg_preview(msg)}\n\n"
        f"Используйте кнопки ниже чтобы выбрать что хотите установить.",
        reply_markup=recurring_content_keyboard(msg)
    )


@router.callback_query(F.data.startswith("rec_set_text:"))
async def set_text_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await state.set_state(RecurringState.waiting_text)
    await state.update_data(msg_id=msg_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")
    ]])
    await safe_edit(call, "✏️ Отправьте текст сообщения (поддерживается HTML).\n\nОтправьте — для удаления текста.", kb)


@router.message(RecurringState.waiting_text)
async def set_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data["msg_id"]
    text = text = message.html_text or ""
    await update_recurring_message(msg_id, text=text)
    await state.clear()
    msg = await get_recurring_message(msg_id)
    await message.answer(
        f"✅ Текст {'удалён' if not text else 'сохранён'}.\n\n"
        f"✍️ <b>Настройка сообщения #{msg_id}</b>\n\n{_msg_preview(msg)}",
        reply_markup=recurring_content_keyboard(msg)
    )


@router.callback_query(F.data.startswith("rec_set_media:"))
async def set_media_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await state.set_state(RecurringState.waiting_media)
    await state.update_data(msg_id=msg_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Удалить медиа", callback_data=f"rec_clear_media:{msg_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")]
    ])
    await safe_edit(call, "🖼 Отправьте фото или видео.\nИли нажмите кнопку чтобы удалить текущее медиа.", kb)


@router.message(RecurringState.waiting_media, F.photo | F.video)
async def set_media_input(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data["msg_id"]
    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    else:
        file_id = message.video.file_id
        media_type = "video"
    await update_recurring_message(msg_id, media_file_id=file_id, media_type=media_type)
    await state.clear()
    msg = await get_recurring_message(msg_id)
    await message.answer(
        f"✅ Медиа сохранено.\n\n"
        f"✍️ <b>Настройка сообщения #{msg_id}</b>\n\n{_msg_preview(msg)}",
        reply_markup=recurring_content_keyboard(msg)
    )


@router.callback_query(F.data.startswith("rec_clear_media:"))
async def clear_media(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    await update_recurring_message(msg_id, media_file_id="", media_type="")
    await state.clear()
    await call.answer("✅ Медиа удалено")
    msg = await get_recurring_message(msg_id)
    await safe_edit(call, f"✍️ <b>Настройка сообщения #{msg_id}</b>\n\n{_msg_preview(msg)}", recurring_content_keyboard(msg))


@router.callback_query(F.data.startswith("rec_set_buttons:"))
async def set_buttons_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await state.set_state(RecurringState.waiting_url_buttons)
    await state.update_data(msg_id=msg_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Удалить все кнопки", callback_data=f"rec_clear_buttons:{msg_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")]
    ])
    await safe_edit(
        call,
        "🔗 <b>URL-кнопки</b>\n\n"
        "Отправьте кнопки в формате, каждая на новой строке:\n"
        "<code>Текст кнопки | https://ссылка.com</code>\n\n"
        "Пример:\n"
        "<code>Наш сайт | https://example.com\nПодписаться | https://t.me/channel</code>",
        kb
    )


@router.message(RecurringState.waiting_url_buttons)
async def set_buttons_input(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data["msg_id"]
    buttons = []
    errors = []
    for line in (message.text or "").strip().splitlines():
        if "|" not in line:
            errors.append(line)
            continue
        parts = line.split("|", 1)
        btn_text = parts[0].strip()
        btn_url = parts[1].strip()
        if btn_text and btn_url.startswith("http"):
            buttons.append({"text": btn_text, "url": btn_url})
        else:
            errors.append(line)
    await update_recurring_message(msg_id, url_buttons=json.dumps(buttons, ensure_ascii=False))
    await state.clear()
    msg = await get_recurring_message(msg_id)
    result = f"✅ Сохранено {len(buttons)} кнопок."
    if errors:
        result += f"\n❌ Пропущено строк: {len(errors)} (неверный формат)."
    await message.answer(
        f"{result}\n\n"
        f"✍️ <b>Настройка сообщения #{msg_id}</b>\n\n{_msg_preview(msg)}",
        reply_markup=recurring_content_keyboard(msg)
    )

@router.callback_query(F.data.startswith("rec_clear_buttons:"))
async def clear_buttons(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    await update_recurring_message(msg_id, url_buttons="[]")
    await state.clear()
    await call.answer("✅ Кнопки удалены")
    msg = await get_recurring_message(msg_id)
    await safe_edit(call, f"✍️ <b>Настройка сообщения #{msg_id}</b>\n\n{_msg_preview(msg)}", recurring_content_keyboard(msg))


@router.callback_query(F.data.startswith("rec_preview_text:"))
async def preview_text(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg or not msg.get("text"):
        return await call.answer("Текст не задан", show_alert=True)
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")
    ]])
    await call.message.answer(f"👁 <b>Текст:</b>\n\n{msg['text']}", reply_markup=kb)


@router.callback_query(F.data.startswith("rec_preview_media:"))
async def preview_media(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg or not msg.get("media_file_id"):
        return await call.answer("Медиа не задано", show_alert=True)
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")
    ]])
    if msg["media_type"] == "photo":
        await call.message.answer_photo(msg["media_file_id"], caption="👁 Медиа", reply_markup=kb)
    else:
        await call.message.answer_video(msg["media_file_id"], caption="👁 Медиа", reply_markup=kb)


@router.callback_query(F.data.startswith("rec_preview_buttons:"))
async def preview_buttons(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    try:
        buttons = json.loads(msg.get("url_buttons") or "[]")
    except Exception:
        buttons = []
    if not buttons:
        return await call.answer("Кнопки не заданы", show_alert=True)
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(text=b["text"], url=b["url"])] for b in buttons],
        [InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")]
    ])
    await call.message.answer("👁 <b>URL-кнопки:</b>", reply_markup=kb)


@router.callback_query(F.data.startswith("rec_full_preview:"))
async def full_preview(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)

    text = msg.get("text") or ""
    media_file_id = msg.get("media_file_id") or ""
    media_type = msg.get("media_type") or ""

    try:
        buttons = json.loads(msg.get("url_buttons") or "[]")
    except Exception:
        buttons = []

    reply_markup = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(text=b["text"], url=b["url"])] for b in buttons],
        [InlineKeyboardButton(text="« Назад", callback_data=f"rec_content:{msg_id}")]
    ])

    await call.answer()
    try:
        if media_file_id and media_type == "photo":
            await call.message.answer_photo(media_file_id, caption=text or None, reply_markup=reply_markup)
        elif media_file_id and media_type == "video":
            await call.message.answer_video(media_file_id, caption=text or None, reply_markup=reply_markup)
        elif text:
            await call.message.answer(text, reply_markup=reply_markup)
        else:
            await call.message.answer("⚠️ Сообщение пустое — задайте текст или медиа.")
    except Exception as e:
        await call.message.answer(f"❌ Ошибка просмотра: {e}")


@router.callback_query(F.data.startswith("rec_time:"))
async def set_time_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await state.set_state(RecurringState.waiting_start_time)
    await state.update_data(msg_id=msg_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data=f"rec_open:{msg_id}")
    ]])
    await safe_edit(
        call,
        f"🕐 Текущее время начала: <b>{msg['start_time']}</b>\n\n"
        f"Отправьте время в формате <code>ЧЧ:ММ</code> (МСК)\n"
        f"Например: <code>09:00</code> или <code>18:30</code>",
        kb
    )


@router.message(RecurringState.waiting_start_time)
async def set_time_input(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data["msg_id"]
    text = (message.text or "").strip()
    try:
        parts = text.split(":")
        h, m = int(parts[0]), int(parts[1])
        assert 0 <= h <= 23 and 0 <= m <= 59
        time_str = f"{h:02d}:{m:02d}"
    except Exception:
        return await message.answer("❌ Неверный формат. Введите время как <code>09:00</code>")
    msg = await get_recurring_message(msg_id)
    next_send = _calc_next_send(time_str, msg["interval_hours"], msg.get("end_time", "23:00")) if msg["enabled"] else 0.0
    await update_recurring_message(msg_id, start_time=time_str, next_send_at=next_send)
    await state.clear()
    msg = await get_recurring_message(msg_id)
    delete_prev = "✅" if msg["delete_previous"] else "❌"
    next_label = _format_next_send(msg["next_send_at"])
    await message.answer(
        f"✅ Время установлено: <b>{time_str}</b> (МСК)\n\n"
        f"🔁 <b>Повторяющееся сообщение #{msg_id}</b>\n\n"
        f"💡 Статус: {'Включено ✅' if msg['enabled'] else 'Выключено ❌'}\n"
        f"🕐 Время работы: <b>{msg['start_time']} — {msg['end_time']}</b>\n"
        f"🔁 Повторение: каждые <b>{msg['interval_hours']} ч.</b>\n"
        f"🗑 Удалять последнее: <b>{delete_prev}</b>\n\n"
        f"🚀 Следующая отправка: <b>{next_label}</b>",
        reply_markup=recurring_item_keyboard(msg)
    )


@router.callback_query(F.data.startswith("rec_interval:"))
async def set_interval_menu(call: CallbackQuery, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await safe_edit(
        call,
        f"🔁 Текущее повторение: каждые <b>{msg['interval_hours']} ч.</b>\n\n"
        f"Выберите как часто должно повторяться сообщение:",
        interval_keyboard(msg_id)
    )


@router.callback_query(F.data.startswith("rec_set_interval:"))
async def set_interval_value(call: CallbackQuery, bot: Bot):
    _, msg_id_str, hours_str = call.data.split(":")
    msg_id, hours = int(msg_id_str), int(hours_str)
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    next_send = _calc_next_send(msg["start_time"], hours, msg.get("end_time", "23:00")) if msg["enabled"] else 0.0
    await update_recurring_message(msg_id, interval_hours=hours, next_send_at=next_send)
    await call.answer(f"✅ Каждые {hours} ч.")
    msg = await get_recurring_message(msg_id)
    delete_prev = "✅" if msg["delete_previous"] else "❌"
    next_label = _format_next_send(msg["next_send_at"])
    text = (
        f"🔁 <b>Повторяющееся сообщение #{msg_id}</b>\n\n"
        f"💡 Статус: {'Включено ✅' if msg['enabled'] else 'Выключено ❌'}\n"
        f"🕐 Время работы: <b>{msg['start_time']} — {msg['end_time']}</b>\n"
        f"🔁 Повторение: каждые <b>{msg['interval_hours']} ч.</b>\n"
        f"🗑 Удалять последнее: <b>{delete_prev}</b>\n\n"
        f"🚀 Следующая отправка: <b>{next_label}</b>"
    )
    await safe_edit(call, text, recurring_item_keyboard(msg))


@router.callback_query(F.data.startswith("rec_endtime:"))
async def set_end_time_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    msg_id = int(call.data.split(":")[1])
    msg = await get_recurring_message(msg_id)
    if not msg:
        return await call.answer("Не найдено", show_alert=True)
    if not await is_admin(bot, msg["chat_id"], call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)
    await state.set_state(RecurringState.waiting_end_time)
    await state.update_data(msg_id=msg_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data=f"rec_open:{msg_id}")
    ]])
    await safe_edit(
        call,
        f"🕙 Текущее время окончания: <b>{msg['end_time']}</b>\n\n"
        f"Отправьте время в формате <code>ЧЧ:ММ</code> (МСК)\n"
        f"Например: <code>22:00</code> или <code>23:30</code>",
        kb
    )


@router.message(RecurringState.waiting_end_time)
async def set_end_time_input(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data["msg_id"]
    text = (message.text or "").strip()
    try:
        parts = text.split(":")
        h, m = int(parts[0]), int(parts[1])
        assert 0 <= h <= 23 and 0 <= m <= 59
        time_str = f"{h:02d}:{m:02d}"
    except Exception:
        return await message.answer("❌ Неверный формат. Введите время как <code>22:00</code>")
    await update_recurring_message(msg_id, end_time=time_str)
    await state.clear()
    msg = await get_recurring_message(msg_id)
    delete_prev = "✅" if msg["delete_previous"] else "❌"
    next_label = _format_next_send(msg["next_send_at"])
    await message.answer(
        f"✅ Время окончания установлено: <b>{time_str}</b> (МСК)\n\n"
        f"🔁 <b>Повторяющееся сообщение #{msg_id}</b>\n\n"
        f"💡 Статус: {'Включено ✅' if msg['enabled'] else 'Выключено ❌'}\n"
        f"🕐 Время работы: <b>{msg['start_time']} — {msg['end_time']}</b>\n"
        f"🔁 Повторение: каждые <b>{msg['interval_hours']} ч.</b>\n"
        f"🗑 Удалять последнее: <b>{delete_prev}</b>\n\n"
        f"🚀 Следующая отправка: <b>{next_label}</b>",
        reply_markup=recurring_item_keyboard(msg)
    )
