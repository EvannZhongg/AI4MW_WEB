# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/extraction.py

import os
import json
import logging
from time import sleep
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI, OpenAIError
from pathlib import Path
from typing import List, Dict, Any, Set
from .prompts import get_model_extraction_prompt

logger = logging.getLogger(__name__)


# === 辅助函数: 文本验证 ===
def validate_model_in_text(model_name, text):
    """
    验证 model_name 是否存在于 text 中。
    支持忽略空格和特殊字符（如 #）。
    """
    # 去除空格和特殊字符后进行匹配
    normalized_model = model_name.replace(" ", "").replace("#", "")
    normalized_text = text.replace(" ", "").replace("#", "")
    return normalized_model in normalized_text


# === 辅助函数: 紧凑 JSON ===
def custom_json_dump(obj, file):
    """自定义格式化输出：保留整体缩进，但让 chunk_ids 紧凑排列"""
    formatted_output = []
    for item in obj:
        model_name = item["model_name"]
        # 修复：确保 chunk_ids 是数字，然后转为字符串
        chunk_ids_str = f"[{','.join(map(str, item['chunk_ids']))}]"
        formatted_output.append(f'  {{"model_name": "{model_name}", "chunk_ids": {chunk_ids_str}}}')
    file.write("[\n" + ",\n".join(formatted_output) + "\n]")


# === 内部 LLM 调用函数 (Pass 1) ===
def _call_llm_for_extraction(
        client: OpenAI,
        model_config: Dict[str, Any],
        chunk: Dict[str, Any],
        max_retries: int
) -> Dict[str, Any]:
    """
    (Pass 1)
    仅负责调用 LLM 并返回原始结果，处理 API 和 JSON 级别的重试。
    不进行业务逻辑验证。
    """
    chunk_id = chunk["id"]
    text = chunk["text"]
    user_prompt = get_model_extraction_prompt()

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_config["model"],
                messages=[
                    {"role": "system",
                     "content": f"以下是电子器件数据手册中的一段 Markdown 文本（可能包含多个型号的名称，或仅仅是公共信息），用于分析：\n{text}"},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=model_config["temperature"],
                stream=False,
                response_format={"type": "json_object"}
            )
            output_text = response.choices[0].message.content.strip()

            usage = response.usage
            token_usage = {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
            }

            # 尝试解析 JSON
            result = json.loads(output_text)

            # API 调用和 JSON 解析均成功
            return {
                "chunk_id": chunk_id,
                "text": text,
                "llm_output": result,
                "token_usage": token_usage,
                "status": "success"
            }

        except json.JSONDecodeError:
            logger.warning(f"Chunk {chunk_id} 第 {attempt} 次尝试失败: 非法 JSON 格式: {output_text}")
            if attempt < max_retries:
                logger.info(f"🔄 Chunk {chunk_id} 尝试重新处理 (JSON 错误)...")
                sleep(3)  # 等待后重试
            else:
                logger.error(f"❌ Chunk {chunk_id} 最终失败: 非法 JSON 格式")
                return {"chunk_id": chunk_id, "text": text, "llm_output": None,
                        "token_usage": {"prompt": 0, "completion": 0}, "status": "json_error"}

        except OpenAIError as e:
            logger.warning(f"⚠️ Chunk {chunk_id} 第 {attempt} 次尝试失败: {e}")
            if attempt < max_retries:
                sleep(3)  # 等待后重试
            else:
                logger.error(f"❌ Chunk {chunk_id} 最终失败: OpenAI 错误")
                return {"chunk_id": chunk_id, "text": text, "llm_output": None,
                        "token_usage": {"prompt": 0, "completion": 0}, "status": "api_error"}

    # 循环结束（理论上不应到达这里）
    return {"chunk_id": chunk_id, "text": text, "llm_output": None, "token_usage": {"prompt": 0, "completion": 0},
            "status": "unknown_error"}


