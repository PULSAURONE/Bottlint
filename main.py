# START OF FILE main.py #

import logging
import asyncio
import os
import sys
from telegram import Update, BotCommandScopeAllPrivateChats
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext
)

if sys.platform == "win32" and sys.version_info >= (3, 8):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import TELEGRAM_BOT_TOKEN, LOG_LEVEL, LOG_FORMAT, LOG_FILE_PATH, ALLOWED_TELEGRAM_IDS, CONVERSATION_TIMEOUT

from handlers import (
    start, logs_command, connect_google_drive, handle_auth_code, cancel_google_drive_auth,
    handle_kb_callback, reset_chat, reset_chat_confirm, reset_chat_cancel,
    knowledge_base_menu, handle_text_or_voice, settings_and_status_command,
    upload_file_start, set_global_services, stop_llm_generation,
    handle_telegram_document_upload
)

from settings_service import (
    SettingsService, SELECT_SETTING, SELECT_TEXT_AI, SELECT_VOICE_AI,
    AWAITING_LOCAL_LLM_PATH, AWAITING_LOCAL_WHISPER_PATH, AWAITING_API_KEY_INPUT,
    AWAITING_CLIENT_SECRET, SELECT_SEARCH_MODE
)
from handlers import RESET_CHAT_CONFIRM, AWAITING_AUTH_CODE

from google_drive_service import GoogleDriveService
from file_parser_service import FileParserService
from knowledge_base_service import KnowledgeBaseService
from generative_ai_service import GenerativeAIServiceFactory
from speech_to_text_service import get_stt_service
from external_knowledge_service import ExternalKnowledgeService
from status_service import StatusService

