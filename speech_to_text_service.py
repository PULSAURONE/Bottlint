# START OF FILE speech_to_text_service.py #

import logging
import os
import asyncio
from abc import ABC, abstractmethod
from pydub import AudioSegment

# --- Импорты для локальной модели ---
try:
    from pywhispercpp.model import Model as WhisperCppModel

    WhisperCpp_installed = True
except ImportError:
    WhisperCppModel = None
    WhisperCpp_installed = False
    logging.getLogger(__name__).warning("Библиотека 'pywhispercpp' не установлена. Локальный STT сервис будет недоступен.")


# --- Импорты для OpenAI модели ---
try:
    import openai
except ImportError:
    openai = None
    logging.getLogger(__name__).warning("Библиотека 'openai' не установлена. OpenAI STT сервис будет недоступен.")


# --- Импорты из конфига ---
from config import VOICE_MESSAGES_DIR, LOCAL_WHISPER_PATH, OPENAI_API_KEY, VOICE_AI_PROVIDER

logger = logging.getLogger(__name__)


# --- Базовый класс для всех STT сервисов ---
class BaseSpeechToTextService(ABC):
    @abstractmethod
    async def transcribe_audio(self, oga_file_path: str) -> str | None:
        """
        Основной метод, который преобразует аудиофайл в текст.
        :param oga_file_path: Путь к аудиофайлу в формате .oga.
        :return: Распознанный текст или сообщение об ошибке.
        """
        pass


# --- Сервис для локального распознавания ---
class LocalSpeechToTextService(BaseSpeechToTextService):
    """
    Сервис для преобразования аудиосообщений в текст с использованием локальной модели Whisper.cpp.
    """

    def __init__(self):
        if not WhisperCpp_installed:
            raise ImportError("Библиотека pywhispercpp не установлена. Установите ее: pip install pywhispercpp")
        if not LOCAL_WHISPER_PATH:
            raise ValueError("Путь к локальной модели Whisper (LOCAL_WHISPER_PATH) не указан в .env.")
        if not os.path.exists(LOCAL_WHISPER_PATH):
            raise FileNotFoundError(f"Файл модели Whisper не найден по пути: {LOCAL_WHISPER_PATH}")

        logger.info(f"Загрузка локальной модели Whisper из {LOCAL_WHISPER_PATH} через pywhispercpp...")
        self.model = WhisperCppModel(LOCAL_WHISPER_PATH, n_threads=0)
        logger.info("Локальная модель Whisper успешно загружена.")

    def _convert_and_resample(self, oga_file_path: str) -> str:
        """Конвертирует .oga в .wav, ресемплирует до 16кГц и устанавливает 16-битную глубину."""
        wav_file_path = os.path.join(VOICE_MESSAGES_DIR, f"{os.path.splitext(os.path.basename(oga_file_path))[0]}.wav")
        audio = AudioSegment.from_ogg(oga_file_path)
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        audio.export(wav_file_path, format="wav")
        return wav_file_path

    async def transcribe_audio(self, oga_file_path: str) -> str | None:
        if not os.path.exists(oga_file_path):
            logger.error(f"Файл для транскрибации не найден: {oga_file_path}")
            return "Ошибка: Внутренняя ошибка сервера (файл не найден)."

        wav_file_path = ""
        try:
            wav_file_path = await asyncio.to_thread(self._convert_and_resample, oga_file_path)
            logger.info(f"Локальная транскрибация аудиофайла: {wav_file_path}")

            # ИЗМЕНЕНИЕ: Оборачиваем критический вызов в try-except
            # для перехвата низкоуровневых ошибок типа 0xC0000005
            try:
                result_segments = await asyncio.to_thread(self.model.transcribe, wav_file_path, language='ru')
                recognized_text = "".join(segment.text for segment in result_segments).strip()
            except Exception as e:
                # Этот блок перехватит ошибку, если она произойдет внутри C++ кода
                # и будет обернута в Python исключение.
                logger.critical(f"Критический сбой в pywhispercpp во время транскрибации файла {wav_file_path}: {e}", exc_info=True)
                return "Ошибка: Произошел критический сбой в модуле распознавания речи."

            if recognized_text:
                logger.info(f"Аудио успешно распознано (локально). Текст: '{recognized_text[:50]}...'")
                return recognized_text
            else:
                logger.warning("Локальная модель не смогла распознать текст.")
                return "Не удалось распознать текст."
        except Exception as e:
            logger.error(f"Произошла ошибка во время локальной транскрибации аудио: {e}", exc_info=True)
            return "Ошибка: Не удалось распознать речь из-за внутренней ошибки."
        finally:
            if wav_file_path and os.path.exists(wav_file_path):
                try:
                    os.remove(wav_file_path)
                    logger.info(f"Удален временный WAV-файл: {wav_file_path}")
                except OSError as e:
                    logger.error(f"Ошибка при удалении временного WAV-файла {wav_file_path}: {e}")


