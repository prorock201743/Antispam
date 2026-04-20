from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def settings_menu(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
    enabled = settings.get("enabled", True)
    status = "✅ Включён" if enabled else "❌ Выключен"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{'🟢' if enabled else '🔴'} Антифлуд: {status}",
                callback_data=f"af_toggle:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="⏱ Интервал", callback_data=f"af_interval:{chat_id}"),
            InlineKeyboardButton(text="💬 Кол-во сообщений", callback_data=f"af_maxmsg:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="⚡ Режим ограничения", callback_data=f"af_mode:{chat_id}"),
            InlineKeyboardButton(text="⏳ Длительность мута", callback_data=f"af_mutedur:{chat_id}"),
        ],
        [
            InlineKeyboardButton(
                text=f"🗑 Автоудаление: {'вкл' if settings.get('auto_delete_bot_msgs') else 'выкл'}",
                callback_data=f"af_autodel:{chat_id}"
            ),
            InlineKeyboardButton(text="👥 Белый список", callback_data=f"af_whitelist:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"af_stats:{chat_id}"),
            InlineKeyboardButton(text="🔄 Сбросить настройки", callback_data=f"af_reset:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="🚫 Запрещённые фразы", callback_data=f"af_phrases:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="🔁 Повторяющиеся сообщения", callback_data=f"rec_list:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="« Назад к группам", callback_data="af_groups"),
        ],
    ])


def interval_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    options = [
        ("1 час", 3600),
        ("6 часов", 21600),
        ("12 часов", 43200),
        ("1 сутки", 86400),
        ("3 суток", 259200),
        ("7 дней", 604800),
    ]
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"af_set_interval:{chat_id}:{val}")]
        for label, val in options
    ]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def maxmsg_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    options = [1, 2, 3, 5, 10, 15, 20]
    buttons = [
        [InlineKeyboardButton(text=str(n), callback_data=f"af_set_maxmsg:{chat_id}:{n}")]
        for n in options
    ]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def mode_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔇 Мут (стандартный)", callback_data=f"af_set_mode:{chat_id}:mute")],
        # [InlineKeyboardButton(text="👟 Кик (исключить)", callback_data=f"af_set_mode:{chat_id}:kick")],
        # [InlineKeyboardButton(text="🚫 Бан (навсегда)", callback_data=f"af_set_mode:{chat_id}:ban")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")],
    ])


def mute_duration_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    options = [
        ("10 минут", 600),
        ("1 час", 3600),
        ("6 часов", 21600),
        ("1 сутки", 86400),
        ("3 суток", 259200),
        ("7 дней", 604800),
        ("Навсегда", 0),
    ]
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"af_set_mutedur:{chat_id}:{val}")]
        for label, val in options
    ]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def groups_keyboard(groups: list[dict], bot_username: str = "") -> InlineKeyboardMarkup:
    buttons = []
    for g in groups:
        title = (g["chat_title"] or "Без названия")[:30]
        buttons.append([
            InlineKeyboardButton(
                text=f"{'✅' if g['settings'].get('enabled') else '❌'} {title}",
                callback_data=f"af_settings:{g['chat_id']}"
            )
        ])

    # Кнопка подключения нового чата (deep link с правами администратора)
    if bot_username:
        # admin= задаёт права, которые будут предложены при добавлении
        connect_url = (
            f"https://t.me/{bot_username}?startgroup=connect"
            f"&admin=restrict_members+delete_messages+pin_messages"
        )
        buttons.append([
            InlineKeyboardButton(
                text="➕ Подключить новый чат",
                url=connect_url
            )
        ])

    if not any(True for g in groups):
        # Вставляем пояснение перед кнопкой если групп нет
        buttons.insert(0, [
            InlineKeyboardButton(text="— Нет подключённых групп —", callback_data="noop")
        ])

    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить список", callback_data="af_groups")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def whitelist_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ID", callback_data=f"af_wl_add:{chat_id}")],
        [InlineKeyboardButton(text="➖ Удалить ID", callback_data=f"af_wl_remove:{chat_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")],
    ])


def confirm_reset_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, сбросить", callback_data=f"af_confirm_reset:{chat_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"af_settings:{chat_id}"),
        ]
    ])


def phrases_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить фразу", callback_data=f"af_phrase_add:{chat_id}")],
        [InlineKeyboardButton(text="➖ Удалить фразу", callback_data=f"af_phrase_remove:{chat_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")],
    ])
