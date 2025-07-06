# START OF FILE handlers.py #

import logging
import os
import asyncio
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from telegram.error import BadRequest
import mimetypes

from config import (
    DOWNLOADS_DIR, VOICE_MESSAGES_DIR, CONVERSATION_HISTORY_DEPTH, LLM_HISTORY_SUMMARIZE_THRESHOLD,
    ALLOWED_TELEGRAM_IDS, LOG_FILE_PATH, MAIN_KEYBOARD_MARKUP, GOOGLE_DRIVE_TOKEN_PATH, MAX_FILE_SIZE_MB, SEARCH_MODE
)

from google_drive_service import GoogleDriveService
from file_parser_service import FileParserService
from knowledge_base_service import KnowledgeBaseService
import generative_ai_service
from generative_ai_service import GenerativeAIServiceFactory
import speech_to_text_service
from speech_to_text_service import get_stt_service
from external_knowledge_service import ExternalKnowledgeService
from status_service import StatusService
from settings_service import SettingsService

from decorators import authorized_only

logger = logging.getLogger(__name__)

# Глобальные сервисы
drive_service: GoogleDriveService | None = None
parser_service: FileParserService | None = None
kb_service: KnowledgeBaseService | None = None
ai_service: generative_ai_service.BaseGenerativeService | None = None
stt_service: speech_to_text_service.BaseSpeechToTextService | None = None
ext_knowledge_service: ExternalKnowledgeService | None = None
status_service: StatusService | None = None
settings_service: SettingsService | None = None

# Состояния для ConversationHandler
(RESET_CHAT_CONFIRM, AWAITING_AUTH_CODE) = range(100, 102)

active_llm_tasks: dict[int, asyncio.Task] = {}
llm_stop_events: dict[int, asyncio.Event] = {}

SUPPORTED_MIME_TYPES = {'application/pdf': '.pdf',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                        'text/plain': '.txt'}


def set_global_services(ds, ps, kbs, ais, stts, eks, sts, sers):
    global drive_service, parser_service, kb_service, ai_service, stt_service, ext_knowledge_service, status_service, settings_service
    drive_service, parser_service, kb_service, ai_service, stt_service, ext_knowledge_service, status_service, settings_service = ds, ps, kbs, ais, stts, eks, sts, sers


async def animate_thinking_message(context: CallbackContext, message_to_edit, stop_event: asyncio.Event,
                                   initial_text: str):
    states = [("Поиск информации...", "🔍"), ("Анализ данных...", "📈"), ("Формирование ответа...", "✍️"),
              ("Генерация...", "🧠")]
    i = 0
    message_id, chat_id = message_to_edit.message_id, message_to_edit.chat_id
    try:
        await context.bot.edit_message_text(text=f"⏳ {initial_text}", chat_id=chat_id, message_id=message_id)
        while not stop_event.is_set():
            try:
                animated_text = f"{states[i % len(states)][1]} {states[i % len(states)][0]}..."
                await context.bot.edit_message_text(text=animated_text, chat_id=chat_id, message_id=message_id,
                                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                                        "🛑 Остановить", callback_data="stop_llm_generation")]]))
            except BadRequest as e:
                if "Message is not modified" not in str(e): logger.warning(f"Ошибка анимации: {e}"); break
            except Exception as e:
                logger.error(f"Непредвиденная ошибка анимации: {e}", exc_info=True); break
            i += 1
            await asyncio.sleep(1.2)
    except asyncio.CancelledError:
        logger.info(f"Задача анимации для chat_id {chat_id} отменена.")
    finally:
        stop_event.set()
        if chat_id in active_llm_tasks:
            try:
                await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            except BadRequest:
                pass


