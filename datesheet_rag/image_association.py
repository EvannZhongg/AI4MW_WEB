# pdf_parser/image_association.py

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
from .prompts import get_image_title_generation_prompt, get_image_association_prompt

logger = logging.getLogger(__name__)


# --- 辅助函数 (Helpers) ---

def clean_model_name(name: str) -> str:
    """移除名称中的所有空格并转为小写以便不区分大小写比较"""
    if not isinstance(name, str):
        return ""
    return name.replace(" ", "").lower()


def load_json_file(file_path: Path) -> Any:
    """加载JSON文件"""
    if not file_path.exists():
        logger.warning(f"JSON文件 {file_path} 未找到。")
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"JSON文件 {file_path} 格式无效。")
        return None
    except Exception as e:
        logger.error(f"读取JSON文件 {file_path} 时发生错误: {e}")
        return None


def save_json_file(data: Dict, file_path: Path):
    """
    保存数据到JSON文件, 特殊处理 'source_chunks' 字段以保持单行。
    (此函数来自您的原始代码)
    """
    data_to_save = copy.deepcopy(data)
    placeholders = {}

    def find_and_replace_chunks(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "source_chunks" and isinstance(value, list):
                    # 确保 source_chunks 列表中的ID是字符串
                    str_chunks = [str(item) for item in value]
                    placeholder = f"__SOURCE_CHUNKS_{uuid.uuid4().hex}__"
                    # 转换列表为紧凑的JSON字符串
                    placeholders[placeholder] = json.dumps(str_chunks)
                    obj[key] = placeholder
                else:
                    find_and_replace_chunks(value)
        elif isinstance(obj, list):
            for item in obj:
                find_and_replace_chunks(item)

    find_and_replace_chunks(data_to_save)
    pretty_json_string = json.dumps(data_to_save, ensure_ascii=False, indent=2)

    # 替换占位符
    for placeholder, single_line_list in placeholders.items():
        # 确保占位符被正确替换 (带引号)
        pretty_json_string = pretty_json_string.replace(f'"{placeholder}"', single_line_list)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(pretty_json_string)
    except Exception as e:
        logger.error(f"保存JSON文件 {file_path} 失败：{e}")


def get_device_param_files_and_names(params_dir: Path) -> tuple[Dict[str, Path], List[str]]:
    """
    获取所有 "resolved" 参数JSON文件路径及其器件型号名称。
    (已更新以解析阶段6.2的JSON结构)
    """
    param_files_map, all_device_names = {}, []
    if not params_dir.is_dir():
        logger.error(f"参数目录 {params_dir} 不存在。")
        return param_files_map, all_device_names

    for file_path in params_dir.glob("*_resolved_llm.json"):  # 确保只读取resolved文件
        param_data = load_json_file(file_path)
        device_name = None

        if param_data and "Device" in param_data:
            device_info = param_data["Device"]
            if isinstance(device_info, dict):
                # 阶段6.2 细化后, "name" 字段是一个列表
                name_value_list = device_info.get("name") or device_info.get("Name")

                if isinstance(name_value_list, list) and name_value_list:
                    # 格式: [{"value": "ModelName", "source_chunks": [...]}]
                    first_entry = name_value_list[0]
                    if isinstance(first_entry, dict) and "value" in first_entry:
                        device_name = first_entry["value"]
                elif isinstance(name_value_list, str):
                    # 兼容旧格式或单型号格式
                    device_name = name_value_list

        if device_name:
            param_files_map[device_name] = file_path
            all_device_names.append(device_name)
        else:
            logger.warning(f"文件 {file_path} 中未找到有效的 'Device.name' 结构。")

    return param_files_map, all_device_names


# --- LLM 调用函数 ---

def _call_llm_with_retry(client, model_name, messages, max_retries, retry_delay, description_for_log):
    """带重试逻辑的LLM API调用封装"""
    last_exception = None
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.1,  # 使用较低的温度以获得更确定的结果
            )
            return completion.choices[0].message.content.strip()
        except (APITimeoutError, APIConnectionError) as e:
            last_exception = e
            logger.warning(
                f"LLM调用 ({description_for_log}) 失败 (尝试 {attempt + 1}/{max_retries}): {e}。将在 {retry_delay}秒后重试...")
            time.sleep(retry_delay)
        except APIStatusError as e:
            last_exception = e
            logger.error(
                f"LLM调用 ({description_for_log}) 失败 (尝试 {attempt + 1}/{max_retries}): HTTP {e.status_code} - {e.response}")
            if 400 <= e.status_code < 500 and e.status_code != 429:
                logger.error("客户端错误，取消重试。")
                break  # 不要重试4xx系列错误（除了速率限制）
            time.sleep(retry_delay)
        except Exception as e:
            last_exception = e
            logger.error(f"LLM调用 ({description_for_log}) 发生未知错误: {e}")
            break  # 未知错误，停止

    logger.error(f"LLM调用 ({description_for_log}) 最终失败: {last_exception}")
    return None


