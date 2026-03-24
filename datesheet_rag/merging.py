# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/merging.py

import json
import logging
import re
from openai import OpenAI
from pathlib import Path
from typing import List, Dict, Any, Set
from collections import defaultdict, deque
from .prompts import (
    get_model_merging_tool_def,
    get_model_merging_system_prompt,
    get_model_merging_user_prompt
)

logger = logging.getLogger(__name__)


# === 辅助: 加载 JSON ===
def load_json_file(file_path: Path) -> Any:
    logger.info(f"Loading JSON from {file_path}")
    try:
        with file_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"CRITICAL: JSON file not found: {file_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"CRITICAL: Error decoding JSON from file {file_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"CRITICAL: An unexpected error occurred while loading JSON file {file_path}: {e}")
        raise


# === 辅助: 清理模型名称 ===
def clean_model_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', name).lower()


# === 辅助: 子序列检查 ===
def is_subsequence(s: str, t: str) -> bool:
    if not s: return True
    if not t: return False
    it = iter(t)
    return all(c in it for c in s)


# === 辅助: LLM 调用 ===
def call_llm_for_group_restructure(
        client: OpenAI,
        model_str: str,
        model_references_for_llm: List[Dict[str, Any]],
        consolidated_contexts_string: str
) -> List[Dict[str, Any]]:
    model_names_in_group = [m["name"] for m in model_references_for_llm]

    system_msg = {
        "role": "system",
        "content": get_model_merging_system_prompt()
    }

    user_msg = {
        "role": "user",
        "content": get_model_merging_user_prompt(
            consolidated_contexts_string,
            model_references_for_llm,
            model_names_in_group
        )
    }

    try:
        response = client.chat.completions.create(
            model=model_str,
            messages=[system_msg, user_msg],
            tools=get_model_merging_tool_def(),
            tool_choice={"type": "function", "function": {"name": "restructure_model_group"}},
            temperature=0.0  # 保持 0.0 以获得确定性结果
        )
        message = response.choices[0].message
        if message.tool_calls and message.tool_calls[0].function.name == "restructure_model_group":
            arguments = json.loads(message.tool_calls[0].function.arguments)
            ops = arguments.get("operations", [])

            # 验证 LLM 的输出
            valid_ops = []
            for op in ops:
                if op.get("target") not in model_names_in_group:
                    logger.warning(
                        f"LLM op invalid: target '{op.get('target')}' not in group {model_names_in_group}. Op: {op}")
                    continue
                if op.get("action") == "merge":
                    if not op.get("sources") or not isinstance(op.get("sources"), list):
                        logger.warning(
                            f"LLM merge op invalid: 'sources' key missing or not a list for target '{op.get('target')}' . Op: {op}")
                        continue
                    valid_sources_for_op = True
                    for src_idx, src in enumerate(op.get("sources", [])):
                        if src not in model_names_in_group:
                            logger.warning(
                                f"LLM merge op invalid: source '{src}' (at index {src_idx}) for target '{op.get('target')}' not in group {model_names_in_group}. Op: {op}")
                            valid_sources_for_op = False
                            break
                    if not valid_sources_for_op:
                        continue
                valid_ops.append(op)
            return valid_ops
        else:
            logger.warning(
                f"LLM did not call the expected function for group {model_names_in_group}. Response: {message}")
            return []
    except Exception as e:
        logger.error(f"Error calling LLM for group restructure {model_names_in_group}: {e}")
        return []


