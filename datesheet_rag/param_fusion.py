# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/param_fusion.py

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Set
from collections import Counter

logger = logging.getLogger(__name__)

# === 1. 辅助函数 ===

# 可自定义跳过值
UNSPECIFIED_VALUES = {"not specified", "未具体列出"}


def is_unspecified(value: str) -> bool:
    return isinstance(value, str) and value.strip().lower() in UNSPECIFIED_VALUES


def normalize_key(key: str) -> str:
    return key.replace(" ", "").lower()


def merge_dicts_with_sources(target: dict, source: dict, chunk_id: str, key_map: dict) -> dict:
    for raw_key, value in source.items():
        if is_unspecified(value):
            continue

        norm = normalize_key(raw_key)
        if norm not in key_map:
            key_map[norm] = {
                "counter": Counter(),
                "canonical": raw_key
            }

        key_map[norm]["counter"][raw_key] += 1
        counts = key_map[norm]["counter"]
        most_common = counts.most_common()
        top_count = most_common[0][1]
        candidates = [k for k, cnt in most_common if cnt == top_count]
        old_can = key_map[norm]["canonical"]
        new_can = old_can if old_can in candidates else candidates[0]

        if new_can != old_can:
            if old_can in target:
                vals = target.pop(old_can)
                target.setdefault(new_can, []).extend(vals)
            key_map[norm]["canonical"] = new_can

        key = key_map[norm]["canonical"]
        entries = target.setdefault(key, [])
        for entry in entries:
            if entry["value"] == value:
                if chunk_id not in entry["source_chunks"]:
                    entry["source_chunks"].append(chunk_id)
                break
        else:
            entries.append({
                "value": value,
                "source_chunks": [chunk_id]
            })

    return target


def dump_json_pretty(obj: dict, file_path: Path):
    """
    自定义 JSON Dumper，使源块列表更紧凑。
    """
    text = json.dumps(obj, indent=2, ensure_ascii=False)

    # 修正：正则表达式查找 "source_chunks": [\n...]"
    # 1. 移除了 lambda 表达式末尾多余的 + ']'
    text = re.sub(
        r'("source_chunks": \[\n\s*)((?:.|\n)*?)(\n\s*\])',
        lambda m: m.group(1).replace('\n', ' ') +  # "source_chunks": [
                  m.group(2).replace('\n', '').replace(' ', '') +  # "1","2"
                  m.group(3).replace('\n', ' ').strip(),  # ] (已移除多余的 + ']')
        text
    )



    file_path.write_text(text, encoding="utf-8")


def merge_device_file(device_path: Path, output_dir: Path):
    """
    处理单个 <device_name>.json 文件
    """
    try:
        data = json.loads(device_path.read_text(encoding="utf-8"))
        merged = {"Device": data.get("Device", {})}
        key_maps = {}  # 用于规范化 key 的映射

        for chunk_id, content in data.get("chunk_parameters", {}).items():
            if not isinstance(content, dict):
                continue

            # 遍历 chunk 结果中的每个部分 (Parameters, Basic information, ...)
            for section, values in content.items():
                if not isinstance(values, dict):
                    continue

                # 确保顶层和 key_map 中有这个部分
                merged.setdefault(section, {})
                key_maps.setdefault(section, {})

                # 执行合并
                merged[section] = merge_dicts_with_sources(
                    merged[section],  # 目标字典 (e.g., merged["Parameters"])
                    values,  # 源字典 (e.g., content["Parameters"])
                    chunk_id,  # 源 Chunk ID
                    key_maps[section]  # 该部分的 Key 映射
                )

        out_path = output_dir / f"{device_path.stem}_merged.json"
        dump_json_pretty(merged, out_path)
        logger.info(f"已融合: {out_path.name}")

    except json.JSONDecodeError as e:
        logger.error(f"解析 {device_path.name} 失败: {e}")
    except Exception as e:
        logger.error(f"处理 {device_path.name} 时出错: {e}", exc_info=True)


# --- 主协调函数 (供 Celery 调用) ---
def process_parameter_fusion(param_results_dir_path: str):
    """
    从 Celery 调用的主函数，协调所有参数融合步骤。
    """
    logger.info(f"开始参数融合（步骤1）: {param_results_dir_path}")

    base_dir = Path(param_results_dir_path)
    merged_dir = base_dir / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)

    device_files = list(base_dir.glob("*.json"))
    if not device_files:
        logger.warning(f"在 {base_dir} 中未找到要融合的 .json 文件。")
        return

    logger.info(f"找到 {len(device_files)} 个 .json 文件待融合...")

    for file in device_files:
        if file.name.endswith("_merged.json"):
            continue
        logger.info(f"正在处理: {file.name}")
        merge_device_file(file, merged_dir)

    logger.info("参数融合（步骤1）完成。")