def generate_title_from_description_llm(client, model_name, image_id, image_description, max_retries, retry_delay):
    """使用LLM从图片描述生成标题"""
    if not image_description or not image_description.strip():
        logger.info(f"图片ID {image_id} 描述为空，无法生成标题。")
        return None

    prompt = get_image_title_generation_prompt(image_description)
    messages = [
        {"role": "system", "content": "你是一个文本摘要和标题生成助手。"},
        {"role": "user", "content": prompt}
    ]

    logger.info(f"--- 为图片ID {image_id} 根据描述生成标题 ---")
    generated_title_raw = _call_llm_with_retry(client, model_name, messages, max_retries, retry_delay,
                                               f"TitleGen ID {image_id}")

    if generated_title_raw:
        # 清理标题，移除不适合做JSON键的字符，并限制长度
        generated_title = generated_title_raw.replace('"', '').replace(":", " ").replace("/", " ").replace("\\", " ")
        generated_title = re.sub(r'\s+', ' ', generated_title)  # 替换多个空格为单个
        if len(generated_title) > 100:
            generated_title = generated_title[:100] + "..."
        logger.info(f"LLM为图片ID {image_id} 生成的标题: '{generated_title}'")
        return generated_title if generated_title else None

    return None


def get_llm_decision_for_image_association(client, model_name, image_info, all_device_names, max_retries, retry_delay):
    """
    使用LLM判断图片属于哪些器件型号。
    返回一个器件型号名称的列表。
    """
    image_id_for_log = image_info.get("source_chart_image", "N/A")  # 使用文件名作为ID

    prompt = get_image_association_prompt(
        image_title=image_info.get("title", "N/A"),
        image_description=image_info.get("description", "N/A"),
        image_applicable_models=image_info.get("applicable_models", []),
        all_device_names=all_device_names,
        image_id_for_log=image_id_for_log
    )

    messages = [
        {"role": "system",
         "content": "您是一位电子元器件数据手册分析专家，请严格按照纯JSON列表格式输出您的判断结果，不要包含任何Markdown标记或解释性文本。"},
        {"role": "user", "content": prompt}
    ]

    logger.info(f"--- 为图片 {image_id_for_log} 请求LLM决策图片关联 ---")
    response_content = _call_llm_with_retry(client, model_name, messages, max_retries, retry_delay,
                                            f"Assoc ID {image_id_for_log}")

    if not response_content:
        return []

    relevant_devices = []
    try:
        # 增强解析能力，以处理 ```json ... ``` 或 ``` ... ``` 块
        if response_content.startswith("```json"):
            match = re.search(r"```json\s*\n?(.*?)\n?```", response_content, re.DOTALL)
            if match:
                response_content = match.group(1).strip()
            else:  # 回退
                response_content = "\n".join(response_content.splitlines()[1:-1]).strip()
        elif response_content.startswith("```") and response_content.endswith("```"):
            response_content = "\n".join(response_content.splitlines()[1:-1]).strip()

        # 确保 response_content 是一个列表
        if not response_content.startswith('['):
            # 尝试从字典中提取
            data = json.loads(response_content)
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        response_content = json.dumps(value)
                        logger.info(f"从LLM响应的字典中提取到列表 (图片 {image_id_for_log})")
                        break
            else:
                raise json.JSONDecodeError("LLM返回的不是列表或字典", response_content, 0)

        decision_data = json.loads(response_content)
        if isinstance(decision_data, list):
            relevant_devices = decision_data
        else:
            logger.warning(f"LLM返回的不是预期的JSON列表 (图片 {image_id_for_log})。响应: {response_content}")

    except json.JSONDecodeError as e:
        logger.error(f"无法解析LLM的JSON关联响应 (图片 {image_id_for_log}): {response_content}。错误: {e}")

    # 验证LLM返回的名称是否在我们的已知列表中
    valid_relevant_devices = [name for name in relevant_devices if name in all_device_names]
    if len(valid_relevant_devices) != len(relevant_devices):
        invalid_names = [name for name in relevant_devices if name not in all_device_names]
        logger.warning(
            f"LLM关联响应 (图片 {image_id_for_log}) 中包含未知/无效的器件型号, 已被过滤。无效型号: {invalid_names}")

    return valid_relevant_devices


