# START OF FILE generative_ai_service.py #

import logging
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any
import asyncio
import os

from config import (
    TEXT_AI_PROVIDER, OPENAI_API_KEY, LOCAL_LLM_PATH, LOCAL_LLM_MODEL_TYPE,
    LLM_MAX_NEW_TOKENS, LLM_CONTEXT_LENGTH, LLM_TEMPERATURE, LLM_GPU_LAYERS
)

try:
    import openai
except ImportError:
    openai = None
    logging.getLogger(__name__).warning("Библиотека 'openai' не установлена.")
try:
    from langchain_community.llms import CTransformers

    CTransformers_installed = True
except ImportError:
    CTransformers = None
    CTransformers_installed = False
    logging.getLogger(__name__).warning("Библиотека 'ctransformers' не установлена.")

logger = logging.getLogger(__name__)


class BaseGenerativeService(ABC):
    @abstractmethod
    async def generate_answer(self, question: str, context: str, history: List[Tuple[str, str]],
                              stop_event: asyncio.Event) -> str: pass

    @abstractmethod
    async def summarize_history(self, history: List[Tuple[str, str]]) -> str: pass


class OpenAIGenerativeService(BaseGenerativeService):
    def __init__(self):
        # ... (код без изменений)
        if not openai: raise ImportError("Библиотека openai не установлена.")
        if not OPENAI_API_KEY: raise ValueError("OPENAI_API_KEY не задан.")
        self.client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.model = "gpt-3.5-turbo"
        logger.info(f"Сервис OpenAI для текста инициализирован с моделью {self.model}.")

    def _format_history_for_llm_messages(self, history: List[Tuple[str, str]]) -> List[Dict[str, str]]:
        messages = []
        for q, a in history:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": a})
        return messages

    async def generate_answer(self, question: str, context: str, history: List[Tuple[str, str]],
                              stop_event: asyncio.Event) -> str:
        # ... (код без изменений)
        system_prompt = "Ты — вежливый и точный AI-ассистент..."
        messages = [{"role": "system", "content": system_prompt}]
        if history: messages.extend(self._format_history_for_llm_messages(history))
        messages.append({"role": "user", "content": f"КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}"})
        try:
            response_stream = await self.client.chat.completions.create(model=self.model, messages=messages,
                                                                        temperature=0.2, max_tokens=1000, stream=True)
            full_answer_content = []
            async for chunk in response_stream:
                if stop_event.is_set(): break
                content = chunk.choices[0].delta.content
                if content: full_answer_content.append(content)
            return "".join(full_answer_content).strip()
        except Exception as e:
            logger.error(f"Ошибка OpenAI API: {e}", exc_info=True)
            return f"Ошибка API: {e}"

    async def summarize_history(self, history: List[Tuple[str, str]]) -> str:
        # ... (код без изменений)
        if not history: return ""
        messages = [{"role": "system", "content": "Суммаризируй диалог."},
                    *self._format_history_for_llm_messages(history)]
        try:
            response = await self.client.chat.completions.create(model=self.model, messages=messages, temperature=0.1,
                                                                 max_tokens=250)
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Ошибка OpenAI API при суммаризации: {e}", exc_info=True)
            return "Ошибка суммаризации."