async def _process_question_logic(question: str, update: Update, context: CallbackContext):
    chat_id, message = update.effective_chat.id, update.effective_message
    if chat_id in active_llm_tasks and not active_llm_tasks[chat_id].done():
        llm_stop_events[chat_id].set()
        try:
            await asyncio.wait_for(active_llm_tasks[chat_id], timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        if chat_id in active_llm_tasks: del active_llm_tasks[chat_id]
        if chat_id in llm_stop_events: del llm_stop_events[chat_id]
        await message.reply_text("Предыдущий запрос отменен. Начинаю новый.")
    stop_event = asyncio.Event()
    llm_stop_events[chat_id] = stop_event
    thinking_message = await message.reply_text("⏳ Получил ваш вопрос...")
    animation_task = asyncio.create_task(
        animate_thinking_message(context, thinking_message, stop_event, "Подготовка..."))
    active_llm_tasks[chat_id] = animation_task
    try:
        history = context.user_data.setdefault('conversation_history', [])
        if len(history) >= LLM_HISTORY_SUMMARIZE_THRESHOLD and ai_service:
            summarized_history = await ai_service.summarize_history(history)
            if summarized_history and not summarized_history.startswith("Ошибка"):
                context.user_data['conversation_history'] = [(summarized_history, "")]
                history = context.user_data['conversation_history']

        context_text, sources = "", []

        if SEARCH_MODE in ['kb_then_web', 'kb_only'] and kb_service and kb_service.vector_store:
            await thinking_message.edit_text("🔍 Ищу в базе знаний...")
            search_results = await asyncio.to_thread(kb_service.search, question, k=4)
            if search_results:
                context_text = "\n\n".join([doc.page_content for doc in search_results])
                sources = sorted(list(set([doc.metadata.get('source', 'База знаний') for doc in search_results])))

        if not context_text and SEARCH_MODE in ['kb_then_web', 'web_only'] and ext_knowledge_service:
            await thinking_message.edit_text("🌐 Ищу в интернете...")
            web_context, web_source = await asyncio.to_thread(ext_knowledge_service.search, question)
            if web_context:
                context_text, sources = web_context, [web_source]

        if not context_text:
            await thinking_message.edit_text(
                "❌ К сожалению, я не смог найти релевантную информацию ни в базе знаний, ни в интернете.",
                reply_markup=None)
            return

        if not ai_service:
            await thinking_message.edit_text(
                f"⚠️ Генератор ответов (LLM) не работает. Найденная информация:\n\n\"{context_text[:1000]}...\"",
                reply_markup=None)
            return

        await thinking_message.edit_text("🧠 Генерирую ответ...")
        generated_answer = await ai_service.generate_answer(question, context_text, history, stop_event)

        if stop_event.is_set(): raise asyncio.CancelledError("Генерация отменена пользователем.")
        if generated_answer.startswith("Ошибка:"):
            await thinking_message.edit_text(f"❌ {generated_answer}", reply_markup=None)
            return

        history.append((question, generated_answer))
        context.user_data['conversation_history'] = history[-CONVERSATION_HISTORY_DEPTH:]
        source_display = "\n\n<i>Источники:</i>\n" + "\n".join(
            [f"• <code>{s}</code>" for s in sources]) if sources else ""
        await thinking_message.edit_text(f"{generated_answer}{source_display}", parse_mode='HTML', reply_markup=None)

    except asyncio.CancelledError:
        await thinking_message.edit_text("✅ Генерация ответа остановлена.", reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка в процессе обработки вопроса для chat_id {chat_id}: {e}", exc_info=True)
        await thinking_message.edit_text(f"❌ Произошла ошибка при обработке вашего запроса: {e}", reply_markup=None)
    finally:
        stop_event.set()
        if chat_id in active_llm_tasks:
            if not active_llm_tasks[chat_id].done(): active_llm_tasks[chat_id].cancel()
            del active_llm_tasks[chat_id]
        if chat_id in llm_stop_events: del llm_stop_events[chat_id]


@authorized_only
async def stop_llm_generation(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat_id
    await query.answer("Останавливаю генерацию...", show_alert=False)
    if chat_id in llm_stop_events:
        llm_stop_events[chat_id].set()
    else:
        await query.message.edit_text("Нет активной генерации для остановки.", reply_markup=None)


@authorized_only
async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    await update.message.reply_html(f"Привет, {user.mention_html()}! Я ваш AI-ассистент.",
                                    reply_markup=MAIN_KEYBOARD_MARKUP)


@authorized_only
async def handle_telegram_document_upload(update: Update, context: CallbackContext):
    document = update.message.document
    if not all([parser_service, kb_service]):
        await update.message.reply_text("❌ Сервис парсинга или базы знаний не инициализирован. Проверьте логи.")
        return

    file_name = document.file_name
    _, file_extension = os.path.splitext(file_name.lower())
    supported_extensions = ['.pdf', '.docx', '.txt', '.md', '.pptx', '.html']
    if file_extension not in supported_extensions:
        await update.message.reply_text(f"❌ Формат файла '{file_extension}' не поддерживается.")
        return

    thinking_message = await update.message.reply_text(f"⏳ Получил файл '{file_name}'. Начинаю обработку...")
    download_path = os.path.join(DOWNLOADS_DIR, f"{uuid4()}_{file_name}")

    try:
        telegram_file = await context.bot.get_file(document.file_id)
        await telegram_file.download_to_drive(download_path)

        file_size_mb = os.path.getsize(download_path) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            await thinking_message.edit_text(
                f"❌ Файл слишком большой ({file_size_mb:.2f} МБ). Максимальный размер: {MAX_FILE_SIZE_MB} МБ.")
            return

        await thinking_message.edit_text(f"⏳ Извлекаю текст из '{file_name}' (это может занять время)...")
        extracted_text = await asyncio.to_thread(parser_service.extract_text, download_path)

        if not extracted_text:
            raise Exception(
                "Не удалось извлечь текст. Файл может быть пустым, содержать только изображения (сканы) или иметь защищенный/поврежденный формат.")

        await thinking_message.edit_text(f"⏳ Индексирую знания из '{file_name}'...")
        source_id = f"local_{uuid4()}"
        await asyncio.to_thread(kb_service.add_text, extracted_text,
                                metadata={"source": file_name, "source_id": source_id})

        await thinking_message.edit_text(f"✅ Файл <b>{file_name}</b> успешно проиндексирован и добавлен в базу знаний!",
                                         parse_mode='HTML')

    except ValueError as ve:
        await thinking_message.edit_text(f"❌ {ve}")
    except Exception as e:
        logger.error(f"Ошибка при прямой обработке файла '{file_name}': {e}", exc_info=True)
        await thinking_message.edit_text(f"❌ Произошла ошибка при обработке файла:\n\n<pre>{e}</pre>",
                                         parse_mode='HTML')
    finally:
        if os.path.exists(download_path):
            try:
                os.remove(download_path)
            except OSError as e:
                logger.error(f"Ошибка при удалении временного файла {download_path}: {e}")


@authorized_only
async def handle_text_or_voice(update: Update, context: CallbackContext) -> None:
    user, question, oga_file_path = update.effective_user, "", None
    try:
        if update.message.voice:
            if not stt_service: await update.message.reply_text("❌ Голосовой ввод не настроен."); return
            thinking_message = await update.message.reply_text("🎤 Распознаю...")
            oga_file_path = os.path.join(VOICE_MESSAGES_DIR, f"{uuid4()}.oga")
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            await voice_file.download_to_drive(oga_file_path)
            question = await stt_service.transcribe_audio(oga_file_path)
            if not question or question.startswith("Ошибка:"): await thinking_message.edit_text(
                f"❌ {question or 'Не удалось распознать речь.'}"); return
            await thinking_message.delete()
            await update.message.reply_text(f"<i>Ваш вопрос: «{question}»</i>", parse_mode='HTML')
        else:
            question = update.message.text
            if question == "🧠 Задать вопрос": await update.message.reply_text(
                "Просто напишите или надиктуйте ваш вопрос."); return
        if question: await _process_question_logic(question, update, context)
    finally:
        if oga_file_path and os.path.exists(oga_file_path):
            try:
                os.remove(oga_file_path)
            except OSError:
                pass


@authorized_only
async def reset_chat(update: Update, context: CallbackContext) -> int:
    keyboard = [[InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_chat_confirm"),
                 InlineKeyboardButton("❌ Нет, отмена", callback_data="reset_chat_cancel")]]
    await update.message.reply_text("Вы уверены, что хотите сбросить контекст диалога?",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return RESET_CHAT_CONFIRM


@authorized_only
async def reset_chat_confirm(update: Update, context: CallbackContext) -> int:
    query = update.callback_query;
    await query.answer()
    context.user_data.pop('conversation_history', None)
    await query.edit_message_text("✅ Контекст диалога сброшен.")
    return ConversationHandler.END


@authorized_only
async def reset_chat_cancel(update: Update, context: CallbackContext) -> int:
    query = update.callback_query;
    await query.answer()
    await query.edit_message_text("❌ Сброс диалога отменен.")
    return ConversationHandler.END


@authorized_only
async def upload_file_start(update: Update, context: CallbackContext) -> None:
    message = update.message
    if not drive_service or not drive_service.is_authenticated:
        await message.reply_text("❌ Сначала нужно подключить Google Drive: /connect_google_drive",
                                 reply_markup=MAIN_KEYBOARD_MARKUP)
        return
    await message.reply_text("⏳ Получаю список файлов с вашего Google Drive...")
    await list_drive_files_paginated(update, context, page=0)


@authorized_only
async def knowledge_base_menu(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton("📂 Показать/Удалить файлы", callback_data="kb_list_files_0")],
                [InlineKeyboardButton("🗑️ Очистить всю базу знаний", callback_data="kb_clear_all_confirm")]]

    # Если вызвано через команду, а не колбэк
    target_message = update.message if update.message else update.callback_query.message
    await target_message.reply_text("📚 Здесь вы можете управлять базой знаний:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))


async def list_indexed_files(update: Update, context: CallbackContext, page: int = 0):
    query = update.callback_query
    if query: await query.answer()

    if not kb_service:
        await query.edit_message_text("❌ Сервис базы знаний не инициализирован.")
        return

    indexed_sources = await asyncio.to_thread(kb_service.get_indexed_sources)

    if not indexed_sources:
        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="kb_menu_back")]]
        await query.edit_message_text("ℹ️ Ваша база знаний пуста. Загрузите файлы, чтобы начать.",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return

    items_per_page = 5
    start_index, end_index = page * items_per_page, start_index + items_per_page
    paginated_sources = indexed_sources[start_index:end_index]

    keyboard = []
    for source in paginated_sources:
        file_name = source['source']
        display_name = (file_name[:40] + '...') if len(file_name) > 43 else file_name
        keyboard.append([InlineKeyboardButton(f"📄 {display_name}", callback_data=f"kb_noop"),
                         InlineKeyboardButton("🗑️ Удалить", callback_data=f"kb_delete_{source['source_id']}_{page}")])

    pg_btns = []
    if page > 0: pg_btns.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"kb_list_files_{page - 1}"))
    if end_index < len(indexed_sources): pg_btns.append(
        InlineKeyboardButton("Вперед ➡️", callback_data=f"kb_list_files_{page + 1}"))
    if pg_btns: keyboard.append(pg_btns)

    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="kb_menu_back")])

    await query.edit_message_text(f"🗂️ Проиндексированные файлы (Страница {page + 1}):",
                                  reply_markup=InlineKeyboardMarkup(keyboard))