logging.basicConfig(format=LOG_FORMAT, level=LOG_LEVEL,
                    handlers=[logging.FileHandler(LOG_FILE_PATH, encoding='utf-8'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

settings_service_instance = None


async def post_init(application: Application) -> None:
    commands = [
        ("start", "🚀 Запустить / Перезапустить бота"),
        ("upload", "📚 Загрузить с Google Drive"),
        ("upload_from_pc", "📥 Загрузить с ПК/телефона"),
        ("kb", "📂 Управление Базой Знаний"),
        ("reset_chat", "🔄 Сбросить диалог"),
        ("status", "⚙️ Настройки и Статус"),
        ("connect_google_drive", "🔗 Подключить Google Drive"),
        ("logs", "📄 Показать логи (для админов)"),
        ("restart", "🚨 Перезапустить процесс (для админов)"),
        ("cancel", "❌ Отменить текущее действие"),
    ]
    await application.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    logger.info("Команды меню Telegram успешно установлены.")


async def restart_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if ALLOWED_TELEGRAM_IDS and user.id not in ALLOWED_TELEGRAM_IDS:
        await update.message.reply_text("❌ Доступ к перезапуску ограничен.")
        return
    await update.message.reply_text("🔄 Перезапускаю процесс...")
    sys.exit(0)


def main() -> None:
    logger.info("Инициализация приложения...")
    if not TELEGRAM_BOT_TOKEN: logger.critical("TELEGRAM_BOT_TOKEN не найден."); sys.exit(1)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    drive_service = GoogleDriveService()
    parser_service = FileParserService()
    kb_service = KnowledgeBaseService()
    ai_service = GenerativeAIServiceFactory.get_service()
    stt_service = get_stt_service()
    ext_knowledge_service = ExternalKnowledgeService()
    status_service = StatusService(drive_service, ai_service, stt_service, ext_knowledge_service, kb_service)
    global settings_service_instance
    settings_service_instance = SettingsService()

    set_global_services(drive_service, parser_service, kb_service, ai_service, stt_service, ext_knowledge_service,
                        status_service, settings_service_instance)

    settings_handler = ConversationHandler(
        entry_points=[
            CommandHandler("status", settings_and_status_command),
            MessageHandler(filters.Regex("^⚙️ Настройки и Статус$"), settings_and_status_command),
            CommandHandler("settings", settings_service_instance.start_settings),
            CallbackQueryHandler(settings_service_instance.start_settings, pattern="^settings_start_from_status$"),
        ],
        states={
            SELECT_SETTING: [
                CallbackQueryHandler(settings_service_instance.handle_setting_selection, pattern="^settings_")],
            SELECT_TEXT_AI: [CallbackQueryHandler(settings_service_instance.handle_text_provider_selection,
                                                  pattern="^text_provider_"),
                             CallbackQueryHandler(settings_service_instance.start_settings, pattern="^settings_back$")],
            SELECT_VOICE_AI: [CallbackQueryHandler(settings_service_instance.handle_voice_provider_selection,
                                                   pattern="^voice_provider_"),
                              CallbackQueryHandler(settings_service_instance.start_settings,
                                                   pattern="^settings_back$")],
            SELECT_SEARCH_MODE: [
                CallbackQueryHandler(settings_service_instance.handle_search_mode_selection, pattern="^search_mode_")],
            AWAITING_LOCAL_LLM_PATH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_service_instance.handle_local_llm_path)],
            AWAITING_LOCAL_WHISPER_PATH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_service_instance.handle_local_whisper_path)],
            AWAITING_API_KEY_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_service_instance.handle_api_key_input)],
            AWAITING_CLIENT_SECRET: [
                MessageHandler(filters.Document.ALL, settings_service_instance.handle_client_secret_upload)]
        },
        fallbacks=[CallbackQueryHandler(settings_service_instance.cancel_settings, pattern="settings_cancel"),
                   CommandHandler("cancel", settings_service_instance.cancel_settings)],
        conversation_timeout=CONVERSATION_TIMEOUT, per_user=True, allow_reentry=True
    )
    application.add_handler(settings_handler)

    reset_chat_handler = ConversationHandler(
        entry_points=[CommandHandler("reset_chat", reset_chat),
                      MessageHandler(filters.Regex("^🔄 Сбросить диалог$"), reset_chat)],
        states={RESET_CHAT_CONFIRM: [CallbackQueryHandler(reset_chat_confirm, pattern="^reset_chat_confirm$"),
                                     CallbackQueryHandler(reset_chat_cancel, pattern="^reset_chat_cancel$")]},
        fallbacks=[CommandHandler("cancel", reset_chat_cancel)],
        conversation_timeout=CONVERSATION_TIMEOUT, per_user=True, allow_reentry=True
    )
    application.add_handler(reset_chat_handler)

    google_drive_auth_handler = ConversationHandler(
        entry_points=[CommandHandler("connect_google_drive", connect_google_drive)],
        states={AWAITING_AUTH_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_code)]},
        fallbacks=[CommandHandler("cancel", cancel_google_drive_auth)],
        conversation_timeout=CONVERSATION_TIMEOUT, per_user=True, allow_reentry=True
    )
    application.add_handler(google_drive_auth_handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^📚 Загрузить файл с Google Drive$"), upload_file_start))
    application.add_handler(CommandHandler("upload", upload_file_start))
    application.add_handler(MessageHandler(filters.Regex("^📂 Управление Базой Знаний$"), knowledge_base_menu))
    application.add_handler(CommandHandler("kb", knowledge_base_menu))
    application.add_handler(MessageHandler(filters.Regex("^📥 Загрузить файл с ПК/телефона$"),
                                           lambda u, c: u.message.reply_text(
                                               "Просто отправьте мне файл (PDF, DOCX, TXT), который вы хотите добавить в базу знаний.")))
    application.add_handler(CommandHandler("upload_from_pc", lambda u, c: u.message.reply_text(
        "Просто отправьте мне файл (PDF, DOCX, TXT), который вы хотите добавить в базу знаний.")))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_telegram_document_upload))
    application.add_handler(CallbackQueryHandler(handle_kb_callback))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CallbackQueryHandler(stop_llm_generation, pattern="^stop_llm_generation$"))
    application.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.VOICE, handle_text_or_voice))

    logger.info("Бот готов к запуску. Запускаем polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        logger.critical(f"Фатальная ошибка при запуске: {e}", exc_info=True)
    finally:
        logger.info("Бот успешно остановлен.")


if __name__ == '__main__':
    if sys.platform == "win32" and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        main()
    except Exception as e:
        logger.critical(f"Фатальная ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)

# END OF FILE main.py #