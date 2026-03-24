# pdf_parser/manufacturer_standardization.py

import json
import logging
import uuid
import copy
import time
from pathlib import Path
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
from typing import List, Dict, Any
from filelock import FileLock  # 确保已安装: pip install filelock
from django.conf import settings
from .prompts import get_manufacturer_standardization_prompt

logger = logging.getLogger(__name__)

# --- 共享数据文件路径 (相对于此文件) ---
DATA_DIR = Path(__file__).resolve().parent / "data"
STANDARD_MANUFACTURERS_FILE = DATA_DIR / "standard_manufacturers.json"
PRECOMPUTED_EMBEDDINGS_FILE = DATA_DIR / "manufacturers_with_embeddings.json"


# === 辅助函数 (Helpers) ===

def load_json_file(file_path: Path) -> Any:
    """
    (*** 这是新添加的缺失函数 ***)
    加载JSON文件
    """
    if not file_path.exists():
        logger.warning(f"JSON文件 {file_path} 未找到。")
        return None
    try:
        # 确保文件非空
        content = file_path.read_text(encoding='utf-8')
        if not content.strip():
            logger.warning(f"JSON文件 {file_path} 为空。")
            return None
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"JSON文件 {file_path} 格式无效。")
        return None
    except Exception as e:
        logger.error(f"读取JSON文件 {file_path} 时发生错误: {e}")
        return None


def get_embedding(text: str, client: OpenAI, model: str, dimensions: int) -> List[float]:
    """获取嵌入向量。"""
    if not text or not text.strip():
        logger.warning(f"输入文本为空，无法获取嵌入向量。")
        return None
    try:
        response = client.embeddings.create(
            model=model,
            input=text,
            dimensions=dimensions,
            encoding_format="float"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"获取嵌入向量失败 ('{text}'): {e}")
        return None


def call_llm_for_decision(prompt_text: str, client: OpenAI, model: str, temperature: float, max_retries: int,
                          retry_delay: int) -> bool:
    """使用LLM进行决策。"""
    messages = [
        {"role": "system", "content": "您是一位数据标准化专家。请严格按照要求仅回答 'YES' 或 'NO'。"},
        {"role": "user", "content": prompt_text},
    ]
    last_exception = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                temperature=temperature
            )
            llm_response = response.choices[0].message.content.strip().upper()
            logger.info(f"    LLM 决策响应: {llm_response}")
            return "YES" in llm_response  # 稍微宽松的检查

        except (APITimeoutError, APIConnectionError) as e:
            last_exception = e
            logger.warning(f"LLM决策失败 (尝试 {attempt + 1}/{max_retries}): {e}。将在 {retry_delay}秒后重试...")
            time.sleep(retry_delay)
        except APIStatusError as e:
            last_exception = e
            logger.error(f"LLM决策失败 (尝试 {attempt + 1}/{max_retries}): HTTP {e.status_code} - {e.response}")
            if 400 <= e.status_code < 500 and e.status_code != 429:
                logger.error("客户端错误，取消重试。")
                break
            time.sleep(retry_delay)
        except Exception as e:
            last_exception = e
            logger.error(f"LLM决策发生未知错误: {e}")
            break

    logger.error(f"LLM决策最终失败: {last_exception}")
    return False