@authorized_only
async def handle_kb_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    data = query.data

    if data.startswith("kb_list_files_"):
        await query.answer()
        page = int(data.split('_')[-1])
        await list_indexed_files(update, context, page=page)
        return

    if data.startswith("kb_delete_"):
        await query.answer()
        parts = data.split('_')
        source_id, page_to_return = parts[2], int(parts[3])
        if kb_service and await asyncio.to_thread(kb_service.delete_by_source_id, source_id):
            await query.edit_message_text("✅ Файл успешно удален из базы знаний. Обновляю список...")
            await list_indexed_files(update, context, page=page_to_return)
        else:
            await query.answer("❌ Не удалось удалить файл из базы знаний.", show_alert=True)
        return

    if data == "kb_clear_all_confirm":
        await query.answer()
        await query.edit_message_text("⚠️ Вы уверены, что хотите полностью удалить все знания из базы? Это необратимо.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да, очистить",
                                                                                               callback_data="kb_clear_all_execute"),
                                                                          InlineKeyboardButton("⬅️ Отмена",
                                                                                               callback_data="kb_list_files_0")]]))
        return

    if data == "kb_clear_all_execute":
        await query.answer()
        if kb_service:
            await asyncio.to_thread(kb_service.clear_all)
            await query.edit_message_text("✅ База знаний полностью очищена.")
        else:
            await query.edit_message_text("❌ Сервис базы знаний не инициализирован.")

        await query.message.delete()
        await knowledge_base_menu(query.message, context)
        return

    if data == "kb_menu_back":
        await query.answer()
        await query.message.delete()
        await knowledge_base_menu(update.effective_message, context)
        return

    if data == "kb_noop":
        await query.answer("Это просто название файла. Используйте кнопку 'Удалить' для действия.")
        return

    if data.startswith("cancel_upload") or data.startswith("gdrive_"):
        await query.answer()
        if data == "cancel_upload":
            try:
                await query.message.delete()
            except BadRequest:
                pass
            await query.message.reply_text("Загрузка отменена.", reply_markup=MAIN_KEYBOARD_MARKUP)
        elif data.startswith("gdrive_page_"):
            await list_drive_files_paginated(update, context, page=int(data.split('_')[-1]), from_callback=True)
        elif data.startswith("gdrive_select_"):
            await handle_file_selection(update, context)