# --- 主协调函数 (供 Celery 调用) ---
def process_chunks_for_model_extraction(
        basic_chunk_path: str,
        results_dir: str,
        llm_config: Dict[str, Any],
        extraction_config: Dict[str, Any]
):
    """
    (已重构) 从 Celery 调用的主函数，协调所有型号抽取步骤。
    采用两阶段验证逻辑。
    """
    logger.info(f"开始型号抽取: {basic_chunk_path}")

    # 1. 准备配置和 Client
    max_workers = extraction_config.get("MAX_WORKERS", 5)
    max_retries = extraction_config.get("MAX_RETRIES", 3)

    client = OpenAI(
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"]
    )

    model_config = {
        "model": llm_config["model_name"],
        "temperature": extraction_config.get("TEMPERATURE", 0.0)
    }

    # 2. 读取 basic_chunk.json
    try:
        with open(basic_chunk_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        if not chunks:
            logger.warning(f"文件 {basic_chunk_path} 为空，跳过型号抽取。")
            return
    except Exception as e:
        logger.error(f"无法读取 {basic_chunk_path}: {e}")
        raise

    # 3. Pass 1: 并发执行 LLM 调用
    raw_llm_results = []
    total_prompt_tokens = 0
    total_completion_tokens = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_call_llm_for_extraction, client, model_config, chunk, max_retries): chunk
            for chunk in chunks
        }

        for future in as_completed(futures):
            raw_result = future.result()
            raw_llm_results.append(raw_result)
            total_prompt_tokens += raw_result["token_usage"]["prompt"]
            total_completion_tokens += raw_result["token_usage"]["completion"]

    # 4. Pass 2: 首次验证并构建“全局有效型号”列表
    all_valid_models_in_doc = set()
    chunks_to_revalidate = []
    validated_results = []  # 存储所有最终通过验证的结果

    logger.info("--- Pass 2a: 首次验证开始 ---")
    for result in raw_llm_results:
        if result["status"] != "success":
            logger.error(f"Chunk {result['chunk_id']} LLM 调用失败，状态: {result['status']}，已跳过。")
            continue

        chunk_id = result["chunk_id"]
        text = result["text"]
        llm_output = result["llm_output"]

        models_found = llm_output.get("models_found", [])
        possible_common = llm_output.get("possible_common", False)

        valid_models_in_chunk = []
        invalid_models_in_chunk = []

        for model_name in models_found:
            if validate_model_in_text(model_name, text):
                valid_models_in_chunk.append(model_name)
                all_valid_models_in_doc.add(model_name)  # 添加到全局列表
            else:
                invalid_models_in_chunk.append(model_name)

        if not invalid_models_in_chunk:
            # 此块 100% 验证通过
            logger.info(f"✅ Chunk {chunk_id} 首次验证通过。")
            validated_results.append({
                "chunk_id": chunk_id,
                "models_found": valid_models_in_chunk,
                "possible_common": possible_common
            })
        else:
            # 此块需要进入 Pass 2b 重新验证
            logger.warning(f"⚠️ Chunk {chunk_id} 首次验证失败，提取的 {invalid_models_in_chunk} 未在文本中找到。")
            chunks_to_revalidate.append({
                "chunk_id": chunk_id,
                "text": text,
                "llm_output": llm_output,
                "valid_models": valid_models_in_chunk,  # 已验证的
                "invalid_models": invalid_models_in_chunk  # 待交叉验证的
            })

    logger.info(f"--- Pass 2b: 交叉验证开始 (全局有效型号: {all_valid_models_in_doc}) ---")

    for failed_chunk in chunks_to_revalidate:
        chunk_id = failed_chunk["chunk_id"]
        llm_output = failed_chunk["llm_output"]
        final_valid_models = list(failed_chunk["valid_models"])  # 从已验证的开始

        still_invalid_models = []

        for invalid_model in failed_chunk["invalid_models"]:
            if invalid_model in all_valid_models_in_doc:
                # 优化成功：模型在当前块不存在，但在文档别处存在
                final_valid_models.append(invalid_model)
            else:
                # 真正的幻觉：模型在文档任何地方都不存在
                still_invalid_models.append(invalid_model)

        if not still_invalid_models:
            # 所有模型都通过了交叉验证
            logger.info(f"✅ Chunk {chunk_id} 交叉验证通过。")
            validated_results.append({
                "chunk_id": chunk_id,
                "models_found": final_valid_models,
                "possible_common": llm_output.get("possible_common", False)
            })
        else:
            # 优化失败：LLM 彻底幻觉了
            logger.error(f"❌ Chunk {chunk_id} 交叉验证失败。以下型号在任何地方都不存在: {still_invalid_models}。")
            # 按照用户要求，将其视为公共块，只保留原先有效的模型
            validated_results.append({
                "chunk_id": chunk_id,
                "models_found": failed_chunk["valid_models"],  # 只保留本地验证的
                "possible_common": True  # 强制设为 True
            })

    # 5. Pass 3: 合并所有最终通过验证的结果
    logger.info("--- Pass 3: 合并最终结果 ---")
    merged_models = {}
    common_chunks = []

    for result in validated_results:
        chunk_id = result["chunk_id"]
        models_found = result["models_found"]
        possible_common = result["possible_common"]

        if possible_common:
            common_chunks.append(chunk_id)

        for model_name in models_found:
            if model_name not in merged_models:
                merged_models[model_name] = set()
            merged_models[model_name].add(chunk_id)

    final_model_results = [
        {"model_name": model_name, "chunk_ids": sorted(list(chunk_ids))}
        for model_name, chunk_ids in merged_models.items()
    ]
    final_model_results.sort(key=lambda x: x["model_name"])

    # 6. 保存输出文件
    final_model_output_path = Path(results_dir) / "model_chunks.json"
    common_chunks_output_path = Path(results_dir) / "common_chunks.json"

    with open(final_model_output_path, "w", encoding="utf-8") as f:
        custom_json_dump(final_model_results, f)

    with open(common_chunks_output_path, "w", encoding="utf-8") as f:
        json.dump(sorted(common_chunks), f, ensure_ascii=False, separators=(",", ":"))

    logger.info(f"🎉 型号抽取结果已保存到: {final_model_output_path}")
    logger.info(f"🎉 公共块 ID 已保存到: {common_chunks_output_path}")
    logger.info(f"📊 Token 消耗: Prompt={total_prompt_tokens}, Completion={total_completion_tokens}")