class LocalGenerativeService(BaseGenerativeService):
    def __init__(self):
        if not CTransformers_installed: raise ImportError("Библиотека 'ctransformers' не установлена.")
        if not LOCAL_LLM_PATH: raise ValueError("LOCAL_LLM_PATH не задан.")
        if not os.path.isfile(LOCAL_LLM_PATH): raise FileNotFoundError(f"Файл модели не найден: {LOCAL_LLM_PATH}")
        logger.info(f"Загрузка локальной GGUF модели: '{LOCAL_LLM_PATH}'...")
        llm_config = {'max_new_tokens': LLM_MAX_NEW_TOKENS, 'context_length': LLM_CONTEXT_LENGTH,
                      'temperature': LLM_TEMPERATURE, 'gpu_layers': LLM_GPU_LAYERS}
        self.llm = CTransformers(model=LOCAL_LLM_PATH, model_type=LOCAL_LLM_MODEL_TYPE, config=llm_config)
        logger.info(f"Локальная GGUF модель ({LOCAL_LLM_MODEL_TYPE}) успешно загружена.")

    # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Адаптация под формат Mistral/Grok ---
    def _build_prompt(self, question: str, context: str, history: List[Tuple[str, str]]) -> str:
        sys_prompt = ("Ты — эксперт-аналитик. Твоя задача — дать точный и краткий ответ на вопрос пользователя, "
                      "ИСКЛЮЧИТЕЛЬНО на основе предоставленного КОНТЕКСТА. "
                      "Если в контексте нет ответа, напиши: 'В предоставленных материалах нет точного ответа на этот вопрос.' "
                      "Отвечай на русском языке.")

        prompt_parts = [f"<|system|>\n{sys_prompt}</s>\n"]

        for q, a in history:
            prompt_parts.append(f"<|user|>\n{q}</s>\n")
            prompt_parts.append(f"<|assistant|>\n{a}</s>\n")

        user_content = f"КОНТЕКСТ ДЛЯ АНАЛИЗА:\n---\n{context}\n---\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}"
        prompt_parts.append(f"<|user|>\n{user_content}</s>\n")
        prompt_parts.append("<|assistant|>")

        full_prompt = "".join(prompt_parts)
        logger.debug(
            f"Сгенерирован промпт для {LOCAL_LLM_MODEL_TYPE} (длина {len(full_prompt)}): {full_prompt[:500]}...")
        return full_prompt

    def _build_summary_prompt(self, history: List[Tuple[str, str]]) -> str:
        sys_prompt = ("Ты — суммаризатор диалогов. Кратко, но информативно, суммаризируй "
                      "представленный диалог, сохраняя ключевые темы. Используй русский язык.")

        prompt_parts = [f"<|system|>\n{sys_prompt}</s>\n"]

        for q, a in history:
            prompt_parts.append(f"<|user|>\n{q}</s>\n")
            prompt_parts.append(f"<|assistant|>\n{a}</s>\n")

        prompt_parts.append(f"<|user|>\nКратко суммаризируй этот диалог.</s>\n<|assistant|>Суммаризация диалога:\n")
        summary_prompt = "".join(prompt_parts)
        logger.debug(
            f"Сгенерирован промпт для суммаризации {LOCAL_LLM_MODEL_TYPE} (длина {len(summary_prompt)}): {summary_prompt[:500]}...")
        return summary_prompt

    async def generate_answer(self, question: str, context: str, history: List[Tuple[str, str]],
                              stop_event: asyncio.Event) -> str:
        prompt = self._build_prompt(question, context, history)
        try:
            if stop_event.is_set(): return "Генерация отменена."
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"Ошибка локальной модели (CTransformers): {e}", exc_info=True)
            return "Ошибка: Не удалось сгенерировать ответ через локальную модель."

    async def summarize_history(self, history: List[Tuple[str, str]]) -> str:
        if not history: return ""
        summary_prompt = self._build_summary_prompt(history)
        try:
            summary = await asyncio.to_thread(self.llm.invoke, summary_prompt)
            return summary.strip()
        except Exception as e:
            logger.error(f"Ошибка локальной модели при суммаризации: {e}", exc_info=True)
            return "Ошибка суммаризации."


class GenerativeAIServiceFactory:
    @staticmethod
    def get_service() -> BaseGenerativeService | None:
        provider = TEXT_AI_PROVIDER.lower()
        try:
            if provider == "openai":
                return OpenAIGenerativeService()
            elif provider == "local":
                return LocalGenerativeService()
            else:
                logger.info("AI-провайдер для текста не указан."); return None
        except Exception as e:
            logger.error(f"Критическая ошибка при инициализации AI сервиса ({provider}): {e}", exc_info=True)
            return None

# END OF FILE generative_ai_service.py #