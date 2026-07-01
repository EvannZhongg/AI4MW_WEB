from __future__ import annotations

import os
from dataclasses import dataclass, field


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


@dataclass(slots=True)
class AgentConfig:
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "")
    )
    openrouter_api_base: str = OPENROUTER_API_BASE
    image_model: str = "qwen/qwen3-vl-8b-instruct"
    text_model: str = "deepseek/deepseek-v3.2"
    http_timeout_seconds: float = 90.0
    max_concurrency: int = 6
    paper_concurrency: int = 3
    image_max_side: int = 1280
    image_jpeg_quality: int = 82
    image_max_tokens: int = 1200
    text_max_tokens: int = 1400
    temperature: float = 0.0
    top_p: float = 0.1
    output_image_json_name: str = "image_extraction.json"
    output_text_json_name: str = "fss_extraction.json"
    output_report_name: str = "extraction_report.csv"
    persist_to_postgres: bool = field(
        default_factory=lambda: os.getenv("FSS_PERSIST_POSTGRES", "1").lower() not in {"0", "false", "no"}
    )
    postgres_database: str = field(default_factory=lambda: os.getenv("FSS_POSTGRES_DATABASE", "fss"))
    postgres_admin_dsn: str = field(
        default_factory=lambda: os.getenv(
            "FSS_POSTGRES_ADMIN_DSN",
            "postgresql://postgres:postgres@localhost:5432/postgres",
        )
    )
    postgres_dsn: str = field(
        default_factory=lambda: os.getenv(
            "FSS_POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/fss",
        )
    )
    persist_to_nebula: bool = field(
        default_factory=lambda: os.getenv("FSS_PERSIST_NEBULA", "1").lower() not in {"0", "false", "no"}
    )
    nebula_host: str = field(default_factory=lambda: os.getenv("FSS_NEBULA_HOST", "127.0.0.1"))
    nebula_port: int = field(default_factory=lambda: int(os.getenv("FSS_NEBULA_PORT", "9669")))
    nebula_user: str = field(default_factory=lambda: os.getenv("FSS_NEBULA_USER", "root"))
    nebula_password: str = field(default_factory=lambda: os.getenv("FSS_NEBULA_PASSWORD", "nebula"))
    nebula_space: str = field(default_factory=lambda: os.getenv("FSS_NEBULA_SPACE", "fss_kg"))
