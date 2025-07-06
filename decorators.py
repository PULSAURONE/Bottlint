# START OF FILE decorators.py #

import logging
from functools import wraps
from telegram import Update
from telegram.ext import CallbackContext

# Импортируем список разрешенных ID из центральной конфигурации
from config import ALLOWED_TELEGRAM_IDS

logger = logging.getLogger(__name__)


def authorized_only(func):
    """
    Декоратор для ограничения доступа к обработчикам команд и колбэков.
    Проверяет, находится ли ID пользователя в списке разрешенных.
    Работает как с обычными сообщениями, так и с нажатиями на inline-кнопки.
    """

    @wraps(func)
    async def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        # Если список разрешенных ID пуст, разрешаем доступ всем.
        if not ALLOWED_TELEGRAM_IDS:
            return await func(update, context, *args, **kwargs)

        # --- ИСПРАВЛЕННАЯ ЛОГИКА ПОЛУЧЕНИЯ ПОЛЬЗОВАТЕЛЯ ---
        user = None
        # Сначала пробуем стандартный способ
        if update.effective_user:
            user = update.effective_user
        # Если это callback_query, effective_user может быть None,
        # тогда берем пользователя из самого запроса
        elif update.callback_query:
            user = update.callback_query.from_user
        # Если это сообщение, но effective_user почему-то пуст
        elif update.message:
            user = update.message.from_user

        if not user:
            logger.warning("Не удалось определить пользователя ни одним из способов. Доступ запрещен.")
            # Для надежности, если пользователь не определен, пытаемся отправить сообщение,
            # хотя это может быть сложно без user_id/chat_id
            if update.effective_chat:
                try:
                    await update.effective_chat.send_message("⛔ Произошла ошибка определения пользователя. Доступ запрещен.")
                except Exception as e:
                    logger.error(f"Не удалось отправить сообщение об ошибке доступа: {e}")
            return

        user_id = user.id
        username = user.username or "N/A"

        # Проверяем, есть ли ID пользователя в списке разрешенных
        if user_id not in ALLOWED_TELEGRAM_IDS:
            logger.warning(
                f"Неавторизованный доступ от пользователя {username} (ID: {user_id}) к функции {func.__name__}.")

            # Отвечаем в зависимости от типа обновления
            if update.callback_query:
                await update.callback_query.answer("⛔ У вас нет доступа к этой функции.", show_alert=True)
            elif update.message:
                await update.message.reply_text("⛔ У вас нет доступа к этой функции.")
            return

        logger.debug(f"Авторизованный доступ для пользователя {username} (ID: {user_id}) к функции {func.__name__}.")
        return await func(update, context, *args, **kwargs)

    return wrapped

# END OF FILE decorators.py #