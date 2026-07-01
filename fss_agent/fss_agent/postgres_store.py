from __future__ import annotations

from typing import Any

from .config import AgentConfig
from .persistence_models import PaperPersistenceRecord, json_dumps, stable_key


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    id BIGSERIAL PRIMARY KEY,
    paper_key TEXT NOT NULL UNIQUE,
    paper_name TEXT NOT NULL,
    paper_dir TEXT NOT NULL,
    title TEXT,
    authors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sections (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section_key TEXT NOT NULL UNIQUE,
    section_order INTEGER NOT NULL,
    section_title TEXT,
    section_text TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    asset_key TEXT NOT NULL UNIQUE,
    asset_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    caption TEXT
);

CREATE TABLE IF NOT EXISTS extraction_reports (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
    image_extraction_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    text_extraction_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_extraction_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ground_truth TEXT,
    image_prompt_tokens INTEGER NOT NULL DEFAULT 0,
    image_completion_tokens INTEGER NOT NULL DEFAULT 0,
    image_total_tokens INTEGER NOT NULL DEFAULT 0,
    text_prompt_tokens INTEGER NOT NULL DEFAULT 0,
    text_completion_tokens INTEGER NOT NULL DEFAULT 0,
    text_total_tokens INTEGER NOT NULL DEFAULT 0,
    all_total_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fss_structures (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    structure_key TEXT NOT NULL UNIQUE,
    name TEXT,
    structure_type TEXT,
    description TEXT,
    package JSONB NOT NULL DEFAULT '{}'::jsonb,
    layers JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS materials (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    material_key TEXT NOT NULL UNIQUE,
    material_role TEXT NOT NULL,
    name TEXT NOT NULL,
    dielectric_constant TEXT,
    loss_tangent TEXT
);

CREATE TABLE IF NOT EXISTS frequency_bands (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    band_key TEXT NOT NULL UNIQUE,
    band_type TEXT,
    center_frequency TEXT,
    working_frequency TEXT,
    passband_frequency TEXT,
    bandwidth TEXT,
    resonant_frequency TEXT
);

CREATE TABLE IF NOT EXISTS performance_metrics (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL UNIQUE,
    metric_name TEXT NOT NULL,
    metric_value TEXT
);
"""

MIGRATION_SQL = """
ALTER TABLE papers ADD COLUMN IF NOT EXISTS paper_key TEXT;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS authors JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
UPDATE papers SET paper_key = 'paper:legacy:' || id::text WHERE paper_key IS NULL OR paper_key = '';
CREATE UNIQUE INDEX IF NOT EXISTS papers_paper_key_idx ON papers(paper_key);

ALTER TABLE sections ADD COLUMN IF NOT EXISTS section_key TEXT;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS section_order INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS section_title TEXT;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS section_text TEXT;
UPDATE sections SET section_key = 'section:legacy:' || id::text WHERE section_key IS NULL OR section_key = '';
CREATE UNIQUE INDEX IF NOT EXISTS sections_section_key_idx ON sections(section_key);

ALTER TABLE assets ADD COLUMN IF NOT EXISTS asset_key TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS relative_path TEXT NOT NULL DEFAULT '';
UPDATE assets SET asset_key = 'asset:legacy:' || id::text WHERE asset_key IS NULL OR asset_key = '';
CREATE UNIQUE INDEX IF NOT EXISTS assets_asset_key_idx ON assets(asset_key);

ALTER TABLE extraction_reports ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE UNIQUE INDEX IF NOT EXISTS extraction_reports_paper_id_idx ON extraction_reports(paper_id);

CREATE UNIQUE INDEX IF NOT EXISTS fss_structures_structure_key_idx ON fss_structures(structure_key);
CREATE UNIQUE INDEX IF NOT EXISTS materials_material_key_idx ON materials(material_key);
CREATE UNIQUE INDEX IF NOT EXISTS frequency_bands_band_key_idx ON frequency_bands(band_key);
CREATE UNIQUE INDEX IF NOT EXISTS performance_metrics_metric_key_idx ON performance_metrics(metric_key);
"""


class PostgresStore:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._psycopg: Any | None = None

    def initialize(self) -> None:
        self._load_driver()
        self._ensure_database()
        with self._connect(self.config.postgres_dsn) as conn:
            conn.execute(SCHEMA_SQL)
            conn.execute(MIGRATION_SQL)
            conn.commit()

    def save_record(self, record: PaperPersistenceRecord) -> None:
        self._load_driver()
        with self._connect(self.config.postgres_dsn) as conn:
            paper_id = self._upsert_paper(conn, record)
            self._upsert_sections(conn, paper_id, record)
            self._upsert_assets(conn, paper_id, record)
            self._upsert_extraction_report(conn, paper_id, record)
            self._upsert_domain_entities(conn, paper_id, record)
            conn.commit()

    def _load_driver(self) -> None:
        if self._psycopg is not None:
            return
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL 自动入库需要安装 psycopg：python -m pip install psycopg[binary]"
            ) from exc
        self._psycopg = psycopg

    def _connect(self, dsn: str) -> Any:
        assert self._psycopg is not None
        return self._psycopg.connect(dsn, autocommit=False)

    def _ensure_database(self) -> None:
        db_name = self.config.postgres_database
        with self._connect(self.config.postgres_admin_dsn) as conn:
            conn.autocommit = True
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)).fetchone()
            if not exists:
                quoted = '"' + db_name.replace('"', '""') + '"'
                conn.execute(f"CREATE DATABASE {quoted}")

    def _upsert_paper(self, conn: Any, record: PaperPersistenceRecord) -> int:
        row = conn.execute(
            """
            INSERT INTO papers (paper_key, paper_name, paper_dir, title, authors)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (paper_key) DO UPDATE SET
                paper_name = EXCLUDED.paper_name,
                paper_dir = EXCLUDED.paper_dir,
                title = EXCLUDED.title,
                authors = EXCLUDED.authors,
                updated_at = now()
            RETURNING id
            """,
            (record.paper_key, record.paper_name, record.paper_dir, record.title, json_dumps(record.authors)),
        ).fetchone()
        return int(row[0])

    def _upsert_sections(self, conn: Any, paper_id: int, record: PaperPersistenceRecord) -> None:
        for section in record.sections:
            conn.execute(
                """
                INSERT INTO sections (paper_id, section_key, section_order, section_title, section_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (section_key) DO UPDATE SET
                    section_order = EXCLUDED.section_order,
                    section_title = EXCLUDED.section_title,
                    section_text = EXCLUDED.section_text
                """,
                (paper_id, section.section_key, section.section_order, section.section_title, section.section_text),
            )

    def _upsert_assets(self, conn: Any, paper_id: int, record: PaperPersistenceRecord) -> None:
        for asset in record.assets:
            conn.execute(
                """
                INSERT INTO assets (paper_id, asset_key, asset_type, file_path, relative_path, caption)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_key) DO UPDATE SET
                    asset_type = EXCLUDED.asset_type,
                    file_path = EXCLUDED.file_path,
                    relative_path = EXCLUDED.relative_path,
                    caption = EXCLUDED.caption
                """,
                (paper_id, asset.asset_key, asset.asset_type, asset.file_path, asset.relative_path, asset.caption),
            )

    def _upsert_extraction_report(self, conn: Any, paper_id: int, record: PaperPersistenceRecord) -> None:
        conn.execute(
            """
            INSERT INTO extraction_reports (
                paper_id, image_extraction_json, text_extraction_json, final_extraction_json, ground_truth,
                image_prompt_tokens, image_completion_tokens, image_total_tokens,
                text_prompt_tokens, text_completion_tokens, text_total_tokens, all_total_tokens
            )
            VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (paper_id) DO UPDATE SET
                image_extraction_json = EXCLUDED.image_extraction_json,
                text_extraction_json = EXCLUDED.text_extraction_json,
                final_extraction_json = EXCLUDED.final_extraction_json,
                ground_truth = EXCLUDED.ground_truth,
                image_prompt_tokens = EXCLUDED.image_prompt_tokens,
                image_completion_tokens = EXCLUDED.image_completion_tokens,
                image_total_tokens = EXCLUDED.image_total_tokens,
                text_prompt_tokens = EXCLUDED.text_prompt_tokens,
                text_completion_tokens = EXCLUDED.text_completion_tokens,
                text_total_tokens = EXCLUDED.text_total_tokens,
                all_total_tokens = EXCLUDED.all_total_tokens,
                updated_at = now()
            """,
            (
                paper_id,
                json_dumps(record.image_payload),
                json_dumps(record.text_payload),
                json_dumps(record.text_payload),
                "",
                record.image_usage.prompt_tokens,
                record.image_usage.completion_tokens,
                record.image_usage.total_tokens,
                record.text_usage.prompt_tokens,
                record.text_usage.completion_tokens,
                record.text_usage.total_tokens,
                record.image_usage.total_tokens + record.text_usage.total_tokens,
            ),
        )

    def _upsert_domain_entities(self, conn: Any, paper_id: int, record: PaperPersistenceRecord) -> None:
        payload = record.text_payload
        structure_types = _as_list(payload.get("structure_types")) or [payload.get("title") or record.paper_name]
        for index, structure_type in enumerate(structure_types, start=1):
            key = f"structure:{record.paper_key}:{index}"
            conn.execute(
                """
                INSERT INTO fss_structures (paper_id, structure_key, name, structure_type, description, package, layers)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (structure_key) DO UPDATE SET
                    name = EXCLUDED.name,
                    structure_type = EXCLUDED.structure_type,
                    description = EXCLUDED.description,
                    package = EXCLUDED.package,
                    layers = EXCLUDED.layers
                """,
                (
                    paper_id,
                    key,
                    str(structure_type),
                    str(structure_type),
                    str(payload.get("core_performance", "")),
                    json_dumps(payload.get("FSS_package") or {}),
                    json_dumps(payload.get("layers") or {}),
                ),
            )

        for role, names in (
            ("substrate", _as_list(payload.get("substrate_materials"))),
            ("conductor", _as_list(payload.get("conductor_materials"))),
        ):
            for name in names:
                key = f"material:{record.paper_key}:{stable_key(role, name)}"
                conn.execute(
                    """
                    INSERT INTO materials (
                        paper_id, material_key, material_role, name, dielectric_constant, loss_tangent
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (material_key) DO UPDATE SET
                        material_role = EXCLUDED.material_role,
                        name = EXCLUDED.name,
                        dielectric_constant = EXCLUDED.dielectric_constant,
                        loss_tangent = EXCLUDED.loss_tangent
                    """,
                    (
                        paper_id,
                        key,
                        role,
                        str(name),
                        str(payload.get("dielectric_constant", "")),
                        str(payload.get("loss_tangent", "")),
                    ),
                )

        band_key = f"band:{record.paper_key}:main"
        conn.execute(
            """
            INSERT INTO frequency_bands (
                paper_id, band_key, band_type, center_frequency, working_frequency,
                passband_frequency, bandwidth, resonant_frequency
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (band_key) DO UPDATE SET
                band_type = EXCLUDED.band_type,
                center_frequency = EXCLUDED.center_frequency,
                working_frequency = EXCLUDED.working_frequency,
                passband_frequency = EXCLUDED.passband_frequency,
                bandwidth = EXCLUDED.bandwidth,
                resonant_frequency = EXCLUDED.resonant_frequency
            """,
            (
                paper_id,
                band_key,
                str(payload.get("band_type", "")),
                str(payload.get("center_frequency", "")),
                str(payload.get("working_frequency", "")),
                str(payload.get("passband_frequency", "")),
                str(payload.get("bandwidth", "")),
                str(payload.get("resonant_frequency", "")),
            ),
        )

        metrics = {
            "incident_angle": payload.get("incident_angle", ""),
            "q_value": payload.get("q_value", ""),
            "core_performance": payload.get("core_performance", ""),
            "other_parameters": payload.get("Other parameters", ""),
        }
        for name, value in metrics.items():
            if str(value):
                conn.execute(
                    """
                    INSERT INTO performance_metrics (paper_id, metric_key, metric_name, metric_value)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (metric_key) DO UPDATE SET
                        metric_name = EXCLUDED.metric_name,
                        metric_value = EXCLUDED.metric_value
                    """,
                    (paper_id, f"metric:{record.paper_key}:{name}", name, str(value)),
                )


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]
