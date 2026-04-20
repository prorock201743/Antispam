import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from bot.handlers import admin_router, group_router, recurring_router
from bot.middlewares.antiflood import AntiFloodMiddleware
from bot.database.db import init_db
from aiogram.client.session.aiohttp import AiohttpSession
from bot.database.recurring_db import init_recurring_db
from bot.scheduler import scheduler_loop
from config import BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    await init_db()
    await init_recurring_db()
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()

    dp.message.outer_middleware(AntiFloodMiddleware())

    dp.include_router(admin_router)
    dp.include_router(group_router)
    dp.include_router(recurring_router)

    asyncio.create_task(scheduler_loop(bot))

    logger.info("Бот запущен!")
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
    )


if __name__ == "__main__":
    asyncio.run(main())