# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/param_extraction.py

import json
import logging
import re
import time
from openai import OpenAI
from pathlib import Path
from typing import List, Dict, Any, Set
from tqdm import tqdm  # 确保 'tqdm' 已 pip install
from .prompts import build_device_prompt, build_single_device_prompt

logger = logging.getLogger(__name__)


# ==== 辅助: LLM 调用函数 ====
def call_llm(
        client: OpenAI,
        model: str,
        system_prompt: str,
        user_prompt: str,
        config: Dict[str, Any]
) -> tuple[dict, int]:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=config.get("TEMPERATURE", 0.2),
            response_format={"type": "json_object"},
            max_tokens=config.get("MAX_TOKENS", 8000)
        )
        raw = response.choices[0].message.content or ""

        # 清理 code-fence
        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        clean = re.sub(r"\s*```$", "", clean).strip()

        # 提取 {}
        start = clean.find("{")
        end = clean.rfind("}") + 1
        json_str = clean[start:end] if start != -1 and end != -1 else clean

        content = json.loads(json_str)
        used_tokens = getattr(response.usage, "total_tokens", 0) or 0
        return content, used_tokens
    except Exception as e:
        raw = locals().get("raw", "")  # 尝试获取原始输出
        logger.error(f"模型响应 JSON 解析失败：{str(e)} 原始输出: {raw!r}")
        return {"error": str(e), "raw_output": raw}, 0


# === 主协调函数 (供 Celery 调用) ===
def process_parameter_extraction(
        results_dir_path: str,
        llm_config: Dict[str, Any],
        extraction_config: Dict[str, Any]
):
    """
    从 Celery 调用的主函数，协调所有参数提取步骤。
    """
    logger.info(f"开始参数提取: {results_dir_path}")

    # 1. 准备配置和 Client
    client = OpenAI(
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"]
    )
    openai_model = llm_config["model_name"]
    api_call_delay = extraction_config.get("API_CALL_DELAY", 1.0)

    # 2. 加载数据
    input_base = Path(results_dir_path)
    output_dir = input_base / "param_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(input_base / "model_chunks_merged.json", "r", encoding="utf-8") as f:
            model_chunks = json.load(f)

        with open(input_base / "chunks.json", "r", encoding="utf-8") as f:
            chunk_data = json.load(f)
            chunks = {c["id"]: c["text"] for c in chunk_data}  # 必须是 int(c["id"]) 吗？ 假设 id 是 int
            # 修正：原始 chunk.json 保存 id 为 str，这里保持一致
            chunks = {int(c["id"]): c["text"] for c in chunk_data}

        common_chunks_path = input_base / "common_chunks.json"
        common_chunk_ids = []
        if common_chunks_path.exists():
            with open(common_chunks_path, "r", encoding="utf-8") as f:
                common_chunk_ids = json.load(f)  # 假设 common_chunks.json 存储的是 IDs 列表 [3, 6]
                common_chunk_ids = sorted(list(set(common_chunk_ids)))  # 确保唯一且排序

    except Exception as e:
        logger.error(f"加载 JSON 文件失败: {e}")
        raise

    # 3. 主循环 & 抽取
    total_tokens_used = 0

    if len(model_chunks) == 1:
        # ==== 单型号模式：遍历 chunks.json 中所有 chunk id ====
        device_name = model_chunks[0]["model_name"]
        all_ids = sorted(list(chunks.keys()))  # 获取所有 chunk IDs 并排序
        logging.info(f"单型号文档，处理器件：{device_name}，遍历全部 {len(all_ids)} 个 chunk IDs")

        result = {
            "Device": {"Name": device_name},
            "chunk_parameters": {}
        }

        for cid in tqdm(all_ids, desc=f"Processing {device_name} (single)"):
            text = chunks.get(cid, "")
            logging.info(f"[单型号] 正在处理 chunk {cid}...")
            if not text.strip():
                result["chunk_parameters"][str(cid)] = {"error": "空文本，跳过"}
                continue

            system_prompt = f"你是一位电子器件专家，擅长从数据手册中提取结构化信息，以下是文本内容：\n{text}"
            user_prompt = build_single_device_prompt(device_name)

            resp, used = call_llm(client, openai_model, system_prompt, user_prompt, extraction_config)
            total_tokens_used += used
            result["chunk_parameters"][str(cid)] = resp
            time.sleep(api_call_delay)  # 礼貌性延迟

        out_path = output_dir / f"{device_name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logging.info(f"已保存：{out_path}")

    else:
        # ==== 多型号模式：实现您的优化逻辑 ====

        # 1. 预计算每个器件的最小 chunk_id
        device_min_chunk = {}
        for model in model_chunks:
            if model.get("chunk_ids"):
                device_min_chunk[model["model_name"]] = min(model["chunk_ids"])

        logging.info(f"多型号优化：计算得到器件起始 chunk ID: {device_min_chunk}")

        # 2. 遍历每个型号
        for model in tqdm(model_chunks, desc="Processing devices (multi)"):
            device_name = model["model_name"]
            specified_ids = set(model["chunk_ids"])

            # --- 优化逻辑 ---
            device_min_id = device_min_chunk.get(device_name)

            relevant_common_ids = set()
            if device_min_id is not None:
                # A common chunk C is relevant to device D if C >= min(D.chunk_ids)
                for c_id in common_chunk_ids:
                    if c_id >= device_min_id:
                        relevant_common_ids.add(c_id)

            # 合并并去重
            all_ids = sorted(list(specified_ids.union(relevant_common_ids)))
            # --- 优化结束 ---

            logging.info(
                f"处理器件 {device_name}。特定 IDs: {sorted(list(specified_ids))}, 智能插入 Common IDs: {sorted(list(relevant_common_ids))}, 总计 IDs: {all_ids}")

            result = {
                "Device": {"name": device_name},
                "chunk_parameters": {}
            }

            for cid in all_ids:
                text = chunks.get(cid, "")
                logging.info(f"正在处理器件 {device_name} 的 chunk {cid}...")
                if not text.strip():
                    result["chunk_parameters"][str(cid)] = {"error": "空文本，跳过"}
                    continue

                system_prompt = f"你是一位电子器件专家，擅长从数据手册中提取参数，以下是文本内容：\n{text}"
                user_prompt = build_device_prompt(device_name)

                resp, used = call_llm(client, openai_model, system_prompt, user_prompt, extraction_config)
                total_tokens_used += used
                result["chunk_parameters"][str(cid)] = resp
                time.sleep(api_call_delay)  # 礼貌性延迟

            out_path = output_dir / f"{device_name}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logging.info(f"已保存：{out_path}")

    # 4. 统计 token 消耗
    logging.info(f"处理完成，总 token 消耗：{total_tokens_used} tokens")