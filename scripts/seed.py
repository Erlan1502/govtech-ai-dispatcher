#!/usr/bin/env python3
"""
GovTech AI Dispatcher — Data Seeding & Embedding Generator
---------------------------------------------------------
Скрипт первоначальной векторизации базы знаний (регламентов госуслуг).
Находит записи без векторов в PostgreSQL, запрашивает эмбеддинги у Ollama (bge-m3)
и сохраняет их в pgvector.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
import requests

# Обеспечиваем корректный вывод UTF-8 в консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# Цветовая подсветка для терминала (ANSI)
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def load_env(env_path: Path) -> Dict[str, str]:
    """Простой парсер .env без обязательной внешней зависимости python-dotenv."""
    env_vars: Dict[str, str] = {}
    if not env_path.exists():
        return env_vars

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            env_vars[key.strip()] = val.strip().strip("'\"")
    return env_vars


class Config:
    """Конфигурация подключения к сервисам."""
    def __init__(self, project_root: Path):
        env = load_env(project_root / ".env")

        # Настройки базы данных
        self.db_host = os.getenv("POSTGRES_HOST", env.get("POSTGRES_HOST", "localhost"))
        self.db_port = int(os.getenv("POSTGRES_PORT", env.get("POSTGRES_PORT", "5432")))
        self.db_name = os.getenv("POSTGRES_DB", env.get("POSTGRES_DB", "govtech_db"))
        self.db_user = os.getenv("POSTGRES_USER", env.get("POSTGRES_USER", "postgres"))
        self.db_password = os.getenv("POSTGRES_PASSWORD", env.get("POSTGRES_PASSWORD", "postgres_password"))

        # Настройки Ollama (если запуск с хоста, ollama:11434 заменяется на localhost:11434)
        raw_ollama = os.getenv("OLLAMA_BASE_URL", env.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        if "ollama:" in raw_ollama and self.db_host == "localhost":
            self.ollama_url = "http://localhost:11434"
        else:
            self.ollama_url = raw_ollama.rstrip("/")

        self.model = os.getenv("EMBEDDING_MODEL", "bge-m3")


def fetch_embedding(text: str, base_url: str, model: str, timeout: int = 30) -> Optional[List[float]]:
    """Получение вектора эмбеддинга от локального сервиса Ollama."""
    url = f"{base_url}/api/embeddings"
    payload = {
        "model": model,
        "prompt": text
    }
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        embedding = data.get("embedding")
        if embedding and isinstance(embedding, list) and len(embedding) > 0:
            return embedding
        return None
    except requests.exceptions.RequestException as e:
        print(f" {Colors.RED}[Ollama Error: {e}]{Colors.RESET}")
        return None


def run_seeding(config: Config) -> None:
    """Основной цикл векторизации записей в PostgreSQL."""
    print(f"\n{Colors.BOLD}{Colors.HEADER}=== GovTech Knowledge Base Seeder ==={Colors.RESET}")
    print(f"{Colors.CYAN}Подключение к PostgreSQL:{Colors.RESET} {config.db_host}:{config.db_port}/{config.db_name}")
    print(f"{Colors.CYAN}Ollama Endpoint:{Colors.RESET} {config.ollama_url} (модель: {config.model})\n")

    # 1. Подключение к БД
    try:
        conn = psycopg2.connect(
            host=config.db_host,
            port=config.db_port,
            dbname=config.db_name,
            user=config.db_user,
            password=config.db_password
        )
        conn.autocommit = True
    except psycopg2.OperationalError as e:
        print(f"{Colors.RED}❌ Ошибка подключения к PostgreSQL:{Colors.RESET} {e}")
        print(f"{Colors.YELLOW}Убедитесь, что контейнеры запущены (docker compose up -d){Colors.RESET}")
        sys.exit(1)

    # 2. Выборка неиндексированных статей
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, title, section, content
            FROM gov_regulations
            WHERE embedding IS NULL
            ORDER BY id ASC;
        """)
        records = cur.fetchall()

    if not records:
        print(f"{Colors.GREEN}✔ Все записи в базе уже содержат эмбеддинги. Обновление не требуется.{Colors.RESET}\n")
        conn.close()
        return

    print(f"{Colors.YELLOW}Найдено неиндексированных записей: {len(records)}{Colors.RESET}\n")

    # 3. Генерация векторов и обновление строк
    updated_count = 0
    with conn.cursor() as cur:
        for idx, row in enumerate(records, start=1):
            doc_id = row["id"]
            title = row["title"] or ""
            content = row["content"] or ""

            # Объединяем заголовок и контент для максимально точного семантического контекста
            full_text = f"{title}. {content}".strip()
            preview = full_text[:45].replace("\n", " ")

            print(f"[{idx}/{len(records)}] ID {doc_id:2d} | \"{preview}...\" ", end="", flush=True)

            embedding = fetch_embedding(full_text, config.ollama_url, config.model)
            if embedding is None:
                continue

            # Форматируем вектор в строку pgvector: [0.123, -0.456, ...]
            vector_str = "[" + ",".join(str(x) for x in embedding) + "]"

            # Параметризованный безопасный UPDATE
            cur.execute(
                "UPDATE gov_regulations SET embedding = %s WHERE id = %s;",
                (vector_str, doc_id)
            )
            print(f"{Colors.GREEN}[OK - {len(embedding)} dims]{Colors.RESET}")
            updated_count += 1

    conn.close()
    print(f"\n{Colors.BOLD}{Colors.GREEN}✔ Векторизация успешно завершена. Обновлено документов: {updated_count}/{len(records)}{Colors.RESET}\n")


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    config = Config(project_root)
    run_seeding(config)


if __name__ == "__main__":
    main()
