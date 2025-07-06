# START OF FILE config.py #

import os
import logging
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Путь к папке data внутри проекта
DATA_DIR = os.path.join(BASE_DIR, 'data')

# Загружаем переменные из .env файла
load_dotenv()

# --- Основные настройки бота ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN не задан в .env. Бот не сможет запуститься.")

# --- Настройки AI-провайдеров ---
TEXT_AI_PROVIDER = os.getenv('TEXT_AI_PROVIDER', '').lower()
VOICE_AI_PROVIDER = os.getenv('VOICE_AI_PROVIDER', '').lower()

# --- Ключи API ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
HUGGINGFACE_API_TOKEN = os.getenv('HUGGINGFACE_API_TOKEN')

# --- Настройки для локальных моделей ---
LOCAL_LLM_PATH = os.getenv('LOCAL_LLM_PATH', os.path.join(DATA_DIR, 'models', 'mistral-7b-grok-Q4_K_M.gguf'))
LOCAL_WHISPER_PATH = os.getenv('LOCAL_WHISPER_PATH', os.path.join(DATA_DIR, 'models', 'ggml-small-q8_0.bin'))

# --- Гибкие настройки для локальной LLM ---
LOCAL_LLM_MODEL_TYPE = os.getenv('LOCAL_LLM_MODEL_TYPE', 'mistral')
LLM_MAX_NEW_TOKENS = int(os.getenv('LLM_MAX_NEW_TOKENS', 1536))
LLM_CONTEXT_LENGTH = int(os.getenv('LLM_CONTEXT_LENGTH', 4096))
LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', 0.3))
LLM_GPU_LAYERS = int(os.getenv('LLM_GPU_LAYERS', 0))

# --- НОВАЯ НАСТРОЙКА: Режим поиска ---
# Возможные значения: "kb_then_web", "kb_only", "web_only"
SEARCH_MODE = os.getenv('SEARCH_MODE', 'kb_then_web')
if SEARCH_MODE not in ["kb_then_web", "kb_only", "web_only"]:
    logger.warning(f"Некорректный SEARCH_MODE: {SEARCH_MODE}. Установлено значение по умолчанию 'kb_then_web'.")
    SEARCH_MODE = 'kb_then_web'
# ----------------------------------------

if TEXT_AI_PROVIDER == 'local':
    if not LOCAL_LLM_PATH:
        logger.error("LOCAL_LLM_PATH не задан в .env, но TEXT_AI_PROVIDER установлен в 'local'.")
    elif not str(LOCAL_LLM_PATH).lower().endswith(".gguf"):
        logger.error(f"LOCAL_LLM_PATH '{LOCAL_LLM_PATH}' должен указывать на файл с расширением .gguf.")
    elif not os.path.isfile(LOCAL_LLM_PATH):
        logger.error(f"Файл GGUF модели не найден по пути: '{LOCAL_LLM_PATH}'. Скачайте его с помощью `download_model.py`.")

if VOICE_AI_PROVIDER == 'local':
    if not LOCAL_WHISPER_PATH:
        logger.error("LOCAL_WHISPER_PATH не задан в .env, но VOICE_AI_PROVIDER установлен в 'local'.")
    elif not os.path.isfile(LOCAL_WHISPER_PATH):
        logger.error(f"Файл модели Whisper не найден по пути: '{LOCAL_WHISPER_PATH}'.")

# --- Настройки для Google Custom Search ---
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
GOOGLE_API_KEY_SEARCH = os.getenv('GOOGLE_API_KEY_SEARCH')

# --- Управление доступом ---
_allowed_ids_str = os.getenv('ALLOWED_TELEGRAM_IDS', '')
ALLOWED_TELEGRAM_IDS = []
if _allowed_ids_str.strip():
    try:
        ALLOWED_TELEGRAM_IDS = [int(id.strip()) for id in _allowed_ids_str.split(',') if id.strip().isdigit()]
        if ALLOWED_TELEGRAM_IDS:
             logger.info(f"Доступ ограничен для следующих ID: {ALLOWED_TELEGRAM_IDS}")
    except (ValueError, TypeError):
        logger.warning(f"Не удалось распарсить ALLOWED_TELEGRAM_IDS: '{_allowed_ids_str}'.")
else:
    logger.info("Доступ к боту открыт для всех пользователей (ALLOWED_TELEGRAM_IDS не задан).")

# --- Настройки логирования ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_FILE_PATH = os.path.join(DATA_DIR, 'bot.log')

# --- Настройки диалогов ---
CONVERSATION_TIMEOUT = int(os.getenv('CONVERSATION_TIMEOUT', 600))
CONVERSATION_WARNING_TIMEOUT_SECONDS = int(os.getenv('CONVERSATION_WARNING_TIMEOUT_SECONDS', 300))
CONVERSATION_HISTORY_DEPTH = int(os.getenv('CONVERSATION_HISTORY_DEPTH', 10))
LLM_HISTORY_SUMMARIZE_THRESHOLD = int(os.getenv('LLM_HISTORY_SUMMARIZE_THRESHOLD', 20))

# --- Папки для хранения данных ---
DOWNLOADS_DIR = os.path.join(DATA_DIR, 'downloads')
VOICE_MESSAGES_DIR = os.path.join(DATA_DIR, 'voice_messages')

# --- Настройки для Google Drive Service ---
GOOGLE_DRIVE_CREDENTIALS_PATH = os.path.join(DATA_DIR, 'client_secret.json')
GOOGLE_DRIVE_TOKEN_PATH = os.path.join(DATA_DIR, 'token.json')
GOOGLE_API_SCOPES = ['https://www.googleapis.com/auth/drive.readonly', 'https://www.googleapis.com/auth/drive.file']

# --- Настройки для Knowledge Base Service ---
EMBEDDING_MODEL_NAME = os.getenv('EMBEDDING_MODEL_NAME', 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
VECTOR_STORE_PATH = os.path.join(DATA_DIR, 'faiss_index')
SOURCE_MAP_PATH = os.path.join(DATA_DIR, 'source_map.json')

# --- Валидация файлов ---
MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 50))

# --- ГЛАВНОЕ МЕНЮ ---
MAIN_KEYBOARD_MARKUP = ReplyKeyboardMarkup(
    [
        ["📚 Загрузить файл с Google Drive", "📥 Загрузить файл с ПК/телефона"],
        ["🧠 Задать вопрос", "🔄 Сбросить диалог"],
        ["📂 Управление Базой Знаний", "⚙️ Настройки и Статус"]
    ],
    resize_keyboard=True
)

# --- Создание директорий ---
for directory in [DATA_DIR, DOWNLOADS_DIR, VOICE_MESSAGES_DIR]:
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
            logger.info(f"Создана директория: {directory}")
        except OSError as e:
            logger.error(f"Не удалось создать директорию {directory}: {e}")

# END OF FILE config.py #