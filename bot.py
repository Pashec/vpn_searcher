import asyncio
import logging
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vpn_bot")

from app.core.config import settings
from app.schemas.memo import MemoResponseSchema, UserCandidatesResponseSchema
from app.services.urfa_client import UrfaMemoService

dp = Dispatcher()
memo_service = UrfaMemoService()


def format_memo_message(memo: MemoResponseSchema) -> str:
    """Форматирует карточку сотрудника в удобный читаемый вид для Telegram."""
    emp = memo.employee
    net = memo.network
    vpn = memo.vpn

    primary_mac = net.mac_addresses[0] if (net.mac_addresses and len(net.mac_addresses) > 0) else "Не указан"

    lines = [
        f"👤 <b>{escape(emp.full_name)}</b>",
        f"🏢 Корпус: <b>{escape(emp.building or '-')}</b> | Кабинет: <b>{escape(emp.room or '-')}</b>",
        f"📞 Телефон: <b>{escape(emp.phone or '-')}</b>",
        f"💼 Должность: {escape(emp.position or 'Сотрудник')}",
        f"🏷 Тариф: {escape(emp.tariff or 'Безлимитный')}",
        "",
        f"🖥 <b>MAC-адрес:</b> <code>{escape(primary_mac)}</code>",
        f"🌐 <b>VPN Сервер:</b> <code>{escape(vpn.vpn_server)}</code>",
        "",
    ]

    if vpn.vpn_accounts:
        for idx, acc in enumerate(vpn.vpn_accounts, start=1):
            title = f"🔑 <b>Учётная запись VPN #{idx}:</b>" if len(vpn.vpn_accounts) > 1 else "🔑 <b>Учётная запись VPN:</b>"
            acc_mac = acc.host_ip if (acc.host_ip and ("-" in acc.host_ip or ":" in acc.host_ip)) else primary_mac
            vpn_ip = acc.vpn_ip or "Динамический"

            lines.extend([
                title,
                f"• Логин: <code>{escape(acc.login or '-')}</code>",
                f"• Пароль: <code>{escape(acc.password or '-')}</code>",
                f"• Выделенный IP: <code>{escape(vpn_ip)}</code>",
                f"• Привязка к MAC: <code>{escape(acc_mac)}</code>",
                "",
            ])
    else:
        lines.extend([
            "🔑 <b>Учётная запись:</b>",
            f"• Логин: <code>{escape(memo.statistics.stat_login or '-')}</code>",
            f"• Пароль: <code>{escape(memo.statistics.stat_password or '-')}</code>",
            "",
        ])

    return "\n".join(lines).strip()


def check_access(user_id: int) -> bool:
    """Проверяет доступ пользователя (только для владельца бота)."""
    if not settings.TG_ADMIN_ID:
        return True
    is_allowed = user_id == settings.TG_ADMIN_ID
    if not is_allowed:
        logger.warning(f"Попытка доступа от неавторизованного пользователя ID: {user_id} (ожидается: {settings.TG_ADMIN_ID})")
    return is_allowed


@dp.message(CommandStart())
async def cmd_start(message: Message):
    logger.info(f"Получена команда /start от {message.from_user.id} (@{message.from_user.username})")
    if not check_access(message.from_user.id):
        await message.answer(f"⛔ Доступ запрещён. Твой ID: <code>{message.from_user.id}</code>")
        return

    await message.answer(
        "👋 <b>Бот поиска VPN ДГТУ готов к работе!</b>\n\n"
        "Просто отправь мне в чат:\n"
        "• <b>Фамилию</b> (например: <code>Иванов</code> или <code>Купчук</code>)\n"
        "• <b>Кабинет</b> (например: <code>709</code> или <code>1-709</code>)\n"
        "• <b>Логин абонента</b> или <b>IP-адрес</b>\n\n"
        "Если найдено несколько человек — я дам список для выбора.",
    )


@dp.message(F.text)
async def handle_search(message: Message, bot: Bot):
    logger.info(f"Поисковый запрос от {message.from_user.id}: '{message.text}'")
    if not check_access(message.from_user.id):
        await message.answer(f"⛔ Доступ запрещён. Твой ID: <code>{message.from_user.id}</code>")
        return

    query = message.text.strip()
    if not query:
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        result = await memo_service.search(query)
    except ConnectionError as e:
        logger.error(f"Ошибка биллинга при поиске '{query}': {e}")
        await message.answer(f"⚠️ <b>Ошибка связи с биллингом:</b>\n{escape(str(e))}")
        return
    except Exception as e:
        logger.exception("Исключение при поиске через бота")
        await message.answer(f"⚠️ <b>Произошла ошибка:</b>\n{escape(str(e))}")
        return

    if result is None:
        await message.answer(f"🔍 По запросу <b>«{escape(query)}»</b> никто не найден.")
        return

    if isinstance(result, MemoResponseSchema):
        text = format_memo_message(result)
        await message.answer(text)
        return

    if isinstance(result, UserCandidatesResponseSchema):
        candidates = result.candidates
        buttons = []

        for c in candidates:
            room_info = f"каб. {c.room}" if c.room else ""
            building_info = f"к. {c.building}" if c.building else ""
            loc = f" ({building_info} {room_info})".strip()
            if loc == "()":
                loc = ""

            btn_text = f"{c.full_name}{loc}"
            callback_data = f"uid:{c.user_id}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=callback_data)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"🔍 Найдено сотрудников: <b>{len(candidates)}</b>.\nВыберите нужного:",
            reply_markup=keyboard,
        )


@dp.callback_query(F.data.startswith("uid:"))
async def handle_user_selection(callback: CallbackQuery):
    logger.info(f"Клик по кандидату от {callback.from_user.id}: {callback.data}")
    if not check_access(callback.from_user.id):
        await callback.answer(f"Доступ запрещён. ID: {callback.from_user.id}", show_alert=True)
        return

    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Неверный ID", show_alert=True)
        return

    await callback.answer("Загружаю памятку...")

    try:
        memo = await memo_service.get_by_user_id(user_id)
    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка загрузки: {escape(str(e))}")
        return

    if not memo:
        await callback.message.answer("❌ Данные абонента не найдены.")
        return

    text = format_memo_message(memo)
    await callback.message.answer(text)


async def main():
    if not settings.TG_BOT_TOKEN:
        logger.error("TG_BOT_TOKEN не задан в .env! Запуск бота отменен.")
        return

    bot = Bot(token=settings.TG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    logger.info("Подключение к Telegram API...")

    # Удаляем вебхук
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Старый вебхук сброшен. Начинаем слушать сообщения (Long Polling)...")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
