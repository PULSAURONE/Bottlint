# START OF FILE settings_service.py #

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from config import DATA_DIR, ALLOWED_TELEGRAM_IDS, GOOGLE_DRIVE_TOKEN_PATH, SEARCH_MODE

logger = logging.getLogger(__name__)

# --- Добавляем новое состояние для выбора режима поиска ---
(
    SELECT_SETTING,
    SELECT_TEXT_AI,
    SELECT_VOICE_AI,
    AWAITING_LOCAL_LLM_PATH,
    AWAITING_LOCAL_WHISPER_PATH,
    AWAITING_API_KEY_INPUT,
    AWAITING_CLIENT_SECRET,
    SELECT_SEARCH_MODE
) = range(8)


class SettingsService:
    def __init__(self):
        self.env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

    def _update_env_file(self, updates: dict):
        env_content = {}
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_content[key.strip()] = value.strip().strip('"')
        env_content.update({k: v for k, v in updates.items() if v is not None})
        keys_to_delete = [key for key, value in updates.items() if value is None]
        for key in keys_to_delete:
            if key in env_content:
                del env_content[key]
        with open(self.env_path, 'w', encoding='utf-8') as f:
            for key, value in env_content.items():
                if isinstance(value, str) and (' ' in value or ':' in value or '/' in value or '\\' in value):
                    f.write(f'{key}="{value}"\n')
                else:
                    f.write(f"{key}={value}\n")

    async def start_settings(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        if ALLOWED_TELEGRAM_IDS and user.id not in ALLOWED_TELEGRAM_IDS:
            if update.callback_query:
                await update.callback_query.answer("⛔ У вас нет доступа к настройкам.", show_alert=True)
            else:
                await update.message.reply_text("⛔ Доступ к настройкам ограничен.")
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton("🤖 Настроить AI для текста", callback_data="settings_text_ai")],
            [InlineKeyboardButton("🎤 Настроить AI для голоса", callback_data="settings_voice_ai")],
            [InlineKeyboardButton("🔍 Настроить режим поиска", callback_data="settings_search_mode")],
            [InlineKeyboardButton("🔑 Настроить API-ключи", callback_data="settings_api_keys")],
            [InlineKeyboardButton("📂 Загрузить client_secret.json", callback_data="settings_client_secret")],
            [InlineKeyboardButton("❌ Закрыть", callback_data="settings_cancel")],
        ]
        message_text = "⚙️ **Меню настроек**\n\nВыберите, что вы хотите настроить:"
        if update.callback_query:
            await update.callback_query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard),
                                                          parse_mode='Markdown')
        else:
            await update.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard),
                                            parse_mode='Markdown')
        return SELECT_SETTING

    async def handle_setting_selection(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        await query.answer()
        selection = query.data

        if selection == "settings_text_ai":
            keyboard = [[InlineKeyboardButton("🤖 OpenAI (GPT)", callback_data="text_provider_openai")],
                        [InlineKeyboardButton("💻 Локальная модель (GGUF)", callback_data="text_provider_local")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="settings_back")]]
            await query.edit_message_text("Выберите провайдера для **генерации текста**:",
                                          reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return SELECT_TEXT_AI

        elif selection == "settings_voice_ai":
            keyboard = [[InlineKeyboardButton("☁️ OpenAI (Whisper API)", callback_data="voice_provider_openai")], [
                InlineKeyboardButton("🖥️ Локальная модель (Whisper.cpp)", callback_data="voice_provider_local")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="settings_back")]]
            await query.edit_message_text("Выберите провайдера для **распознавания речи**:",
                                          reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return SELECT_VOICE_AI

        elif selection == "settings_search_mode":
            current_mode = SEARCH_MODE
            modes = {"kb_then_web": "Сначала в Базе Знаний, потом в интернете", "kb_only": "Только в Базе Знаний",
                     "web_only": "Только в интернете"}
            keyboard = [
                [InlineKeyboardButton(f"{'✅' if current_mode == 'kb_then_web' else ''} БЗ ➡️ Интернет",
                                      callback_data="search_mode_kb_then_web")],
                [InlineKeyboardButton(f"{'✅' if current_mode == 'kb_only' else ''} Только БЗ",
                                      callback_data="search_mode_kb_only")],
                [InlineKeyboardButton(f"{'✅' if current_mode == 'web_only' else ''} Только Интернет",
                                      callback_data="search_mode_web_only")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="settings_back")]
            ]
            await query.edit_message_text(
                f"Выберите, где бот должен искать информацию.\n\nТекущий режим: *{modes.get(current_mode, 'Неизвестно')}*",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return SELECT_SEARCH_MODE

        elif selection == "settings_client_secret":
            await query.edit_message_text("📎 Отправьте файл `client_secret.json` для Google Drive.")
            return AWAITING_CLIENT_SECRET

        elif selection == "settings_api_keys":
            await query.edit_message_text("🔑 Введите ваш **OpenAI API Key** (должен начинаться с `sk-`):",
                                          parse_mode='Markdown')
            return AWAITING_API_KEY_INPUT

        elif selection == "settings_cancel":
            await query.edit_message_text("Настройки закрыты.")
            return ConversationHandler.END

        elif selection == "settings_back":
            return await self.start_settings(update, context)

    async def handle_search_mode_selection(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        await query.answer()
        mode = query.data.replace("search_mode_", "")

        self._update_env_file({'SEARCH_MODE': mode})

        await query.edit_message_text(
            f"✅ Режим поиска изменен на: *{mode}*.\n\n🚨 **Важно:** Перезапустите бота, чтобы изменения вступили в силу.",
            parse_mode='Markdown')
        return ConversationHandler.END

    async def handle_text_provider_selection(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query;
        await query.answer();
        provider = query.data.split('_')[-1]
        if provider == "local":
            await query.edit_message_text("Отправьте мне **полный путь** к файлу вашей `GGUF` модели...",
                                          parse_mode='Markdown')
            return AWAITING_LOCAL_LLM_PATH
        elif provider == "openai":
            self._update_env_file({'TEXT_AI_PROVIDER': 'openai', 'LOCAL_LLM_PATH': None})
            await query.edit_message_text("✅ AI для текста установлен на **OpenAI**.\nПерезапустите бота.",
                                          parse_mode='Markdown')
            return ConversationHandler.END

    async def handle_voice_provider_selection(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query;
        await query.answer();
        provider = query.data.split('_')[-1]
        if provider == "local":
            await query.edit_message_text("Отправьте мне **полный путь** к файлу вашей `ggml` модели Whisper...",
                                          parse_mode='Markdown')
            return AWAITING_LOCAL_WHISPER_PATH
        elif provider == "openai":
            self._update_env_file({'VOICE_AI_PROVIDER': 'openai', 'LOCAL_WHISPER_PATH': None})
            await query.edit_message_text("✅ AI для голоса установлен на **OpenAI Whisper API**.\nПерезапустите бота.",
                                          parse_mode='Markdown')
            return ConversationHandler.END

    async def handle_local_llm_path(self, update: Update, context: CallbackContext) -> int:
        path = update.message.text.strip().strip('"')
        if not path.lower().endswith(".gguf") or not os.path.isfile(path): await update.message.reply_text(
            "❌ Файл не найден или имеет неверное расширение."); return AWAITING_LOCAL_LLM_PATH
        self._update_env_file({'TEXT_AI_PROVIDER': 'local', 'LOCAL_LLM_PATH': path})
        await update.message.reply_text(f"✅ Путь к LLM сохранен.\nПерезапустите бота.", parse_mode='Markdown');
        return ConversationHandler.END

    async def handle_local_whisper_path(self, update: Update, context: CallbackContext) -> int:
        path = update.message.text.strip().strip('"')
        if not os.path.isfile(path): await update.message.reply_text(
            "❌ Файл не найден."); return AWAITING_LOCAL_WHISPER_PATH
        self._update_env_file({'VOICE_AI_PROVIDER': 'local', 'LOCAL_WHISPER_PATH': path})
        await update.message.reply_text(f"✅ Путь к Whisper сохранен.\nПерезапустите бота.", parse_mode='Markdown');
        return ConversationHandler.END

    async def handle_api_key_input(self, update: Update, context: CallbackContext) -> int:
        api_key = update.message.text.strip()
        if not api_key.startswith("sk-"): await update.message.reply_text(
            "❌ Неверный формат OpenAI API ключа."); return AWAITING_API_KEY_INPUT
        self._update_env_file({"OPENAI_API_KEY": api_key})
        await update.message.reply_text("✅ OpenAI API ключ сохранен.\nПерезапустите бота.");
        return ConversationHandler.END

    async def handle_client_secret_upload(self, update: Update, context: CallbackContext) -> int:
        if not update.message.document or update.message.document.file_name.lower() != 'client_secret.json':
            await update.message.reply_text("❌ Ожидается файл с именем `client_secret.json`.");
            return AWAITING_CLIENT_SECRET
        file = await update.message.document.get_file()
        file_path = os.path.join(DATA_DIR, 'client_secret.json')
        try:
            await file.download_to_drive(file_path)
            if os.path.exists(GOOGLE_DRIVE_TOKEN_PATH): os.remove(GOOGLE_DRIVE_TOKEN_PATH)
            await update.message.reply_text(
                "✅ Файл `client_secret.json` загружен. Старый токен сброшен.\n\n🚨 **Важно:** **Перезапустите бота**.",
                parse_mode='Markdown')
            return ConversationHandler.END
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при сохранении файла: {e}");
            return AWAITING_CLIENT_SECRET

    async def cancel_settings(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        if query:
            await query.answer(); await query.edit_message_text("Настройка отменена.")
        else:
            await update.message.reply_text("Настройка отменена.")
        return ConversationHandler.END

# END OF FILE settings_service.py #