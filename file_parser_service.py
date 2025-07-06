# START OF FILE file_parser_service.py #

import os
import logging
import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from config import MAX_FILE_SIZE_MB # Импортируем новую константу

logger = logging.getLogger(__name__)


class FileParserService:
    """
    Сервис для извлечения текста из файлов различных форматов (PDF, DOCX, TXT).
    """

    def extract_text(self, file_path: str) -> str | None:
        """
        Главный метод, который определяет тип файла и вызывает соответствующий парсер.
        Включает валидацию размера файла.
        :param file_path: Путь к файлу.
        :return: Извлеченный текст или None в случае ошибки.
        """
        if not os.path.exists(file_path):
            logger.error(f"Файл не найден по пути: {file_path}")
            return None

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            logger.warning(f"Файл {os.path.basename(file_path)} (Размер: {file_size_mb:.2f} МБ) "
                           f"превышает максимально допустимый размер ({MAX_FILE_SIZE_MB} МБ). Отклонено.")
            return None # <--- Возвращаем None при превышении размера

        _, extension = os.path.splitext(file_path.lower())
        logger.info(f"Начинается парсинг файла: {os.path.basename(file_path)} с расширением {extension}")

        try:
            if extension == '.pdf':
                return self._extract_text_from_pdf(file_path)
            elif extension == '.docx':
                return self._extract_text_from_docx(file_path)
            elif extension == '.txt':
                return self._extract_text_from_txt(file_path)
            else:
                logger.warning(f"Неподдерживаемый формат файла: {extension}")
                return None
        except Exception as e:
            logger.error(f"Произошла ошибка при парсинге файла {file_path}: {e}", exc_info=True)
            return None

    def _extract_text_from_pdf(self, file_path: str) -> str:
        """Извлекает текст из PDF файла."""
        text = []
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
            logger.info(
                f"PDF файл {os.path.basename(file_path)} успешно обработан. Найдено страниц: {len(reader.pages)}.")
            return "\n".join(text)
        except PdfReadError as e:
            logger.error(
                f"Не удалось прочитать PDF файл {file_path}. Возможно, он зашифрован или поврежден. Ошибка: {e}")
            raise

    def _extract_text_from_docx(self, file_path: str) -> str:
        """Извлекает текст из DOCX файла."""
        doc = docx.Document(file_path)
        text = [p.text for p in doc.paragraphs]
        logger.info(f"DOCX файл {os.path.basename(file_path)} успешно обработан.")
        return "\n".join(text)

    def _extract_text_from_txt(self, file_path: str) -> str:
        """Извлекает текст из TXT файла."""
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        logger.info(f"TXT файл {os.path.basename(file_path)} успешно обработан.")
        return text

# END OF FILE file_parser_service.py #