# === 辅助: 应用操作 ===
def apply_all_restructuring_operations(
        raw_chunks_list: List[Dict[str, Any]],
        all_operations: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    initial_model_chunks_map: Dict[str, Set[int]] = {
        c["model_name"]: set(c["chunk_ids"]) for c in raw_chunks_list
    }
    evolving_model_data_map: Dict[str, Set[int]] = {
        name: ids.copy() for name, ids in initial_model_chunks_map.items()
    }
    models_to_discard_globally: Set[str] = set()

    for op in all_operations:
        if op.get("action") == "merge":
            target_name = op.get("target")
            source_names = op.get("sources", [])
            if not target_name or not isinstance(source_names, list):
                logger.warning(f"Merge operation skipped due to malformed target/sources: {op}")
                continue
            if target_name not in evolving_model_data_map:
                logger.warning(f"Merge target '{target_name}' not in model map. Op: {op}")
                continue
            for source_name in source_names:
                if target_name == source_name:
                    logger.warning(f"Merge operation skipped, target and source are the same: {target_name}. Op: {op}")
                    continue
                if source_name in initial_model_chunks_map:
                    chunks_to_add = initial_model_chunks_map[source_name]
                    logger.info(
                        f"Merging (globally) '{source_name}' (chunks: {sorted(list(chunks_to_add))}) into '{target_name}'")
                    evolving_model_data_map[target_name].update(chunks_to_add)
                    models_to_discard_globally.add(source_name)
                else:
                    logger.warning(f"Merge source '{source_name}' not in initial model map. Op: {op}")

    for op in all_operations:
        if op.get("action") == "delete":
            target_name = op.get("target")
            if target_name:
                logger.info(f"Marking '{target_name}' for global discard due to explicit delete operation.")
                models_to_discard_globally.add(target_name)
            else:
                logger.warning(f"Delete operation skipped due to missing target: {op}")

    result = []
    for original_model_entry in raw_chunks_list:
        model_name = original_model_entry["model_name"]
        if model_name not in models_to_discard_globally:
            if model_name in evolving_model_data_map:
                result.append({
                    "model_name": model_name,
                    "chunk_ids": sorted(list(evolving_model_data_map[model_name]))
                })
            else:
                logger.error(f"CRITICAL BUG: Model '{model_name}' was to be kept but not in evolving_model_data_map.")
        else:
            logger.info(f"Model '{model_name}' was discarded globally after all operations.")

    logger.info(f"Final restructured models count after all group operations: {len(result)}")
    return result


# --- 主协调函数 (供 Celery 调用) ---
def process_model_merging(
        results_dir_path: str,
        llm_config: Dict[str, Any]  # <--- 修改点：现在接收与阶段4相同的 config 字典
):
    """
    从 Celery 调用的主函数，协调所有器件融合步骤。
    """
    logger.info(f"开始器件融合: {results_dir_path}")

    # 1. 初始化 LLM 客户端 (使用传入的 DEFAULT_LLM config)
    client = OpenAI(
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"]
    )
    llm_model_name = llm_config["model_name"]  # <--- 修改点：使用字典中的 model_name
    logger.info(f"Using LLM model: {llm_model_name}")

    # 2. 定义和加载文件路径
    data_folder = Path(results_dir_path)
    model_chunks_path = data_folder / "model_chunks.json"
    basic_chunks_path = data_folder / "basic_chunk.json"

    raw_model_chunks_list = load_json_file(model_chunks_path)
    basic_chunks_list = load_json_file(basic_chunks_path)
    basic_chunks_map: Dict[int, str] = {chunk["id"]: chunk["text"] for chunk in basic_chunks_list}

    model_name_to_data_map: Dict[str, Dict[str, Any]] = {
        entry["model_name"]: entry for entry in raw_model_chunks_list
    }
    all_model_original_names: List[str] = [m["model_name"] for m in raw_model_chunks_list]

    total_models = len(raw_model_chunks_list)
    logger.info(f"Loaded {total_models} initial model_chunks")

    # 3. 如果模型<=1，跳过合并，直接写入
    out_path = data_folder / "model_chunks_merged.json"
    if total_models <= 1:
        with out_path.open('w', encoding='utf-8') as f:
            json.dump(raw_model_chunks_list, f, ensure_ascii=False, indent=2)
        logger.info(f"Models count <=1. Original data written to {out_path}")
        return  # 成功完成

    # 4. 构建模型关系图 (Grouping)
    adj = defaultdict(list)
    model_name_details_for_grouping = [{'original': name, 'cleaned': clean_model_name(name)} for name in
                                       all_model_original_names]

    for i in range(len(model_name_details_for_grouping)):
        for j in range(i + 1, len(model_name_details_for_grouping)):
            m1_orig = model_name_details_for_grouping[i]['original']
            m2_orig = model_name_details_for_grouping[j]['original']
            c1 = model_name_details_for_grouping[i]['cleaned']
            c2 = model_name_details_for_grouping[j]['cleaned']
            if not (c1 and c2):
                continue
            related = False
            if c1 == c2:
                related = True
            elif is_subsequence(c1, c2) or is_subsequence(c2, c1):
                related = True
            if related:
                adj[m1_orig].append(m2_orig)
                adj[m2_orig].append(m1_orig)

    visited_for_grouping = set()
    all_groups_for_llm_processing: List[List[str]] = []

    for model_name in all_model_original_names:
        if model_name not in visited_for_grouping:
            current_group_names = []
            q = deque([model_name])
            visited_for_grouping.add(model_name)
            while q:
                curr_model_name = q.popleft()
                current_group_names.append(curr_model_name)
                for neighbor in adj[curr_model_name]:
                    if neighbor not in visited_for_grouping:
                        visited_for_grouping.add(neighbor)
                        q.append(neighbor)
            if len(current_group_names) > 1:
                all_groups_for_llm_processing.append(current_group_names)

    # 5. 遍历组，调用 LLM
    all_llm_operations: List[Dict[str, Any]] = []

    for model_names_in_group in all_groups_for_llm_processing:
        logger.info(f"Preparing group for LLM (Subsequence Component): {model_names_in_group}")
        model_references_for_llm = []
        unique_selected_chunk_ids_in_group = set()
        for name in model_names_in_group:
            model_data = model_name_to_data_map[name]
            all_chunk_ids_for_model = model_data.get("chunk_ids", [])
            selected_chunk_id_for_context = None
            if isinstance(all_chunk_ids_for_model, list) and len(all_chunk_ids_for_model) > 0:
                selected_chunk_id_for_context = all_chunk_ids_for_model[0]
                if selected_chunk_id_for_context is not None:
                    unique_selected_chunk_ids_in_group.add(selected_chunk_id_for_context)
            model_references_for_llm.append({
                "name": name,
                "original_chunk_ids": all_chunk_ids_for_model,
                "selected_chunk_id_for_context": selected_chunk_id_for_context
            })

        consolidated_contexts_string = ""
        sorted_unique_chunk_ids = sorted(list(cid for cid in unique_selected_chunk_ids_in_group if cid is not None))

        if not sorted_unique_chunk_ids:
            consolidated_contexts_string = "No specific contexts were selected from chunks for any model in this group.\n"
        else:
            for chunk_id_to_add in sorted_unique_chunk_ids:
                context_text = basic_chunks_map.get(chunk_id_to_add)
                if context_text is not None:
                    consolidated_contexts_string += f"--- Context from Chunk ID {chunk_id_to_add} ---\n{context_text}\n\n"
                else:
                    consolidated_contexts_string += f"--- Context from Chunk ID {chunk_id_to_add} [Text not found in basic_chunks_map] ---\n\n"

        if not model_references_for_llm: continue

        ops_for_group = call_llm_for_group_restructure(
            client, llm_model_name, model_references_for_llm, consolidated_contexts_string
        )
        if ops_for_group:
            logger.info(f"LLM proposed {len(ops_for_group)} operations for group component: {ops_for_group}")
            all_llm_operations.extend(ops_for_group)
        else:
            logger.info(f"No valid operations returned by LLM for group component.")

    # 6. 应用所有操作
    logger.info(f"Total LLM operations collected from all groups: {len(all_llm_operations)}")
    final_restructured_models = apply_all_restructuring_operations(raw_model_chunks_list, all_llm_operations)

    # 7. 保存最终文件
    with out_path.open('w', encoding='utf-8') as f:
        f.write('[\n')
        for idx, obj in enumerate(final_restructured_models):
            line = json.dumps(obj, ensure_ascii=False, separators=(', ', ': '))
            line = re.sub(r'\[([0-9,\s]+)\]', lambda m: '[' + m.group(1).replace(' ', '') + ']', line)
            suffix = ',' if idx < len(final_restructured_models) - 1 else ''
            f.write(f"  {line}{suffix}\n")
        f.write(']\n')

    logger.info(f"Results written to {out_path}, total {len(final_restructured_models)} records.")