def load_manufacturers_with_embeddings() -> List[Dict]:
    """加载预计算的嵌入向量 (带锁)"""
    lock_path = PRECOMPUTED_EMBEDDINGS_FILE.with_suffix(".json.lock")
    with FileLock(lock_path):
        if not PRECOMPUTED_EMBEDDINGS_FILE.exists():
            return []
        try:
            with open(PRECOMPUTED_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
                manufacturers = json.load(f)
                return [m for m in manufacturers if all(k in m for k in ["embedding", "text_for_embedding", "name"])]
        except (json.JSONDecodeError, TypeError):
            return []


def add_new_manufacturer_to_standards_file(new_mfg_name: str) -> Dict:
    """将新发现的厂商添加回标准库 (带锁)"""
    lock_path = STANDARD_MANUFACTURERS_FILE.with_suffix(".json.lock")
    with FileLock(lock_path):
        manufacturers = []
        if STANDARD_MANUFACTURERS_FILE.exists():
            try:
                with open(STANDARD_MANUFACTURERS_FILE, 'r', encoding='utf-8') as f:
                    manufacturers = json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"标准厂商文件 {STANDARD_MANUFACTURERS_FILE} 损坏，将创建新列表。")
                manufacturers = []

        if any(mfg.get('name', '').lower() == new_mfg_name.lower() for mfg in manufacturers):
            return next((mfg for mfg in manufacturers if mfg.get('name', '').lower() == new_mfg_name.lower()), None)

        new_mfg_id = f"mfg_auto_{uuid.uuid4().hex[:8]}"
        new_mfg_entry = {"id": new_mfg_id, "name": new_mfg_name, "source": "auto-added", "aliases": []}
        manufacturers.append(new_mfg_entry)

        with open(STANDARD_MANUFACTURERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(manufacturers, f, ensure_ascii=False, indent=2)
        return new_mfg_entry


def update_embeddings_file(full_data_list: List[Dict]):
    """更新嵌入向量文件 (带锁)"""
    lock_path = PRECOMPUTED_EMBEDDINGS_FILE.with_suffix(".json.lock")
    with FileLock(lock_path):
        with open(PRECOMPUTED_EMBEDDINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(full_data_list, f, ensure_ascii=False, indent=2)


def _find_and_replace_source_chunks_recursive(current_data_node, placeholder_map_list_ref):
    """(来自您的原始代码) 递归查找和替换 source_chunks"""
    if isinstance(current_data_node, dict):
        for key, value in list(current_data_node.items()):
            if key == "source_chunks" and isinstance(value, list):
                placeholder_str_unquoted = f"__SC_PLACEHOLDER_{uuid.uuid4().hex}__"
                # 确保 chunk ID 是字符串
                compact_str = json.dumps([str(v) for v in value], ensure_ascii=False, separators=(',', ':'))
                placeholder_map_list_ref.append((json.dumps(placeholder_str_unquoted), compact_str))
                current_data_node[key] = placeholder_str_unquoted
            elif isinstance(value, (dict, list)):
                _find_and_replace_source_chunks_recursive(value, placeholder_map_list_ref)
    elif isinstance(current_data_node, list):
        for i, item in enumerate(current_data_node):
            if isinstance(item, (dict, list)):
                _find_and_replace_source_chunks_recursive(item, placeholder_map_list_ref)


def save_json_preserving_source_chunks(device_data_orig, output_filepath, filename_for_logging):
    """(来自您的原始代码) 保存JSON，同时压缩 source_chunks"""
    device_data_copy = copy.deepcopy(device_data_orig)
    placeholder_replacements = []

    try:
        _find_and_replace_source_chunks_recursive(device_data_copy, placeholder_replacements)
        if placeholder_replacements:
            logger.debug(
                f"  为 '{filename_for_logging}' 找到了 {len(placeholder_replacements)} 个 'source_chunks' 实例进行特殊格式化。")
    except Exception as e:
        logger.warning(f"  递归替换 'source_chunks' 时出错 ({filename_for_logging}): {e}")
        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                json.dump(device_data_orig, f, ensure_ascii=False, indent=2)
            logger.info(f"  已保存结果到 (标准格式，source_chunks替换失败): {output_filepath}")
        except Exception as e_save_orig:
            logger.error(f"  保存原始数据到 '{output_filepath}' 也失败: {e_save_orig}")
        return

    try:
        formatted_json_string = json.dumps(device_data_copy, ensure_ascii=False, indent=2)
        for quoted_placeholder, compact_str in placeholder_replacements:
            if quoted_placeholder in formatted_json_string:
                formatted_json_string = formatted_json_string.replace(quoted_placeholder, compact_str)
            else:
                logger.warning(
                    f"  未能找到 'source_chunks' 的占位符 '{quoted_placeholder}' 在格式化后的JSON中 ({filename_for_logging})。")

        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(formatted_json_string)
        logger.info(f"  已保存结果到: {output_filepath}")

    except Exception as e:
        logger.error(f"  保存文件 '{output_filepath}' 时出错: {e}")


# --- 主协调函数 (供 Celery 调用) ---

def process_manufacturer_standardization(
        results_dir_path: str,
        llm_config: Dict[str, Any],
        embedding_config: Dict[str, Any],
        standardization_config: Dict[str, Any]
):
    """
    处理 resolved_with_images 目录下的所有文件，进行制造商标准化，
    并将结果保存到 manufacturer_standardized 目录。
    """
    input_dir = Path(results_dir_path) / "param_results" / "resolved_with_images"
    logger.info(f"开始制造商标准化流程 (阶段8)，输入目录: {input_dir}")
    output_dir = Path(results_dir_path) / "param_results" / "manufacturer_standardized"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 初始化所有需要的API客户端
    try:
        llm_client = OpenAI(api_key=llm_config["api_key"], base_url=llm_config["base_url"])
        embedding_client = OpenAI(api_key=embedding_config["api_key"], base_url=embedding_config["base_url"])
        logger.info(f"LLM({llm_config['model_name']}) 和 Embedding({embedding_config['model_name']}) 客户端初始化成功。")
    except Exception as e:
        logger.error(f"初始化OpenAI客户端失败: {e}")
        raise  # 抛出异常以使 Celery 任务失败

    # 2. 加载共享的、带锁的制造商知识库
    standard_manufacturers_data = load_manufacturers_with_embeddings()
    # texts_for_matching = [mfg['text_for_embedding'] for mfg in standard_manufacturers_data]
    standard_mfg_embeddings_np = np.array(
        [mfg['embedding'] for mfg in standard_manufacturers_data if mfg.get("embedding")]
    ) if standard_manufacturers_data else np.array([])
    # 过滤掉加载失败的条目
    standard_manufacturers_data = [m for m in standard_manufacturers_data if m.get("embedding")]

    logger.info(f"已加载 {len(standard_manufacturers_data)} 条带嵌入的标准制造商信息。")

    # 3. 核心处理逻辑
    total_files_processed = 0
    total_manufacturers_updated = 0
    total_new_manufacturers_added = 0
    generated_files = []

    json_files_to_process = sorted(list(input_dir.glob("*.json")))

    for filepath in json_files_to_process:
        try:
            # (*** BUG 修复 ***)
            # 此处调用 load_json_file
            device_data = load_json_file(filepath)
            if not device_data:
                logger.warning(f"跳过空文件或无法解析的文件: {filepath.name}")
                continue

            logger.info(f"--- 正在处理文件: {filepath.name} ---")
            total_files_processed += 1

            # (从 get_device_param_files_and_names 移植逻辑)
            device_name = "未知设备"
            if "Device" in device_data:
                device_info = device_data["Device"]
                if isinstance(device_info, dict):
                    name_value = device_info.get("name") or device_info.get("Name")
                    if isinstance(name_value, str):
                        device_name = name_value
                    elif isinstance(name_value, list) and name_value and isinstance(name_value[0], dict):
                        device_name = name_value[0].get("value", "未知设备")

            manufacturer_info = device_data.get("Manufacturer")
            original_mfg_name = None
            can_process_mfg = False

            # 提取原始制造商名称
            if isinstance(manufacturer_info, dict):
                name_list = manufacturer_info.get("Name")  # 在阶段6后，键名应该是大写的 'Name'
                if isinstance(name_list, list) and name_list:
                    name_entry = name_list[0]  # 取第一个值
                    if isinstance(name_entry, dict) and "value" in name_entry:
                        original_mfg_name = name_entry.get("value")
                        if original_mfg_name and isinstance(original_mfg_name, str):
                            can_process_mfg = True

            if not can_process_mfg:
                logger.warning(f"设备 '{device_name}' ({filepath.name}) 无有效厂商名，跳过标准化。")
                save_json_preserving_source_chunks(device_data, output_dir / filepath.name, filepath.name)
                generated_files.append(filepath.name)
                continue

            logger.info(f"设备: '{device_name}', 提取原始厂商: '{original_mfg_name}'")

            # 获取嵌入向量
            extracted_mfg_embedding = get_embedding(
                original_mfg_name,
                embedding_client,
                embedding_config["model_name"],
                embedding_config["dimensions"]
            )
            if not extracted_mfg_embedding:
                logger.warning(f"无法获取 '{original_mfg_name}' 的嵌入，跳过标准化。")
                save_json_preserving_source_chunks(device_data, output_dir / filepath.name, filepath.name)
                generated_files.append(filepath.name)
                continue

            # 进行相似度匹配
            mfg_name_to_update_to = original_mfg_name
            update_reason = "原始名称，未找到匹配项或无需更改。"

            if standard_mfg_embeddings_np.size > 0:
                similarities = cosine_similarity(
                    np.array(extracted_mfg_embedding).reshape(1, -1),
                    standard_mfg_embeddings_np
                )[0]
                best_match_index = np.argmax(similarities)
                max_similarity_score = similarities[best_match_index]

                matched_entry = standard_manufacturers_data[best_match_index]
                text_that_matched = matched_entry.get('text_for_embedding')
                canonical_name_for_replacement = matched_entry.get('name')

                logger.info(
                    f"最佳嵌入匹配: '{text_that_matched}' (规范名: '{canonical_name_for_replacement}', 相似度: {max_similarity_score:.4f})")

                # 决策逻辑
                if text_that_matched.lower() == original_mfg_name.lower():
                    mfg_name_to_update_to = canonical_name_for_replacement
                    update_reason = f"精确匹配，标准化为 '{canonical_name_for_replacement}'"
                else:
                    # 使用LLM决策
                    prompt = get_manufacturer_standardization_prompt(
                        original_mfg_name,
                        text_that_matched,
                        canonical_name_for_replacement,
                        max_similarity_score
                    )
                    if call_llm_for_decision(
                            prompt,
                            llm_client,
                            llm_config["model_name"],
                            0.1,  # 低温
                            standardization_config["MAX_LLM_RETRIES"],
                            standardization_config["RETRY_DELAY_SECONDS"]
                    ):
                        mfg_name_to_update_to = canonical_name_for_replacement
                        update_reason = f"LLM确认与 '{text_that_matched}' 一致, 标准化为 '{canonical_name_for_replacement}'"
                    else:
                        update_reason = f"LLM判断与 '{text_that_matched}' 不一致"

            # 如果最终决定不替换为现有标准，则将当前名称添加为新标准
            if mfg_name_to_update_to == original_mfg_name and (
                    not standard_manufacturers_data or original_mfg_name not in [m['name'] for m in
                                                                                 standard_manufacturers_data]):

                logger.info(f"尝试将 '{original_mfg_name}' 添加为新标准制造商...")
                new_standard_entry = add_new_manufacturer_to_standards_file(original_mfg_name)

                if new_standard_entry:
                    new_embedding_obj = {
                        **new_standard_entry,
                        "text_for_embedding": original_mfg_name,
                        "embedding": extracted_mfg_embedding
                    }
                    standard_manufacturers_data.append(new_embedding_obj)
                    update_embeddings_file(standard_manufacturers_data)  # 持久化到文件

                    # 更新内存中的np数组以供后续文件使用
                    standard_mfg_embeddings_np = np.vstack([
                        standard_mfg_embeddings_np,
                        np.array(extracted_mfg_embedding).reshape(1, -1)
                    ]) if standard_mfg_embeddings_np.size > 0 else np.array(extracted_mfg_embedding).reshape(1, -1)

                    total_new_manufacturers_added += 1

            # 更新JSON数据并保存
            if mfg_name_to_update_to != original_mfg_name:
                logger.info(f"更新厂商: '{original_mfg_name}' -> '{mfg_name_to_update_to}'")
                device_data["Manufacturer"]["Name"][0]["value"] = mfg_name_to_update_to
                device_data["Manufacturer"]["Name"][0]["standardization_reason"] = update_reason
                device_data["Manufacturer"]["Name"][0]["original_value_before_standardization"] = original_mfg_name
                total_manufacturers_updated += 1
            else:
                device_data["Manufacturer"]["Name"][0]["standardization_notes"] = update_reason

            output_filepath = output_dir / filepath.name
            save_json_preserving_source_chunks(device_data, output_filepath, filepath.name)
            generated_files.append(filepath.name)

        except Exception as e:
            logger.error(f"处理文件 {filepath.name} 时发生未知错误: {e}", exc_info=True)

    logger.info(f"--- 阶段8处理总结 ---")
    logger.info(f"总共处理文件数: {total_files_processed}")
    logger.info(f"标准化替换的厂商数量: {total_manufacturers_updated}")
    logger.info(f"新增到标准库的厂商数量: {total_new_manufacturers_added}")
    logger.info(f"阶段8 (厂商标准化) 完成。")