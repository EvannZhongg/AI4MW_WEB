# pdf_parser/classification.py

import json
import logging
import re
import copy
import uuid
import time
from pathlib import Path
from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
from typing import List, Dict, Any
from django.conf import settings
from .prompts import get_classification_prompt  # <--- 从 prompts.py 导入

logger = logging.getLogger(__name__)

# --- 动态、安全地定义文件路径 ---
DATA_DIR = Path(__file__).resolve().parent / "data"
TAXONOMY_PATH = DATA_DIR / "device_classification.json"
COMPACT_KEYS = {'source_chunks'}


# === 辅助函数 ===

def load_json_file(file_path: Path) -> Any:
    """加载JSON文件"""
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


def save_json_with_compact_lists(data, filepath, compact_keys, indent=2, ensure_ascii=False):
    """
    (来自您的代码)
    使用占位符策略，将JSON数据写入文件，同时保持特定键的列表为紧凑格式。
    """
    data_copy = copy.deepcopy(data)
    placeholders = {}

    def _walk_and_replace(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in compact_keys and isinstance(value, list):
                    placeholder = f"__PLACEHOLDER_{uuid.uuid4().hex}__"
                    placeholders[placeholder] = json.dumps([str(v) for v in value], separators=(',', ':'),
                                                           ensure_ascii=False)
                    obj[key] = placeholder
                else:
                    _walk_and_replace(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk_and_replace(item)

    _walk_and_replace(data_copy)
    pretty_string = json.dumps(data_copy, indent=indent, ensure_ascii=ensure_ascii)

    for placeholder, compact_list_str in placeholders.items():
        pretty_string = pretty_string.replace(f'"{placeholder}"', compact_list_str)

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(pretty_string)


def get_device_context(device_data: Dict) -> str:
    """(来自您的代码) 提取用于分类的上下文"""
    info = device_data.get('Basic information', {})
    info_lower_keys = {k.lower(): v for k, v in info.items()}

    # 提取值 (假设它们是经过细化后的列表)
    description_list = info_lower_keys.get('description', [{}])
    function_list = info_lower_keys.get('function', [{}])
    applications_list = info_lower_keys.get('applications', [{}])

    description = description_list[0].get('value', '') if description_list else ''
    function = function_list[0].get('value', '') if function_list else ''
    applications = applications_list[0].get('value', '') if applications_list else ''

    return f"器件描述: {description}\n功能: {function}\n应用领域: {applications}"


def get_llm_classification_choice(
        client: OpenAI,
        model: str,
        context: str,
        level_name: str,
        options_list: List,
        max_retries: int,
        retry_delay: int,
        previous_choices: Dict = None
) -> str:
    """(重构自您的代码) 带重试和验证的LLM调用"""

    prompt = get_classification_prompt(context, level_name, options_list, previous_choices)
    messages = [{"role": "user", "content": prompt}]
    last_exception = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=50
            )
            choice = response.choices[0].message.content.strip()

            # 1. 精确匹配
            if choice in options_list:
                return choice

            # 2. 模糊匹配 (处理LLM可能添加的标点或包装)
            logger.warning(f"LLM返回了不在选项中的值 '{choice}'。将进行模糊匹配。")
            choice_lower = choice.lower()
            for option in options_list:
                if choice_lower in option.lower() or option.lower() in choice_lower:
                    logger.info(f"模糊匹配成功: '{choice}' -> '{option}'")
                    return option

            logger.error(f"模糊匹配失败: 无法将'{choice}'匹配到任何选项。")
            last_exception = Exception(f"LLM choice '{choice}' not in options and failed fuzzy match.")

        except (APITimeoutError, APIConnectionError) as e:
            last_exception = e
            logger.warning(f"LLM分类失败 (尝试 {attempt + 1}/{max_retries}): {e}。将在 {retry_delay}秒后重试...")
            time.sleep(retry_delay)
        except APIStatusError as e:
            last_exception = e
            logger.error(f"LLM分类失败 (尝试 {attempt + 1}/{max_retries}): HTTP {e.status_code} - {e.response}")
            if 400 <= e.status_code < 500 and e.status_code != 429:
                break
            time.sleep(retry_delay)
        except Exception as e:
            last_exception = e
            logger.error(f"LLM分类发生未知错误: {e}")
            break

    logger.error(f"LLM分类最终失败: {last_exception}")
    return None


def process_device_file(file_path: Path, client: OpenAI, model: str, taxonomy: Dict, max_retries: int,
                        retry_delay: int) -> Dict:
    """(重构自您的代码) 处理单个文件"""
    logger.info(f"--- 正在分类文件: {file_path.name} ---")
    device_data = load_json_file(file_path)
    if not device_data:
        logger.error(f"读取或解析JSON文件 '{file_path}' 失败。")
        return None

    context = get_device_context(device_data)

    # Level 1
    level_1_options = list(taxonomy.keys())
    level_1_choice = get_llm_classification_choice(
        client, model, context, "一级分类", level_1_options, max_retries, retry_delay
    )
    if not level_1_choice: return None

    # Level 2
    level_2_options = list(taxonomy.get(level_1_choice, {}).keys())
    if not level_2_options:
        logger.warning(f"在 '{level_1_choice}' 下无二级分类。")
        return None
    level_2_choice = level_2_options[0] if len(level_2_options) == 1 else get_llm_classification_choice(
        client, model, context, "二级分类", level_2_options, max_retries, retry_delay,
        {"一级分类": level_1_choice}
    )
    if not level_2_choice: return None

    # Level 3
    level_3_options = taxonomy.get(level_1_choice, {}).get(level_2_choice, [])
    if not level_3_options:
        logger.warning(f"在 '{level_1_choice} -> {level_2_choice}' 下无三级分类。")
        return None
    level_3_choice = level_3_options[0] if len(level_3_options) == 1 else get_llm_classification_choice(
        client, model, context, "三级分类", level_3_options, max_retries, retry_delay,
        {"一级分类": level_1_choice, "二级分类": level_2_choice}
    )
    if not level_3_choice: return None

    # 注入新字段 (使用标准化的列表/字典结构)
    device_data['Category'] = {
        "level_1": [{"value": level_1_choice, "source_chunks": []}],
        "level_2": [{"value": level_2_choice, "source_chunks": []}],
        "level_3": [{"value": level_3_choice, "source_chunks": []}]
    }
    return device_data


# === 主协调函数 (供 Celery 调用) ===
def process_device_classification(
        results_dir_path: str,
        llm_config: Dict[str, Any],
        classification_config: Dict[str, Any]
):
    """
    (重构自您的代码)
    处理 manufacturer_standardized 目录下的所有文件，进行设备分类。
    """
    input_dir = Path(results_dir_path) / "param_results" / "manufacturer_standardized"
    logger.info(f"开始设备分类流程 (阶段9)，输入目录: {input_dir}")
    output_dir = Path(results_dir_path) / "param_results" / "classified_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 初始化客户端和加载分类体系
    try:
        client = OpenAI(api_key=llm_config["api_key"], base_url=llm_config["base_url"])
        model_name = llm_config["model_name"]
        max_retries = classification_config.get("MAX_LLM_RETRIES", 3)
        retry_delay = classification_config.get("RETRY_DELAY_SECONDS", 5)
        logger.info(f"LLM客户端初始化成功，使用模型: {model_name}")
    except Exception as e:
        logger.error(f"初始化OpenAI客户端失败: {e}")
        raise  # 抛出异常以使 Celery 任务失败

    try:
        with open(TAXONOMY_PATH, 'r', encoding='utf-8') as f:
            taxonomy = json.load(f)
    except FileNotFoundError:
        logger.error(f"分类体系文件 '{TAXONOMY_PATH}' 未找到。")
        raise  # 关键文件缺失，任务失败
    except Exception as e:
        logger.error(f"加载分类体系文件失败: {e}")
        raise

    # 2. 查找并处理文件
    files_to_process = list(input_dir.glob('*.json'))
    if not files_to_process:
        logger.warning(f"在 '{input_dir}' 中没有找到需要处理的JSON文件。")
        return  # 没有文件不是一个错误

    logger.info(f"找到 {len(files_to_process)} 个待处理文件，结果将保存至 '{output_dir}'")

    success_count, fail_count = 0, 0
    generated_files = []

    for file_path in files_to_process:
        try:
            updated_data = process_device_file(file_path, client, model_name, taxonomy, max_retries, retry_delay)
            if updated_data:
                # 文件名保持与输入一致 (例如 UD1006FR_merged_resolved_llm.json)
                output_file_path = output_dir / file_path.name
                save_json_with_compact_lists(updated_data, output_file_path, COMPACT_KEYS)
                logger.info(f"处理成功: '{file_path.name}' -> 分类已保存至 '{output_file_path.name}'")
                success_count += 1
                generated_files.append(output_file_path.name)
            else:
                logger.error(f"处理文件 '{file_path.name}' 失败。")
                fail_count += 1
        except Exception as e:
            logger.error(f"处理文件 '{file_path.name}' 时发生未知异常: {e}", exc_info=True)
            fail_count += 1

    logger.info(f"批量分类完成。成功: {success_count}，失败: {fail_count}")
    if fail_count > 0:
        # 如果有任何文件失败，则抛出异常，以便Celery任务标记为失败
        raise Exception(f"阶段9中 {fail_count} 个文件分类失败。")