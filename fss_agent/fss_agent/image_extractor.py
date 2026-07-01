from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from .client import CompletionResult, CompletionUsage, OpenRouterClient
from .config import AgentConfig


IMAGE_EXTRACTION_PROMPT = """
【任务1：图片提取】：
1）按顺序读取imgs目录下的imag图片，输出结构图最外环或整体结构对应的参数字母（如L、D、h、W、P等），只要有图片成功提取字母，剩下的图片不用继续提取；提取图中FSS结构包含的所有颜色，{"black","white","orange","red",…}格式返回，颜色标准化采用HSV空间。
2）读取imgs目录下的table图片，提取全部文字，并按行或列整理。
严格按下面 JSON 模板输出：
{
  "parameters": [],
  "col_mats": {},
  "table_content": ""
}
""".strip()


IMAGE_TASK_SYSTEM_PROMPT = """
你是一个只输出 JSON 的 FSS 图片信息抽取器。
只保留和任务直接相关的信息，不要解释，不要补充无关字段。
若没有识别到内容，返回空数组、空对象或空字符串。
""".strip()


class ImageExtractionModule:
    def __init__(self, client: OpenRouterClient, config: AgentConfig) -> None:
        self.client = client
        self.config = config

    async def extract_from_paper_dir(self, paper_dir: Path) -> CompletionResult:
        image_paths = self._collect_files(paper_dir / "imgs" / "image")
        table_paths = self._collect_files(paper_dir / "imgs" / "table")

        content: list[dict[str, Any]] = [{"type": "text", "text": self._build_user_prompt(image_paths, table_paths)}]
        for image_path in image_paths:
            content.append(self._build_image_part(image_path))
        for table_path in table_paths:
            content.append(self._build_image_part(table_path))

        if len(content) == 1:
            return CompletionResult(
                payload={"parameters": [], "col_mats": {}, "table_content": ""},
                usage=CompletionUsage(),
            )

        return await self.client.create_json_completion(
            model=self.config.image_model,
            messages=[
                {"role": "system", "content": IMAGE_TASK_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            max_tokens=self.config.image_max_tokens,
        )

    def _build_user_prompt(self, image_paths: list[Path], table_paths: list[Path]) -> str:
        image_names = [path.name for path in image_paths]
        table_names = [path.name for path in table_paths]
        compact_manifest = json.dumps(
            {
                "structure_image_files": image_names,
                "table_image_files": table_names,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            f"{IMAGE_EXTRACTION_PROMPT}\n\n"
            "补充要求：\n"
            "1. 仅根据当前输入图片作答。\n"
            "2. parameters 只保留字母或字母组合，不要附带数值。\n"
            "3. col_mats 先返回颜色键，材料值未知时填空字符串。\n"
            "4. table_content 合并所有表格内容，尽量紧凑。\n"
            f"5. 输入清单：{compact_manifest}"
        )

    def _build_image_part(self, path: Path) -> dict[str, Any]:
        data_url = self._to_data_url(path)
        return {"type": "image_url", "image_url": {"url": data_url}}

    def _to_data_url(self, path: Path) -> str:
        image = Image.open(path)
        image = image.convert("RGB")
        image.thumbnail((self.config.image_max_side, self.config.image_max_side))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=self.config.image_jpeg_quality, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _collect_files(folder: Path) -> list[Path]:
        if not folder.exists():
            return []
        return sorted(path for path in folder.iterdir() if path.is_file())