# --- 主协调函数 (供 Celery 调用) ---

def process_image_association(
        results_dir_path: str,
        llm_config: Dict[str, Any],
        assoc_config: Dict[str, Any]
):
    """
    读取 image_descriptions 和 resolved 参数文件, 将图片信息关联并注入,
    最终保存到 'resolved_with_images' 目录。
    """
    logger.info(f"开始图片关联流程 (阶段7)，根目录: {results_dir_path}")

    # 1. 动态设置路径
    output_dir = Path(results_dir_path)
    image_json_path = output_dir / "image_descriptions.json"
    params_dir_resolved = output_dir / "param_results" / "resolved"
    params_dir_target = output_dir / "param_results" / "resolved_with_images"
    params_dir_target.mkdir(parents=True, exist_ok=True)

    # 2. 初始化 LLM 客户端和加载数据
    try:
        client = OpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config["base_url"]
        )
        model_name = llm_config["model_name"]
        max_retries = assoc_config.get("MAX_RETRIES", 3)
        retry_delay = assoc_config.get("RETRY_DELAY_SECONDS", 5)
        logger.info(f"OpenAI客户端初始化成功，使用模型: {model_name}")
    except Exception as e:
        logger.error(f"初始化OpenAI客户端失败: {e}")
        raise  # 抛出异常以使 Celery 任务失败

    images_data = load_json_file(image_json_path)
    if not images_data:
        msg = f"无法加载或内容为空: {image_json_path}。跳过图片关联。";
        logger.warning(msg)
        # 不认为是关键错误，允许流程继续（但不会有关联）
        return

    param_files_map, all_device_names = get_device_param_files_and_names(params_dir_resolved)
    if not all_device_names:
        msg = f"未从目录 {params_dir_resolved} 提取到任何设备。跳过图片关联。";
        logger.warning(msg)
        # 同上，不认为是关键错误
        return

    # 3. 核心处理逻辑 (预加载所有器件数据)
    all_device_data = {}
    for device_name, file_path in param_files_map.items():
        data = load_json_file(file_path)
        if data:
            all_device_data[device_name] = data

    # 4. 遍历图片，并将信息注入到已加载的数据中
    for image_info in images_data:
        # image_info 格式来自 VLM (见 VLM_Client.py):
        # { "classification": "...", "title": "...", "description": "...",
        #   "applicable_models": [...], "source_chart_image": "...", "source_page_image": "..." }

        image_abs_path = image_info.get("source_chart_image")  # <--- 关键更改：获取绝对路径
        image_id_for_log = Path(image_abs_path or f"UnknownID_{uuid.uuid4().hex[:6]}").name
        image_description_raw = image_info.get("description", "")

        logger.info(f"--- 开始处理图片: {image_id_for_log} ---")

        classification = image_info.get("classification", "Else").lower()
        if classification == "else" or classification == "company_logo":
            logger.info(f"图片 {image_id_for_log} 分类为 '{classification}'，跳过处理。")
            continue

        if not image_abs_path:
            logger.warning(f"图片 {image_id_for_log} 缺少 'source_chart_image' 绝对路径，跳过。")
            continue

        image_key = image_info.get("title")
        if not image_key or image_key.strip().lower() == "none":
            logger.info(f"图片 {image_id_for_log} 标题为 'none'，将尝试使用LLM生成。")
            image_key = generate_title_from_description_llm(client, model_name, image_id_for_log, image_description_raw,
                                                            max_retries, retry_delay)
            if not image_key:
                image_key = f"Untitled_Image_{image_id_for_log[:10]}";  # 使用部分文件名作为备用
                logger.warning(f"无法为图片 {image_id_for_log} 生成标题，使用备用标题: '{image_key}'")
        else:
            # 清理已有的标题
            image_key = re.sub(r'\s+', ' ',
                               image_key.strip().replace('"', '').replace(":", " ").replace("/", " ").replace("\\",
                                                                                                              " "))[
                        :100]

        # 确定图片关联的设备列表
        relevant_device_names_for_image = []
        image_applicable_models = image_info.get("applicable_models", [])

        if image_applicable_models and isinstance(image_applicable_models, list):
            cleaned_all_device_names_map = {clean_model_name(name): name for name in all_device_names}
            matched_names = set()

            for model_in_image_raw in image_applicable_models:
                # 检查 "all" 关键字
                if clean_model_name(model_in_image_raw) == "all":
                    matched_names.update(all_device_names)
                    logger.info(f"图片 {image_id_for_log} 标记为 'all'，关联所有 {len(all_device_names)} 个设备。")
                    break  # 找到 'all'，无需再检查其他

                cleaned_model_in_image = clean_model_name(model_in_image_raw)

                # 1. 精确匹配
                if cleaned_model_in_image in cleaned_all_device_names_map:
                    matched_names.add(cleaned_all_device_names_map[cleaned_model_in_image])

                # 2. 检查 VLM 模型是否为系列名 (例如 VLM 返回 "ABC", 我们有 "ABC-01", "ABC-02")
                for cleaned_known_name, known_name in cleaned_all_device_names_map.items():
                    if cleaned_known_name.startswith(cleaned_model_in_image):
                        matched_names.add(known_name)

            if matched_names:
                relevant_device_names_for_image = sorted(list(matched_names))

        if not relevant_device_names_for_image:
            # 如果VLM没有提供有用的 applicable_models，或者文档只有一个型号
            if len(all_device_names) == 1:
                logger.info(f"文档只有一个设备，图片 {image_id_for_log} 自动关联到: {all_device_names[0]}")
                relevant_device_names_for_image = all_device_names
            else:
                # VLM没提供，且有多个设备，求助于LLM决策
                logger.info(f"图片 {image_id_for_log} 的适用型号列表为空或未匹配，且文档有多个设备。求助于LLM决策...")
                relevant_device_names_for_image = get_llm_decision_for_image_association(
                    client, model_name, image_info, all_device_names, max_retries, retry_delay
                )

        # 将图片信息注入到对应的器件数据中
        if relevant_device_names_for_image:
            logger.info(
                f"图片 {image_id_for_log} (JSON键: '{image_key}') 将关联到器件: {relevant_device_names_for_image}")

            # 提取页码 (从 page_X.png 或 page_X_...png)
            page_num = "N/A"
            page_match = re.search(r'page_(\d+)', image_info.get("source_page_image", ""))
            if not page_match:
                page_match = re.search(r'page_(\d+)', image_info.get("source_chart_image", ""))
            if page_match:
                page_num = page_match.group(1)

            for device_name in relevant_device_names_for_image:
                if device_name in all_device_data:
                    current_device_data = all_device_data[device_name]
                    # 确保 "Image" 部分存在
                    image_section = current_device_data.setdefault("Image", {})
                    # 键是标题，值是列表
                    image_list = image_section.setdefault(image_key, [])

                    # 构造要注入的对象
                    image_entry = {
                        "value": image_abs_path,  # <--- 关键更改：使用绝对路径
                        "description": image_description_raw,
                        "page_number": page_num,
                        "classification": image_info.get("classification", "Else")
                    }

                    # 检查是否已存在（防止重复注入）
                    if not any(entry.get("value") == image_abs_path for entry in image_list):
                        image_list.append(image_entry)
                else:
                    logger.warning(f"器件型号 '{device_name}' (针对图片 {image_id_for_log}) 在预加载的数据中未找到。")
        else:
            logger.info(f"图片 {image_id_for_log} 未关联到任何器件。")

    # 5. 保存修改后的数据
    generated_files_count = 0
    if all_device_data:
        for device_name, data_to_save in all_device_data.items():
            # 从原始映射中获取文件名
            if device_name not in param_files_map:
                logger.warning(f"在 param_files_map 中找不到 {device_name} 的原始文件名，跳过保存。")
                continue

            base_filename = param_files_map[device_name].name
            output_file_path = params_dir_target / base_filename
            save_json_file(data_to_save, output_file_path)
            generated_files_count += 1
            logger.info(f"已保存带有关联图片信息的JSON: {output_file_path.name}")

    logger.info(f"图片关联阶段 (阶段7) 完成。共保存 {generated_files_count} 个文件。")