async def list_drive_files_paginated(update: Update, context: CallbackContext, page: int = 0,
                                     from_callback: bool = False):
    target_message = update.message if not from_callback else update.callback_query.message
    if not from_callback and update.message and update.message.text:
        try:
            await update.message.delete()
        except BadRequest:
            pass
    all_files = await drive_service.list_files(page_size=1000)
    if not all_files:
        text, reply_markup = "📂 На вашем Google Drive не найдено файлов.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_upload")]])
        if from_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await target_message.reply_text(text, reply_markup=reply_markup)
        return
    processable_files = [f for f in all_files if f.get('mimeType') in SUPPORTED_MIME_TYPES]
    if not processable_files:
        text, reply_markup = "📂 На GDrive не найдено поддерживаемых документов (PDF, DOCX, TXT).", InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_upload")]])
        if from_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await target_message.reply_text(text, reply_markup=reply_markup)
        return
    items_per_page = 5
    start_index, end_index = page * items_per_page, (page + 1) * items_per_page
    paginated_files = processable_files[start_index:end_index]
    keyboard = [[InlineKeyboardButton(f"📄 {f.get('name', 'Без имени')}", callback_data=f"gdrive_select_{f.get('id')}")]
                for f in paginated_files]
    pg_btns = []
    if page > 0: pg_btns.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"gdrive_page_{page - 1}"))
    if end_index < len(processable_files): pg_btns.append(
        InlineKeyboardButton("Вперед ➡️", callback_data=f"gdrive_page_{page + 1}"))
    if pg_btns: keyboard.append(pg_btns)
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_upload")])
    text = 'Выберите файл для добавления в базу знаний:'
    if from_callback:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await target_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@authorized_only
