# START OF FILE tests/test_file_parser_service.py #

import os
import pytest
from file_parser_service import FileParserService


# Фикстура - это функция, которая подготавливает данные для тестов.
# Pytest автоматически найдет ее и передаст в тесты, которые ее запрашивают.
@pytest.fixture
def parser_service():
    """Возвращает экземпляр FileParserService для каждого теста."""
    return FileParserService()


# Тестовая функция должна начинаться с "test_"
def test_extract_text_from_txt(parser_service, tmp_path):
    """
    Проверяет, что сервис корректно извлекает текст из .txt файла.

    :param parser_service: экземпляр сервиса, созданный фикстурой
    :param tmp_path: встроенная фикстура pytest, которая создает временную папку
    """
    # 1. Подготовка (Arrange)
    test_content = "Привет, мир! Это тестовый файл.\nВторая строка."
    # Создаем временный файл внутри временной папки
    file_path = tmp_path / "test_document.txt"
    file_path.write_text(test_content, encoding='utf-8')

    # 2. Действие (Act)
    extracted_text = parser_service.extract_text(str(file_path))

    # 3. Проверка (Assert)
    assert extracted_text is not None
    assert extracted_text == test_content


def test_extract_text_from_non_existent_file(parser_service):
    """
    Проверяет, что сервис возвращает None для несуществующего файла.
    """
    # 1. Подготовка
    non_existent_path = "path/to/non/existent/file.txt"

    # 2. Действие
    result = parser_service.extract_text(non_existent_path)

    # 3. Проверка
    assert result is None


def test_unsupported_file_type(parser_service, tmp_path):
    """
    Проверяет, что сервис возвращает None для неподдерживаемого типа файла.
    """
    # 1. Подготовка
    file_path = tmp_path / "document.xyz"
    file_path.write_text("some data")

    # 2. Действие
    result = parser_service.extract_text(str(file_path))

    # 3. Проверка
    assert result is None

# END OF FILE tests/test_file_parser_service.py #