# --- Сервис для распознавания через OpenAI API ---
class OpenAISpeechToTextService(BaseSpeechToTextService):
    """
    Сервис для преобразования аудиосообщений в текст с использованием OpenAI Whisper API.
    """

    def __init__(self):
        if not openai:
            raise ImportError("Библиотека openai не установлена. Установите ее: pip install openai")
        if not OPENAI_API_KEY:
            raise ValueError("Ключ OpenAI API (OPENAI_API_KEY) не задан в .env.")

        self.client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.model = "whisper-1"
        logger.info(f"Сервис OpenAI Whisper API инициализирован с моделью {self.model}.")

    async def transcribe_audio(self, oga_file_path: str) -> str | None:
        if not os.path.exists(oga_file_path):
            logger.error(f"Файл для транскрибации не найден: {oga_file_path}")
            return "Ошибка: Внутренняя ошибка сервера (файл не найден)."

        try:
            logger.info(f"Tранскрибация аудио через OpenAI Whisper API: {oga_file_path}")
            with open(oga_file_path, "rb") as audio_file:
                transcript = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    language="ru"
                )
            recognized_text = transcript.text.strip()
            if recognized_text:
                logger.info(f"Аудио успешно распознано (OpenAI). Текст: '{recognized_text[:50]}...'")
                return recognized_text
            else:
                logger.warning("OpenAI API не смог распознать текст.")
                return "Не удалось распознать текст."
        except openai.APIError as e:
            logger.error(f"Ошибка OpenAI API при транскрибации: {e}", exc_info=True)
            return f"Ошибка API: Не удалось распознать речь. Проверьте ключ OpenAI. ({e.code})"
        except Exception as e:
            logger.error(f"Произошла ошибка во время транскрибации через OpenAI: {e}", exc_info=True)
            return "Ошибка: Не удалось распознать речь из-за непредвиденной ошибки."


# --- Фабрика для создания STT сервиса ---
def get_stt_service() -> BaseSpeechToTextService | None:
    """
    Создает и возвращает экземпляр нужного STT-сервиса
    в зависимости от конфигурации VOIhttps://huggingface.co/meta-llama/Llama-3.2-3B-InstructCE_AI_PROVIDER.
    """
    provider = (VOICE_AI_PROVIDER or "").lower()
    logger.info(f"Попытка инициализации ГОЛОСОВОГО AI-провайдера: '{provider}'.")
    try:
        if provider == 'openai':
            return OpenAISpeechToTextService()
        elif provider == 'local':
            return LocalSpeechToTextService()
        else:
            logger.warning("Провайдер для распознавания речи не указан или некорректен.")
            return None
    except Exception as e:
        logger.error(f"Критическая ошибка при инициализации STT сервиса ({provider}): {e}", exc_info=True)
        return None

# END OF FILE speech_to_text_service.py #