# START OF FILE download_model.py #

import os
from huggingface_hub import hf_hub_download

# --- ИЗМЕНЕНИЕ: Настраиваем скачивание модели Mistral-7B-Grok ---
llm_repo_id = "tensorblock/mistral-7b-grok-GGUF"
# Q4_K_M - рекомендованный баланс размера и качества
llm_filename = "mistral-7b-grok-Q4_K_M.gguf"
# Убедитесь, что этот путь соответствует вашему окружению
local_llm_destination_dir = os.path.join("C:/Users/dp/PycharmProjects/Bottlint/data/models/")
local_llm_path = os.path.join(local_llm_destination_dir, llm_filename)

print(f"Попытка скачать LLM модель '{llm_filename}' из репозитория '{llm_repo_id}'...")
print("Это стабильная модель Mistral-7B, рекомендованная для использования.")
try:
    os.makedirs(local_llm_destination_dir, exist_ok=True)
    hf_hub_download(
        repo_id=llm_repo_id,
        filename=llm_filename,
        local_dir=local_llm_destination_dir,
        local_dir_use_symlinks=False,
        resume_download=True
    )
    print(f"\nLLM модель успешно скачана в: {local_llm_path}")
except Exception as e:
    print(f"\nОШИБКА при скачивании LLM модели: {e}")
# ----------------------------------------------------

# --- Блок для Whisper (остается без изменений) ---
whisper_repo_id = "ggerganov/whisper.cpp"
whisper_model_filename = "ggml-small-q8_0.bin"
local_whisper_destination_dir = os.path.join("C:/Users/dp/PycharmProjects/Bottlint/data/models/")
local_whisper_path = os.path.join(local_whisper_destination_dir, whisper_model_filename)


print(f"\nПопытка скачать модель Whisper '{whisper_model_filename}' из '{whisper_repo_id}'...")
try:
    os.makedirs(local_whisper_destination_dir, exist_ok=True)
    hf_hub_download(
        repo_id=whisper_repo_id,
        filename=whisper_model_filename,
        local_dir=local_whisper_destination_dir,
        local_dir_use_symlinks=False,
        resume_download=True
    )
    print(f"\nМодель Whisper успешно скачана в: {local_whisper_path}")
except Exception as e:
    print(f"\nОШИБКА при скачивании модели Whisper: {e}")


# END OF FILE download_model.py #