async def handle_file_selection(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    file_id = query.data.split('_')[-1]
    if not all([drive_service, parser_service, kb_service]): await query.edit_message_text(
        "❌ Один из ключевых сервисов не инициализирован."); return
    download_path = ""
    try:
        if not drive_service or not drive_service.service: await query.edit_message_text(
            "❌ Сервис Google Drive не инициализирован."); return
        file_info = await asyncio.to_thread(
            lambda: drive_service.service.files().get(fileId=file_id, fields='name, size').execute())
        file_name, file_size = file_info.get('name', file_id), int(file_info.get('size', 0)) / (1024 * 1024)
        if file_size > MAX_FILE_SIZE_MB:
            await query.edit_message_text(f"❌ Файл <b>{file_name}</b> ({file_size:.2f} МБ) > {MAX_FILE_SIZE_MB} МБ.",
                                          parse_mode='HTML', reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Вернуться", callback_data=f"gdrive_page_0")]]))
            return
        await query.edit_message_text(f"⏳ Скачиваю и парсю <b>{file_name}</b>...", parse_mode='HTML')
        download_path = os.path.join(DOWNLOADS_DIR, f"{uuid4()}_{file_name}")
        if not await drive_service.download_file(file_id, download_path): raise Exception("Не удалось скачать файл.")
        extracted_text = await asyncio.to_thread(parser_service.extract_text, download_path)
        if not extracted_text:
            await query.edit_message_text(f"❌ Не удалось извлечь текст из <b>{file_name}</b>.", parse_mode='HTML',
                                          reply_markup=InlineKeyboardMarkup(
                                              [[InlineKeyboardButton("🔙 Вернуться", callback_data=f"gdrive_page_0")]]))
            return
        await query.edit_message_text(f"⏳ Индексирую знания из <b>{file_name}</b>...", parse_mode='HTML')
        await asyncio.to_thread(kb_service.add_text, extracted_text,
                                metadata={"source": file_name, "source_id": file_id})
        await query.edit_message_text(text=f"✅ Знания из файла <b>{file_name}</b> успешно добавлены.",
                                      reply_markup=InlineKeyboardMarkup(
                                          [[InlineKeyboardButton("🔙 Вернуться", callback_data="cancel_upload")]]))
    except Exception as e:
        logger.error(f"Ошибка при обработке файла {file_id}: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Не удалось обработать файл. Ошибка: {e}", parse_mode='HTML')
    finally:
        if download_path and os.path.exists(download_path):
            try:
                os.remove(download_path)
            except OSError:
                pass


@authorized_only
async def settings_and_status_command(update: Update, context: CallbackContext) -> None:
    if not status_service: await update.message.reply_text("❌ Сервис статуса не инициализирован."); return
    await status_service.get_status(update, context)


@authorized_only
async def logs_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if ALLOWED_TELEGRAM_IDS and user.id not in ALLOWED_TELEGRAM_IDS: await update.message.reply_text(
        "❌ Доступ ограничен."); return
    if not os.path.exists(LOG_FILE_PATH): await update.message.reply_text(f"❌ Файл логов не найден."); return
    try:
        with open(LOG_FILE_PATH, 'rb') as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(f.tell() - 4000, 0), os.SEEK_SET)
            log_text = f.read().decode('utf-8', errors='ignore')
        if not log_text.strip():
            await update.message.reply_text("📜 Лог пуст.")
        else:
            await update.message.reply_html(f"📜 <b>Последние строки из лога:</b>\n\n<code>{log_text}</code>")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось прочитать логи: {e}")


@authorized_only
async def connect_google_drive(update: Update, context: CallbackContext) -> int:
    global drive_service
    if not drive_service: await update.message.reply_html(
        "❌ Сервис Google Drive не доступен."); return ConversationHandler.END
    if drive_service.is_authenticated: await update.message.reply_text(
        "✅ Google Drive уже подключен."); return ConversationHandler.END
    auth_url = drive_service.get_auth_url()
    if auth_url:
        await update.message.reply_html(
            f'<b>Шаг 1: Авторизация</b>\n<a href="{auth_url}">Нажмите здесь</a>\n\n<b>Шаг 2:</b> Скопируйте код и отправьте его мне.',
            disable_web_page_preview=True)
        await update.message.reply_text("Введите полученный код авторизации от Google:")
        return AWAITING_AUTH_CODE
    else:
        await update.message.reply_html(
            "❌ Не удалось начать процесс подключения. Убедитесь, что `client_secret.json` находится в папке `data`.")
        return ConversationHandler.END


@authorized_only
async def handle_auth_code(update: Update, context: CallbackContext) -> int:
    if not drive_service: await update.message.reply_html(
        "❌ Сервис Google Drive не доступен."); return ConversationHandler.END
    auth_code = update.message.text.strip()
    if await asyncio.to_thread(drive_service.complete_authentication, auth_code):
        await update.message.reply_text("✅ Аккаунт Google Drive успешно подключен!", reply_markup=MAIN_KEYBOARD_MARKUP)
    else:
        await update.message.reply_text(
            "❌ Ошибка подключения. Код неверный или истек. Попробуйте /connect_google_drive еще раз.")
    return ConversationHandler.END


@authorized_only
async def cancel_google_drive_auth(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Авторизация Google Drive отменена.", reply_markup=MAIN_KEYBOARD_MARKUP)
    return ConversationHandler.END

# END OF FILE handlers.py #