import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ID администраторов бота (могут управлять ботом в любом чате)
BOT_ADMINS: list[int] = [
    int(x) for x in os.getenv("BOT_ADMINS", "").split(",") if x.strip().isdigit()
]

# Настройки по умолчанию для новых групп
DEFAULT_SETTINGS = {
    "interval": 86400,           # 1 сутки в секундах
    "max_messages": 3,           # Сообщений за интервал
    "restriction_mode": "mute",  # mute | ban | kick
    "mute_duration": 86400,      # 1 сутки в секундах
    "auto_delete_bot_msgs": True, # Автоудаление сообщений бота
    "auto_delete_delay": 90,     # Задержка удаления (секунды)
    "whitelist": [],             # ID в белом списке
    "enabled": True,             # Включён ли антифлуд
}
