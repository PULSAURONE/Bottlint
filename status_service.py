# START OF FILE status_service.py #

import logging
import os
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, \
    InlineKeyboardMarkup  # Добавлены InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from config import (
    TEXT_AI_PROVIDER,
    VOICE_AI_PROVIDER,  # Добавлен импорт VOICE_AI_PROVIDER
    GOOGLE_DRIVE_CREDENTIALS_PATH,
    ALLOWED_TELEGRAM_IDS,
    MAIN_KEYBOARD_MARKUP
)

logger = logging.getLogger(__name__)


class StatusService:
    """Сервис для отображения текущего состояния бота."""

    def __init__(self, drive_service, ai_service, stt_service, ext_knowledge_service, kb_service):
        self.drive_service = drive_service
        self.ai_service = ai_service
        self.stt_service = stt_service
        self.ext_knowledge_service = ext_knowledge_service
        self.kb_service = kb_service

    async def get_status(self, update: Update, context: CallbackContext) -> None:
        """Отправляет пользователю текущий статус бота с кнопками для дальнейших действий."""
        user = update.effective_user
        logger.info(f"Пользователь {user.username} (ID: {user.id}) запросил статус бота.")

        # Определяем статусы компонентов
        ai_status_icon = "✅" if self.ai_service else "❌"
        voice_status_icon = "✅" if self.stt_service else "❌"
        web_search_status_icon = "✅" if self.ext_knowledge_service and (
                (hasattr(self.ext_knowledge_service, 'google_search') and self.ext_knowledge_service.google_search) or \
                (hasattr(self.ext_knowledge_service, 'wikipedia') and self.ext_knowledge_service.wikipedia)
        ) else "❌"
        drive_status_icon = "✅" if self.drive_service and self.drive_service.is_authenticated else "❌"

        # Детализация статуса Базы Знаний
        kb_docs_count = 0
        if self.kb_service and self.kb_service.source_id_to_faiss_ids_map:
            kb_docs_count = len(self.kb_service.source_id_to_faiss_ids_map)

        kb_status_text = "Пуста"
        if kb_docs_count > 0:
            kb_status_text = f"{kb_docs_count} документ{'ов' if kb_docs_count != 1 else ''} (есть данные)"
            kb_status_icon = "✅"
        else:
            kb_status_icon = "❌"

        # Формируем более читаемый текст статуса
        status_text = (
            "<b>📊 Статус бота:</b>\n\n"
            f"👤 <b>Доступ:</b> {'Ограничен' if ALLOWED_TELEGRAM_IDS else 'Открыт для всех'}\n"
            f"🤖 <b>AI-текст:</b> {TEXT_AI_PROVIDER or 'не настроен'} {ai_status_icon}\n"
            f"🎤 <b>AI-голос:</b> {VOICE_AI_PROVIDER or 'не настроен'} {voice_status_icon}\n"
            f"🌐 <b>Поиск в интернете:</b> {'Включен' if web_search_status_icon == '✅' else 'Выключен'} {web_search_status_icon}\n"
            f"📂 <b>Google Drive:</b> {'Подключен' if drive_status_icon == '✅' else 'Не подключен'} {drive_status_icon}\n"
            f"🧠 <b>База знаний:</b> {kb_status_text} {kb_status_icon}\n\n"
            f"💾 <b>Файл client_secret.json:</b> {'Найден' if os.path.exists(GOOGLE_DRIVE_CREDENTIALS_PATH) else 'Отсутствует'}\n\n"
            "💡 Используйте кнопки ниже для навигации или <b>'⚙️ Перейти к настройкам'</b> для детальной настройки."
        )

        # Отправляем сообщение со статусом и главным меню
        # Добавляем инлайн-кнопку для перехода в настройки
        keyboard = [[InlineKeyboardButton("⚙️ Перейти к настройкам", callback_data="settings_start_from_status")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправляем статус
        await update.message.reply_text(status_text, parse_mode='HTML', reply_markup=reply_markup)
        # Отдельно отправляем главное меню, чтобы оно всегда было внизу
        await update.message.reply_text("Выберите действие:", reply_markup=MAIN_KEYBOARD_MARKUP)

# END OF FILE status_service.py #