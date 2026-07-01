from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .client import CompletionResult, OpenRouterClient
from .config import AgentConfig


TEXT_EXTRACTION_PROMPT = """
【任务2：文本信息提取】
一、任务：提取该论文主提出的 FSS 所有相关信息，并输出严格合法的 JSON。
二、字段规则：
1）固定输出的字段：
1.Instance：固定"FSS"。
2.Folder_path： markdown 文件所在绝对路径。
3.mode：固定 "S"。
4.fss_structure_images：imgs目录下的imag图片的绝对路径。
2）title与"authors：只提取structured_sections.json 顶层字段并填入，不读取"sections"中的内容，
3）只读取structured_sections.json中"sections"中的内容并填写以下字段：
1.band_type：论文明确给出的频段名称
2.对频率字段的判定：
   - center_frequency：中心频率
   - working_frequency：工作频率/设计频率
   - passband_frequency：通带范围
   - bandwidth：带宽或相对带宽
   - resonant_frequency：谐振频率
   若原文只明确给出一个设计频率，如 “designed at 60 GHz”，优先填 working_frequency，也可同步填 center_frequency。
3.structure_types：按论文原文并适度归一。
4.dielectric_constant：绑定材料名输出，例如 “ FR4: 4.4”。
5.loss_tangent：绑定材料名输出。
6.incident_angle：若区分 TE/TM，可写为 “TE: 0°-60°; TM: 0°-60°”。
7.substrate_materials: 介质板材料。
8.conductor_materials: 金属材料。
9.Other parameters：所有文中出现的有单位的参数。
10.FSS_package中：
-X=Y：主提出FSS 单元 x和Y方向整体尺寸，即FSS单元最外围的尺寸。
-Z：介质基板厚度，奴能成功提取则默认1.6mm。
-如果过不能成功提取X和Y的值，则根据任务1提取出来的parameters字母与任务2中的Other parameters相对应，将能对应上的数值最大值输出为X和Y。
-f0 固定为 "0.5" ,f1 固定为"20"。
-Units：根据文中判断。
11.layer_number：若文中并未明确提出，则层数填1。
12.layers 中：
   - 如果layer_number输出1，则只需要填写"layer1"的实际信息，"layer2"与"layer3"直接去掉，以此类推。
   - img_path 固定输出 "Null"。
   - substrate 填该层基板材料或介质信息。
   - gnd 判断是否为接地层，是，则填写"True",不是，则填写"False";
   - col_mats":按照任务1的实际提取来写，并将颜色与任务2的材料相匹配，"conductor_materials"部分通常对应颜色较深的区域（如黑色、深灰色、蓝色等），"substrate_materials"部分通常对应颜色较浅的区域（如白色、浅灰色等），输出示例：col_mats = {
    'black': 'PEC',
    'white': 'FR4',
    'red': 'PEC',
    'blue': 'FR4'
    }
严格按下面 JSON 模板输出：
{
"Folder_path": "",
  "Instance": "FSS",
  "mode": "S",
  "fss_structure_images": [],
"title": "",
  "authors": "",
  "band_type": "",
"center_frequency": "",
  "working_frequency": "",
  "passband_frequency": "",
  "bandwidth": "",
  "resonant_frequency": "",
"structure_types": [],
  "dielectric_constant": "",
  "loss_tangent": "",
  "incident_angle": "",
  "q_value": "",
  "substrate_materials": [],
  "conductor_materials": [],
  "application_fields": [],
  "core_performance": "",
"Other parameters": "",
"FSS_package": {
    "X": "",
"Y": "",
"Z": "",
    "f0": 0,
"f1": 0,
"Unit": ""
  },
"layer_number":"",
  "layers": {
    "layer1": {
      "img_path": "Null",
      "substrate": "",
      "gnd": "",
"col_mats": {}
    },
    "layer2": {
      "img_path": "Null",
      "substrate": "",
      "gnd": "",
"col_mats": {}
    },
    "layer3": {
      "img_path": "Null",
      "substrate": "",
      "gnd": "",
"col_mats": {}
    }
  }
}
""".strip()


TEXT_TASK_SYSTEM_PROMPT = """
你是一个只输出 JSON 的 FSS 论文信息抽取器。
优先依据输入文本直接抽取，避免臆测；无法确认时返回空字符串、空数组或默认值。
严格输出合法 JSON，不要附加解释。
""".strip()


class TextExtractionModule:
    def __init__(self, client: OpenRouterClient, config: AgentConfig) -> None:
        self.client = client
        self.config = config

    async def extract_from_paper_dir(
        self,
        paper_dir: Path,
        image_result: dict[str, Any],
    ) -> CompletionResult:
        structured_path = paper_dir / "structured_sections.json"
        compact_payload = self._build_compact_payload(structured_path, paper_dir, image_result)

        return await self.client.create_json_completion(
            model=self.config.text_model,
            messages=[
                {"role": "system", "content": TEXT_TASK_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"{TEXT_EXTRACTION_PROMPT}\n\n"
                        "补充要求：\n"
                        "1. 仅基于输入 JSON 与任务1结果抽取。\n"
                        "2. 输出字段必须完整；不适用时保留空值。\n"
                        "3. 尽量使用原文单位，不要重复表述。\n"
                        "4. 若 layer_number=1，只保留 layer1。\n"
                        "5. 输入数据如下：\n"
                        f"{compact_payload}"
                    ),
                },
            ],
            max_tokens=self.config.text_max_tokens,
        )

    def _build_compact_payload(self, structured_path: Path, paper_dir: Path, image_result: dict[str, Any]) -> str:
        raw = json.loads(structured_path.read_text(encoding="utf-8"))
        paper_payload = {
            "Folder_path": str(paper_dir.resolve()),
            "fss_structure_images": [str(path.resolve()) for path in self._collect_structure_images(paper_dir)],
            "title": raw.get("title", ""),
            "authors": raw.get("authors", []),
            "sections": [
                {
                    "title": item.get("title", ""),
                    "text": self._compact_text(item.get("text", "")),
                }
                for item in raw.get("sections", [])
            ],
            "image_task_result": image_result,
        }
        return json.dumps(paper_payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _collect_structure_images(paper_dir: Path) -> list[Path]:
        image_dir = paper_dir / "imgs" / "image"
        if not image_dir.exists():
            return []
        return sorted(path for path in image_dir.iterdir() if path.is_file())

    @staticmethod
    def _compact_text(text: str) -> str:
        return " ".join(text.split())
