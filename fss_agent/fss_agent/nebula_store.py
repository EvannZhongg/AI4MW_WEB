from __future__ import annotations

import time
from typing import Any

from .config import AgentConfig
from .persistence_models import PaperPersistenceRecord, stable_key


class NebulaGraphStore:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._pool: Any | None = None
        self._session: Any | None = None

    def initialize(self) -> None:
        self._connect()
        self._execute(
            f"""
            CREATE SPACE IF NOT EXISTS {self.config.nebula_space}
            (partition_num=10, replica_factor=1, vid_type=FIXED_STRING(128))
            """
        )
        self._use_space_with_retry()
        self._create_schema()

    def close(self) -> None:
        if self._session is not None:
            self._session.release()
            self._session = None
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def save_record(self, record: PaperPersistenceRecord) -> None:
        self._use_space_with_retry()
        self._insert_paper(record)
        self._insert_sections(record)
        self._insert_assets(record)
        self._insert_report(record)
        self._insert_domain_entities(record)

    def _connect(self) -> None:
        try:
            from nebula3.Config import Config
            from nebula3.gclient.net import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "NebulaGraph 自动写入需要安装 nebula3-python：python -m pip install nebula3-python"
            ) from exc

        config = Config()
        config.max_connection_pool_size = 10
        pool = ConnectionPool()
        ok = pool.init([(self.config.nebula_host, self.config.nebula_port)], config)
        if not ok:
            raise RuntimeError("无法连接 NebulaGraph，请确认 graphd 已启动，默认端口是 9669。")
        self._pool = pool
        self._session = pool.get_session(self.config.nebula_user, self.config.nebula_password)

    def _execute(self, statement: str) -> Any:
        if self._session is None:
            raise RuntimeError("NebulaGraph session has not been initialized.")
        result = self._session.execute(statement.strip())
        if not result.is_succeeded():
            raise RuntimeError(f"NebulaGraph 执行失败：{result.error_msg()}\nSQL: {statement}")
        return result

    def _use_space_with_retry(self) -> None:
        last_error: Exception | None = None
        for _ in range(30):
            try:
                self._execute(f"USE {self.config.nebula_space};")
                return
            except RuntimeError as exc:
                last_error = exc
                time.sleep(1)
        raise RuntimeError(f"无法切换到 NebulaGraph space {self.config.nebula_space}") from last_error

    def _create_schema(self) -> None:
        statements = [
            """
            CREATE TAG IF NOT EXISTS Paper (
              paper_id string, paper_name string, paper_dir string, title string, authors string
            )
            """,
            """
            CREATE TAG IF NOT EXISTS Section (
              section_id string, section_order int, section_title string, section_text string
            )
            """,
            """
            CREATE TAG IF NOT EXISTS Asset (
              asset_id string, asset_type string, file_path string, relative_path string, caption string
            )
            """,
            """
            CREATE TAG IF NOT EXISTS ExtractionReport (
              report_id string, image_extraction_json string, text_extraction_json string, all_total_tokens int
            )
            """,
            """
            CREATE TAG IF NOT EXISTS FSSStructure (
              structure_id string, name string, structure_type string, description string, package_json string, layers_json string
            )
            """,
            """
            CREATE TAG IF NOT EXISTS Material (
              material_id string, name string, material_role string, dielectric_constant string, loss_tangent string
            )
            """,
            """
            CREATE TAG IF NOT EXISTS FrequencyBand (
              band_id string, band_type string, center_frequency string, working_frequency string,
              passband_frequency string, bandwidth string, resonant_frequency string
            )
            """,
            """
            CREATE TAG IF NOT EXISTS PerformanceMetric (
              metric_id string, metric_name string, metric_value string
            )
            """,
            "CREATE EDGE IF NOT EXISTS HAS_SECTION (section_order int)",
            "CREATE EDGE IF NOT EXISTS HAS_ASSET (asset_type string)",
            "CREATE EDGE IF NOT EXISTS HAS_IMAGE (caption string)",
            "CREATE EDGE IF NOT EXISTS HAS_TABLE (caption string)",
            "CREATE EDGE IF NOT EXISTS HAS_REPORT ()",
            "CREATE EDGE IF NOT EXISTS PROPOSES_STRUCTURE ()",
            "CREATE EDGE IF NOT EXISTS USES_MATERIAL ()",
            "CREATE EDGE IF NOT EXISTS OPERATES_AT ()",
            "CREATE EDGE IF NOT EXISTS HAS_PERFORMANCE ()",
            "CREATE EDGE IF NOT EXISTS MENTIONED_IN ()",
        ]
        for statement in statements:
            self._execute(statement)
        time.sleep(10)

    def _insert_paper(self, record: PaperPersistenceRecord) -> None:
        self._execute(
            "INSERT VERTEX Paper(paper_id,paper_name,paper_dir,title,authors) "
            f"VALUES {vid(record.paper_key)}:("
            f"{s(record.paper_key)},{s(record.paper_name)},{s(record.paper_dir)},"
            f"{s(record.title)},{s(_stringify(record.authors))})"
        )

    def _insert_sections(self, record: PaperPersistenceRecord) -> None:
        for section in record.sections:
            self._execute(
                "INSERT VERTEX Section(section_id,section_order,section_title,section_text) "
                f"VALUES {vid(section.section_key)}:("
                f"{s(section.section_key)},{section.section_order},"
                f"{s(section.section_title)},{s(section.section_text)})"
            )
            self._execute(
                "INSERT EDGE HAS_SECTION(section_order) "
                f"VALUES {vid(record.paper_key)}->{vid(section.section_key)}:({section.section_order})"
            )

    def _insert_assets(self, record: PaperPersistenceRecord) -> None:
        for asset in record.assets:
            self._execute(
                "INSERT VERTEX Asset(asset_id,asset_type,file_path,relative_path,caption) "
                f"VALUES {vid(asset.asset_key)}:("
                f"{s(asset.asset_key)},{s(asset.asset_type)},{s(asset.file_path)},"
                f"{s(asset.relative_path)},{s(asset.caption)})"
            )
            self._execute(
                "INSERT EDGE HAS_ASSET(asset_type) "
                f"VALUES {vid(record.paper_key)}->{vid(asset.asset_key)}:({s(asset.asset_type)})"
            )
            if asset.asset_type == "image":
                self._execute(
                    "INSERT EDGE HAS_IMAGE(caption) "
                    f"VALUES {vid(record.paper_key)}->{vid(asset.asset_key)}:({s(asset.caption)})"
                )
            if asset.asset_type == "table":
                self._execute(
                    "INSERT EDGE HAS_TABLE(caption) "
                    f"VALUES {vid(record.paper_key)}->{vid(asset.asset_key)}:({s(asset.caption)})"
                )

    def _insert_report(self, record: PaperPersistenceRecord) -> None:
        report_key = f"report:{record.paper_key}"
        self._execute(
            "INSERT VERTEX ExtractionReport(report_id,image_extraction_json,text_extraction_json,all_total_tokens) "
            f"VALUES {vid(report_key)}:("
            f"{s(report_key)},{s(_stringify(record.image_payload))},{s(_stringify(record.text_payload))},"
            f"{record.image_usage.total_tokens + record.text_usage.total_tokens})"
        )
        self._execute(f"INSERT EDGE HAS_REPORT() VALUES {vid(record.paper_key)}->{vid(report_key)}:()")

    def _insert_domain_entities(self, record: PaperPersistenceRecord) -> None:
        payload = record.text_payload
        structure_keys = []
        structure_types = _as_list(payload.get("structure_types")) or [payload.get("title") or record.paper_name]
        for index, structure_type in enumerate(structure_types, start=1):
            structure_key = f"structure:{record.paper_key}:{index}"
            structure_keys.append(structure_key)
            self._execute(
                "INSERT VERTEX FSSStructure(structure_id,name,structure_type,description,package_json,layers_json) "
                f"VALUES {vid(structure_key)}:("
                f"{s(structure_key)},{s(str(structure_type))},{s(str(structure_type))},"
                f"{s(str(payload.get('core_performance', '')))},"
                f"{s(_stringify(payload.get('FSS_package') or {}))},"
                f"{s(_stringify(payload.get('layers') or {}))})"
            )
            self._execute(f"INSERT EDGE PROPOSES_STRUCTURE() VALUES {vid(record.paper_key)}->{vid(structure_key)}:()")

        material_keys = []
        for role, names in (
            ("substrate", _as_list(payload.get("substrate_materials"))),
            ("conductor", _as_list(payload.get("conductor_materials"))),
        ):
            for name in names:
                material_key = f"material:{record.paper_key}:{stable_key(role, name)}"
                material_keys.append(material_key)
                self._execute(
                    "INSERT VERTEX Material(material_id,name,material_role,dielectric_constant,loss_tangent) "
                    f"VALUES {vid(material_key)}:("
                    f"{s(material_key)},{s(str(name))},{s(role)},"
                    f"{s(str(payload.get('dielectric_constant', '')))},"
                    f"{s(str(payload.get('loss_tangent', '')))})"
                )

        band_key = f"band:{record.paper_key}:main"
        self._execute(
            "INSERT VERTEX FrequencyBand(band_id,band_type,center_frequency,working_frequency,passband_frequency,bandwidth,resonant_frequency) "
            f"VALUES {vid(band_key)}:("
            f"{s(band_key)},{s(str(payload.get('band_type', '')))},"
            f"{s(str(payload.get('center_frequency', '')))},"
            f"{s(str(payload.get('working_frequency', '')))},"
            f"{s(str(payload.get('passband_frequency', '')))},"
            f"{s(str(payload.get('bandwidth', '')))},"
            f"{s(str(payload.get('resonant_frequency', '')))})"
        )

        metric_keys = []
        for name, value in {
            "incident_angle": payload.get("incident_angle", ""),
            "q_value": payload.get("q_value", ""),
            "core_performance": payload.get("core_performance", ""),
            "other_parameters": payload.get("Other parameters", ""),
        }.items():
            if str(value):
                metric_key = f"metric:{record.paper_key}:{name}"
                metric_keys.append(metric_key)
                self._execute(
                    "INSERT VERTEX PerformanceMetric(metric_id,metric_name,metric_value) "
                    f"VALUES {vid(metric_key)}:({s(metric_key)},{s(name)},{s(str(value))})"
                )

        for structure_key in structure_keys:
            self._execute(f"INSERT EDGE OPERATES_AT() VALUES {vid(structure_key)}->{vid(band_key)}:()")
            for material_key in material_keys:
                self._execute(f"INSERT EDGE USES_MATERIAL() VALUES {vid(structure_key)}->{vid(material_key)}:()")
            for metric_key in metric_keys:
                self._execute(f"INSERT EDGE HAS_PERFORMANCE() VALUES {vid(structure_key)}->{vid(metric_key)}:()")


def s(value: Any) -> str:
    text = "" if value is None else str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def vid(value: str) -> str:
    return s(value[:128])


def _stringify(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]
