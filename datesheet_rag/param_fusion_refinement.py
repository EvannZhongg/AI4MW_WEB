# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/param_fusion_refinement.py

import json
import os
import re
import sys
import time
import logging
import itertools
from pathlib import Path
from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
from typing import List, Dict, Any, Set
from .prompts import (
    get_param_refinement_tool_def,
    get_param_refinement_system_prompt,
    get_param_refinement_user_prompt
)

logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- 全局常量从 config 传入 ---
# DEFAULT_API_TIMEOUT_SECONDS = 60
# MAX_API_RETRIES = 3
# RETRY_DELAY_SECONDS = 5

# --- LLM 工具定义 ---
TOOLS_DEFINITION = get_param_refinement_tool_def()
DEFINED_TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS_DEFINITION}


# --- LLM 调用封装类 ---
class LLMFunctionCaller:
    def __init__(self, llm_config: Dict[str, Any], fusion_config: Dict[str, Any]):

        api_key = llm_config.get("api_key")
        base_url = llm_config.get("base_url")
        model_name = llm_config.get("model_name")
        timeout_seconds = fusion_config.get("API_TIMEOUT_SECONDS", 60)

        if not api_key:
            raise ValueError("API 密钥(api_key)未在 DEFAULT_LLM 配置中提供。")
        if not base_url:
            raise ValueError("Base URL(base_url)未在 DEFAULT_LLM 配置中提供。")
        if not model_name:
            raise ValueError("模型名称(model_name)未在 DEFAULT_LLM 配置中提供。")

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self.tools = TOOLS_DEFINITION
        self.model_name = model_name

        # 从配置中读取重试和延迟
        self.MAX_API_RETRIES = fusion_config.get("MAX_API_RETRIES", 3)
        self.RETRY_DELAY_SECONDS = fusion_config.get("RETRY_DELAY_SECONDS", 5)

    def _make_api_call(self, messages, parameter_path, available_tools, forced_tool_choice=None):
        logging.info(f"[LLM 调用] 路径: {parameter_path}, 模型: {self.model_name}")
        api_params = {"model": self.model_name, "messages": messages, "tools": available_tools}
        api_params["tool_choice"] = forced_tool_choice if forced_tool_choice else "auto"

        last_exception = None
        for attempt in range(self.MAX_API_RETRIES):
            try:
                response = self.client.chat.completions.create(**api_params)
                message = response.choices[0].message
                if message.tool_calls:
                    tool_call = message.tool_calls[0]
                    function_name = tool_call.function.name
                    arguments_json_str = tool_call.function.arguments
                    logging.info(
                        f"  [LLM 工具调用] LLM 为 {parameter_path} 调用了 '{function_name}' (尝试 {attempt + 1}/{self.MAX_API_RETRIES}).")

                    if not arguments_json_str or not arguments_json_str.strip():
                        logging.error(
                            f"  [LLM 错误] LLM 为 {parameter_path} 的工具 '{function_name}' 返回了空的参数字符串。")
                        return {"tool_name": "error", "error_message": "LLM returned empty arguments for tool call."}

                    try:
                        parsed_arguments = json.loads(arguments_json_str)
                        if function_name not in DEFINED_TOOL_NAMES:
                            logging.warning(f"  LLM 为 {parameter_path} 调用了未定义的工具名 '{function_name}'。")
                            if all(key in parsed_arguments for key in
                                   ["parameter_path", "resolution_strategy_applied", "final_entries"]):
                                logging.info(f"    参数结构与 'record_resolved_parameter' 匹配，将按此处理。")
                                return {"tool_name": "record_resolved_parameter", "arguments": parsed_arguments}
                            else:
                                logging.error(f"    未定义工具 '{function_name}' 的参数结构不匹配任何已知工具。")
                                return {"tool_name": "error",
                                        "error_message": f"LLM called undefined tool '{function_name}' with incompatible arguments."}

                        return {"tool_name": function_name, "arguments": parsed_arguments}
                    except json.JSONDecodeError as e:
                        logging.error(f"  [LLM 错误] 为 {parameter_path} 解析 LLM 返回的 JSON 参数失败: {e}")
                        logging.error(f"    LLM 返回的原始参数字符串: '{arguments_json_str}'")
                        return {"tool_name": "error",
                                "error_message": f"JSONDecodeError: {e} for arguments: {arguments_json_str}"}
                else:
                    if message.content:
                        logging.warning(
                            f"  LLM 未为 {parameter_path} 标准调用工具，尝试从内容中解析参数 (尝试 {attempt + 1}/{self.MAX_API_RETRIES}).")
                        match = re.search(r"✿ARGS✿:\s*(\{[\s\S]*?\})\s*(?:<\|assistant\|>|<\|end_header\|>assistant|$)",
                                          message.content, re.DOTALL)
                        if match:
                            arguments_json_str_from_content = match.group(1)
                            try:
                                parsed_arguments = json.loads(arguments_json_str_from_content)
                                if all(key in parsed_arguments for key in
                                       ["parameter_path", "resolution_strategy_applied", "final_entries"]):
                                    logging.info(
                                        f"  成功从内容中为 {parameter_path} 解析出 'record_resolved_parameter' 的参数。")
                                    return {"tool_name": "record_resolved_parameter", "arguments": parsed_arguments}
                                else:
                                    logging.warning(
                                        f"  从内容中为 {parameter_path} 解析的JSON不含 'record_resolved_parameter' 的所有必需键。")
                            except json.JSONDecodeError as e:
                                logging.error(f"  [LLM 错误] 从内容为 {parameter_path} 解析 JSON 参数失败: {e}")
                                logging.error(f"    内容中的参数字符串: '{arguments_json_str_from_content}'")
                        else:
                            logging.warning(f"  在 {parameter_path} 的响应内容中未找到 '✿ARGS✿:' 标记或有效JSON。")

                    logging.warning(
                        f"  LLM 未为 {parameter_path} 调用任何工具函数 (尝试 {attempt + 1}/{self.MAX_API_RETRIES}). 响应内容: {message.content if message.content else '无内容'}")
                    return {"tool_name": None, "content": message.content}
            except APITimeoutError as e:
                last_exception = e
                logging.warning(
                    f"  [API 超时] 为 {parameter_path} 调用 API 时超时 (尝试 {attempt + 1}/{self.MAX_API_RETRIES}): {e}")
            except APIConnectionError as e:
                last_exception = e
                logging.warning(
                    f"  [API 连接错误] 为 {parameter_path} 调用 API 时发生连接错误 (尝试 {attempt + 1}/{self.MAX_API_RETRIES}): {e}")
            except APIStatusError as e:
                last_exception = e
                logging.error(
                    f"  [API 状态错误] 为 {parameter_path} 调用 API 时出错 (尝试 {attempt + 1}/{self.MAX_API_RETRIES}): HTTP Status {e.status_code}, Response: {e.response}")
                if e.status_code == 429: logging.warning("    检测到速率限制错误 (429)。")
                if e.status_code < 500 and e.status_code not in [429, 408]:
                    break
            except Exception as e:
                last_exception = e
                logging.error(
                    f"  [API 未知错误] 使用模型 {self.model_name} 为 {parameter_path} 调用 API 时出错 (尝试 {attempt + 1}/{self.MAX_API_RETRIES}): {e}")
                break
            if attempt < self.MAX_API_RETRIES - 1:
                logging.info(f"    将在 {self.RETRY_DELAY_SECONDS} 秒后重试...")
                time.sleep(self.RETRY_DELAY_SECONDS)
            else:
                logging.error(f"  [API 错误] 已达到最大重试次数 ({self.MAX_API_RETRIES})。")
        return {"tool_name": "error", "error_message": str(last_exception)}

    def initial_call(self, parameter_path, values_with_source_ids_only, parameter_type_hint, device_model_name):
        system_content = get_param_refinement_system_prompt(device_model_name, is_follow_up_call=False)
        user_prompt = get_param_refinement_user_prompt(
            parameter_path, values_with_source_ids_only, parameter_type_hint, is_follow_up_call=False
        )
        messages = [{"role": "system", "content": system_content}, {"role": "user", "content": user_prompt}]
        return self._make_api_call(messages, parameter_path, self.tools)

    def follow_up_call(self, parameter_path, values_with_source_ids_only, combined_requested_context_str,
                       parameter_type_hint, device_model_name):
        system_content = get_param_refinement_system_prompt(device_model_name, is_follow_up_call=True)
        user_prompt = get_param_refinement_user_prompt(
            parameter_path, values_with_source_ids_only, parameter_type_hint,
            is_follow_up_call=True, combined_requested_context_str=combined_requested_context_str
        )
        messages = [{"role": "system", "content": system_content}, {"role": "user", "content": user_prompt}]
        forced_tool_choice = {"type": "function", "function": {"name": "record_resolved_parameter"}}
        # 仅提供 record_resolved_parameter 工具
        return self._make_api_call(messages, parameter_path, [self.tools[0]], forced_tool_choice)


# --- 文件和数据处理辅助函数 ---
def load_json_data(json_path):
    if not os.path.exists(json_path):
        logging.error(f"数据文件 {json_path} 未找到。")
        return None
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"从 {json_path} 加载 JSON 失败: {e}")
        return None


def load_chunks_map(chunks_json_path):
    chunks_list = load_json_data(chunks_json_path)
    if chunks_list is None: return {}
    chunks_data_map = {}
    for chunk in chunks_list:
        if 'id' in chunk and 'text' in chunk and 'token_count' in chunk:
            # 确保 chunk id 统一为字符串
            chunks_data_map[str(chunk['id'])] = {"text": chunk['text'], "token_count": chunk['token_count']}
        else:
            logging.warning(f"Chunk 数据中缺少 id, text, 或 token_count: {chunk}")
    return chunks_data_map


def needs_list_enhancement(path_str):
    param_name = path_str.split('.')[-1]
    list_enhancement_keywords = ["applications", "features", "function"]
    return any(keyword in param_name.lower() for keyword in list_enhancement_keywords)


def get_parameter_type_hint(path_str, num_values, current_value_example=None):
    if needs_list_enhancement(path_str):
        return "list_enhancement"
    parameter_name_lower = path_str.split('.')[-1].lower()
    equivalence_keywords = ["package", "manufacturer", "base qty", "name", "description", "type", "packaging", "family",
                            "series"]
    if any(keyword in parameter_name_lower for keyword in equivalence_keywords):
        return "single_value_equivalence"
    if num_values > 1:
        return "single_value_conflict_resolution"
    elif num_values == 1:
        return "KEPT_AS_IS_NO_CONFLICT"
    return "single_value_conflict_resolution"


def group_consecutive(sorted_int_list):
    if not sorted_int_list: return []
    sequences = [];
    current_sequence = [sorted_int_list[0]]
    for i in range(1, len(sorted_int_list)):
        if sorted_int_list[i] == current_sequence[-1] + 1:
            current_sequence.append(sorted_int_list[i])
        else:
            sequences.append(current_sequence);
            current_sequence = [sorted_int_list[i]]
    sequences.append(current_sequence)
    return sequences


def split_into_sentences(text_block):
    if not text_block or not text_block.strip(): return []
    sentences = re.split(r'([.!?\n]+)', text_block)
    result_sentences = []
    current_sentence = ""
    for i, part in enumerate(sentences):
        if i % 2 == 0:
            current_sentence += part
        else:
            current_sentence += part
            if current_sentence.strip(): result_sentences.append(current_sentence.strip())
            current_sentence = ""
    if current_sentence.strip(): result_sentences.append(current_sentence.strip())
    if not result_sentences and text_block.strip():
        result_sentences = [s.strip() for s in text_block.splitlines() if s.strip()]
    return [s for s in result_sentences if s]


def select_globally_optimal_single_chunk_ids_per_value(list_of_original_value_source_chunks, chunks_data_map):
    if not list_of_original_value_source_chunks: return []
    candidate_options_per_value_for_product = []
    for original_chunks_for_value in list_of_original_value_source_chunks:
        if not original_chunks_for_value:
            candidate_options_per_value_for_product.append([None])
        else:
            candidate_options_per_value_for_product.append(original_chunks_for_value)

    best_combination_tuple = None
    best_score = (float('inf'), -float('inf'))

    for combo_tuple in itertools.product(*candidate_options_per_value_for_product):
        current_ids_str = [cid for cid in combo_tuple if cid is not None]
        if not current_ids_str: continue
        try:
            current_ids_sorted_int = sorted(list(set(int(cid) for cid in current_ids_str)))
        except ValueError:
            logging.warning(f"组合 {combo_tuple} 中包含无法转换为整数的chunk ID，跳过此组合。")
            continue
        if not current_ids_sorted_int: continue
        sequences = group_consecutive(current_ids_sorted_int)
        num_sequences = len(sequences)
        max_len = max(len(s) for s in sequences) if sequences else 0
        current_score = (num_sequences, -max_len)
        if current_score < best_score:
            best_score = current_score
            best_combination_tuple = combo_tuple
            logging.debug(
                f"  找到新的最佳单ID组合（基于连续性）: {best_combination_tuple} (得分: 序列数={num_sequences}, 最长序列取负={-max_len})")

    if not best_combination_tuple:
        logging.warning(
            "无法通过全局优化选择最佳单ID组合（基于连续性），将为每个value独立选择其首个原始chunk ID（如果存在）。")
        fallback_chosen_ids = []
        for original_chunks_for_value in list_of_original_value_source_chunks:
            if original_chunks_for_value:
                try:
                    sorted_ids_str = sorted(original_chunks_for_value,
                                            key=lambda x: int(x) if x and x.isdigit() else float('inf'))
                    fallback_chosen_ids.append(sorted_ids_str[0] if sorted_ids_str else None)
                except:
                    fallback_chosen_ids.append(original_chunks_for_value[0])
            else:
                fallback_chosen_ids.append(None)
        return fallback_chosen_ids

    final_selected_ids = list(best_combination_tuple)
    ids_in_best_combo_str = [cid for cid in final_selected_ids if cid is not None]
    if not ids_in_best_combo_str: return final_selected_ids
    try:
        ids_in_best_combo_int = sorted(list(set(int(cid) for cid in ids_in_best_combo_str)))
    except ValueError:
        logging.warning(f"最佳连续性组合 {final_selected_ids} 中包含无法转换为整数的chunk ID。无法应用token数优化。")
        return final_selected_ids
    sequences_in_best_combo = group_consecutive(ids_in_best_combo_int)
    isolated_ids_in_best_combo_str = set()
    for seq in sequences_in_best_combo:
        if len(seq) == 1: isolated_ids_in_best_combo_str.add(str(seq[0]))

    for i, original_chunks_for_this_value in enumerate(list_of_original_value_source_chunks):
        id_selected_by_continuity = final_selected_ids[i]
        if id_selected_by_continuity is not None and id_selected_by_continuity in isolated_ids_in_best_combo_str:
            min_token_id = None;
            min_tokens = float('inf')
            if not original_chunks_for_this_value: continue
            for chunk_id_str in original_chunks_for_this_value:
                if chunk_id_str is None: continue
                chunk_data = chunks_data_map.get(chunk_id_str)  # 使用 str 键
                if chunk_data:
                    token_count = chunk_data.get("token_count", float('inf'))
                    if token_count < min_tokens: min_tokens = token_count; min_token_id = chunk_id_str
                else:
                    logging.warning(f"Chunk ID {chunk_id_str} 在 chunks_data_map 中未找到token_count。")
            if min_token_id is not None and min_token_id != id_selected_by_continuity:
                logging.debug(
                    f"  路径的第 {i} 个value，原连续性选择ID '{id_selected_by_continuity}' 是孤立的。替换为token最小的ID '{min_token_id}' (tokens: {min_tokens})。")
                final_selected_ids[i] = min_token_id
            elif min_token_id is not None:
                logging.debug(
                    f"  路径的第 {i} 个value，原连续性选择ID '{id_selected_by_continuity}' 是孤立的，但其本身已是token最小的ID。")
    return final_selected_ids


# --- 核心递归处理函数 ---
def resolve_conflicts_recursively(data_node, current_path, chunks_map, llm_caller, device_model_name):
    if isinstance(data_node, dict):
        new_node = {}
        for key, value in data_node.items():
            new_path = f"{current_path}.{key}" if current_path else key
            new_node[key] = resolve_conflicts_recursively(value, new_path, chunks_map, llm_caller, device_model_name)
        return new_node
    elif isinstance(data_node, list):
        is_parameter_list = all(
            isinstance(item, dict) and "value" in item and "source_chunks" in item for item in data_node)

        if is_parameter_list and data_node:
            should_call_llm = len(data_node) > 1
            hint = get_parameter_type_hint(current_path, len(data_node),
                                           data_node[0].get("value") if data_node else None)
            if hint == "list_enhancement" and len(data_node) >= 1:
                should_call_llm = True

            if should_call_llm:
                logging.debug(
                    f"路径 '{current_path}' 有 {len(data_node)} 个不同的 value 对象。将为每个选择一个代表性chunk ID。")
                list_of_original_source_chunks_per_value = [
                    [str(cid) for cid in item.get("source_chunks", [])] for item in data_node
                ]
                chosen_single_ids_per_value = select_globally_optimal_single_chunk_ids_per_value(
                    list_of_original_source_chunks_per_value, chunks_map
                )
                values_for_initial_llm_call = []
                for i, item in enumerate(data_node):
                    chosen_id_for_this_value = chosen_single_ids_per_value[i]
                    values_for_initial_llm_call.append({
                        "value": item["value"],
                        "source_chunks": [chosen_id_for_this_value] if chosen_id_for_this_value else []
                    })
                    if chosen_id_for_this_value:
                        logging.debug(
                            f"  路径 '{current_path}', value '{item['value']}', 全局单ID选择策略选中 chunk ID: {[chosen_id_for_this_value]}")
                    else:
                        logging.warning(
                            f"  路径 '{current_path}', value '{item['value']}', 全局单ID选择策略未能选择chunk ID。")

                llm_response = llm_caller.initial_call(current_path, values_for_initial_llm_call, hint,
                                                       device_model_name)

                if llm_response and llm_response.get("tool_name") == "get_chunk_contexts":
                    logging.info(f"LLM 为 '{current_path}' 请求了上下文。正在准备后续调用...")
                    chunk_ids_to_fetch_str_set = set()
                    for val_obj_with_rep_id in values_for_initial_llm_call:
                        if val_obj_with_rep_id.get("source_chunks"):
                            chosen_id = val_obj_with_rep_id["source_chunks"][0]
                            if chosen_id: chunk_ids_to_fetch_str_set.add(chosen_id)
                    if not chunk_ids_to_fetch_str_set:
                        logging.warning(
                            f"路径 '{current_path}' 的所有冲突值都没有代表性的 chunk ID。无法获取上下文。保留原始数据。")
                        return data_node

                    logging.info(
                        f"  为路径 '{current_path}' 最终选择用于获取上下文的 Chunk ID (共 {len(chunk_ids_to_fetch_str_set)} 个): {sorted(list(chunk_ids_to_fetch_str_set))}")
                    try:
                        chunk_ids_to_fetch_int = sorted([int(cid) for cid in chunk_ids_to_fetch_str_set if cid])
                    except ValueError:
                        logging.error(
                            f"为 '{current_path}' 收集的代表性 chunk ID 包含非整数值: {chunk_ids_to_fetch_str_set}。跳过上下文获取。")
                        return data_node

                    consecutive_sequences = group_consecutive(chunk_ids_to_fetch_int)
                    final_context_parts = []
                    for seq in consecutive_sequences:
                        sequence_label = f"Chunks {seq[0]}" if len(seq) == 1 else f"Chunks {seq[0]}-{seq[-1]}"
                        if len(seq) == 1:
                            chunk_data = chunks_map.get(str(seq[0]))  # 使用 str 键
                            raw_chunk_text = chunk_data.get("text",
                                                            "[上下文文本不可用]") if chunk_data else "[上下文文本不可用]"
                            final_context_parts.append(f"--- Context from {sequence_label} ---\n{raw_chunk_text}")
                        else:
                            all_sentences_for_sequence = []
                            sentences_from_previous_chunk_in_seq = set()
                            for chunk_idx_in_seq, chunk_id_val in enumerate(seq):
                                chunk_id_str = str(chunk_id_val)
                                chunk_data = chunks_map.get(chunk_id_str)  # 使用 str 键
                                current_chunk_raw_text = chunk_data.get("text", "") if chunk_data else ""
                                current_chunk_sentences_list = split_into_sentences(current_chunk_raw_text)
                                if chunk_idx_in_seq == 0:
                                    all_sentences_for_sequence.extend(current_chunk_sentences_list)
                                else:
                                    new_sentences_from_current_chunk = [
                                        s for s in current_chunk_sentences_list if
                                        s.lower() not in sentences_from_previous_chunk_in_seq
                                    ]
                                    all_sentences_for_sequence.extend(new_sentences_from_current_chunk)
                                sentences_from_previous_chunk_in_seq = set(
                                    s.lower() for s in current_chunk_sentences_list)
                            sequence_text = " ".join(all_sentences_for_sequence)
                            final_context_parts.append(
                                f"--- Context from {sequence_label} (pairwise de-duplicated & combined) ---\n{sequence_text}")

                    combined_requested_context_str = "\n\n".join(final_context_parts)
                    if not combined_requested_context_str.strip():
                        combined_requested_context_str = "[未能成功构建上下文文本]"
                        logging.warning(f"为路径 '{current_path}' 构建的组合上下文为空。")

                    llm_response = llm_caller.follow_up_call(current_path, values_for_initial_llm_call,
                                                             combined_requested_context_str, hint, device_model_name)

                if llm_response and llm_response.get("tool_name") == "record_resolved_parameter":
                    resolved_args = llm_response.get("arguments")
                    if resolved_args and "final_entries" in resolved_args and isinstance(resolved_args["final_entries"],
                                                                                         list):
                        is_list_enhancement_hint = (hint == "list_enhancement")
                        resolution_strategy = resolved_args.get("resolution_strategy_applied")
                        should_revert_to_original = False
                        if not is_list_enhancement_hint:
                            if len(resolved_args["final_entries"]) > 1:
                                should_revert_to_original = True
                                logging.info(
                                    f"  路径 '{current_path}': LLM 为非列表增强类型返回了多个条目 ({len(resolved_args['final_entries'])} 个)。将保留原始冲突数据。")
                            elif resolution_strategy == "NO_RESOLUTION_FLAG_FOR_REVIEW":
                                should_revert_to_original = True
                                logging.info(f"  路径 '{current_path}': LLM 标记为无法解决。将保留原始冲突数据。")
                        if should_revert_to_original:
                            processed_original_data_node = []
                            for item_original in data_node:
                                processed_item = dict(item_original)
                                if "value" in processed_item:
                                    processed_item["value"] = str(processed_item["value"]) if processed_item[
                                                                                                  "value"] is not None else "null"
                                processed_original_data_node.append(processed_item)
                            return processed_original_data_node
                        else:
                            processed_final_entries = []
                            if resolution_strategy == "MERGED_SEMANTICALLY_EQUIVALENT" and \
                                    len(resolved_args["final_entries"]) == 1 and \
                                    isinstance(resolved_args["final_entries"][0], dict):
                                logging.info(
                                    f"  路径 '{current_path}': LLM 执行了 MERGED_SEMANTICALLY_EQUIVALENT。将合并所有原始 source_chunks。")
                                all_original_source_chunks_for_this_merge = set()
                                for original_item_obj in data_node:  # data_node 是此参数路径的原始冲突值列表
                                    if isinstance(original_item_obj, dict) and "source_chunks" in original_item_obj:
                                        for sc_id in original_item_obj.get("source_chunks", []):
                                            all_original_source_chunks_for_this_merge.add(str(sc_id))

                                consolidated_chunks = []
                                if all_original_source_chunks_for_this_merge:
                                    try:
                                        # 尝试按数字排序
                                        sorted_chunk_ids_int = sorted(
                                            [int(cid) for cid in all_original_source_chunks_for_this_merge])
                                        consolidated_chunks = [str(cid) for cid in sorted_chunk_ids_int]
                                    except ValueError:  # 如果包含非数字ID，则按字符串排序
                                        consolidated_chunks = sorted(list(all_original_source_chunks_for_this_merge))

                                # 更新LLM返回的单个条目的source_chunks
                                resolved_args["final_entries"][0]["source_chunks"] = consolidated_chunks
                                logging.info(f"    合并后的 source_chunks: {consolidated_chunks}")

                            for entry in resolved_args["final_entries"]:
                                if isinstance(entry, dict) and "value" in entry:
                                    entry["value"] = str(entry["value"]) if entry["value"] is not None else "null"
                                processed_final_entries.append(entry)
                            return processed_final_entries
                    else:
                        logging.warning(
                            f"LLM 为 {current_path} 的 'record_resolved_parameter' 调用缺少 'final_entries' 或格式不正确。保留原始数据。")
                        return data_node
                elif llm_response and llm_response.get("tool_name") == "error":
                    logging.warning(
                        f"LLM API 调用失败 ({llm_response.get('error_message')})。保留 {current_path} 的原始数据。")
                    return data_node
                else:
                    logging.warning(f"LLM 未能为 {current_path} 提供有效解析 (响应: {llm_response})。保留原始数据。")
                    return data_node
            else:  # 不调用LLM（单值情况）
                processed_list = []
                for i, item in enumerate(data_node):
                    new_item = dict(item)
                    if isinstance(new_item, dict) and "value" in new_item:
                        new_item["value"] = str(new_item["value"]) if new_item["value"] is not None else "null"
                    processed_list.append(
                        resolve_conflicts_recursively(new_item, f"{current_path}[{i}]", chunks_map, llm_caller,
                                                      device_model_name))
                return processed_list
        else:  # 非参数列表，递归处理其元素
            return [
                resolve_conflicts_recursively(item, f"{current_path}[{i}]", chunks_map, llm_caller, device_model_name)
                for i, item in enumerate(data_node)]
    else:  # 叶子节点
        return data_node


# --- 主执行流程 (供 Celery 调用) ---
def process_parameter_fusion_refinement(
        base_input_dir: str,
        llm_config: Dict[str, Any],
        fusion_config: Dict[str, Any]
):
    logging.info("开始执行参数融合细化流程 (步骤2)...")

    # 1. 加载 chunks.json
    chunks_file_path = os.path.join(base_input_dir, "chunks.json")
    logging.info(f"加载 chunks 数据: {chunks_file_path}")
    chunks_data_map = load_chunks_map(chunks_file_path)
    if not chunks_data_map:
        logging.critical(f"Chunks 数据文件 {chunks_file_path} 为空或无法加载有效映射。脚本中止。")
        raise FileNotFoundError(f"Chunks.json is empty or invalid at {chunks_file_path}")

    # 2. 找到 "merged" 目录
    preliminary_merged_dir = os.path.join(base_input_dir, "param_results", "merged")
    if not os.path.isdir(preliminary_merged_dir):
        logging.critical(f"初步融合数据目录 {preliminary_merged_dir} 不存在。脚本中止。")
        raise FileNotFoundError(f"Directory not found: {preliminary_merged_dir}")

    # 3. 创建 "resolved" 目录
    resolved_output_dir = os.path.join(base_input_dir, "param_results", "resolved")
    os.makedirs(resolved_output_dir, exist_ok=True)
    logging.info(f"结果将保存到: {resolved_output_dir}")

    # 4. 初始化 LLM 调用器
    try:
        llm_caller = LLMFunctionCaller(
            llm_config=llm_config,
            fusion_config=fusion_config
        )
    except (ValueError, KeyError) as e:
        logging.critical(f"初始化 LLM 调用器错误: {e}。脚本中止。")
        raise

    # 5. 遍历 "merged" 目录中的文件
    json_files_processed_count = 0
    for filename in os.listdir(preliminary_merged_dir):
        if filename.lower().endswith("_merged.json"):  # 只处理 _merged.json

            current_merged_json_path = os.path.join(preliminary_merged_dir, filename)
            logging.info(f"----------------------------------------------------------------")
            logging.info(f"开始处理文件: {current_merged_json_path}")

            preliminary_fused_data = load_json_data(current_merged_json_path)
            if preliminary_fused_data is None:
                logging.error(f"无法加载初步融合数据文件 {current_merged_json_path}。跳过此文件。")
                continue

            # 6. 提取设备型号
            device_model_name_from_json = "UnknownDevice"
            if isinstance(preliminary_fused_data, dict):
                device_info = preliminary_fused_data.get("Device")
                if isinstance(device_info, dict):
                    # 适应 'name' 和 'Name' 键
                    name_value_obj = device_info.get("name", device_info.get("Name"))

                    if isinstance(name_value_obj, str):
                        device_model_name_from_json = name_value_obj
                    elif isinstance(name_value_obj, list) and name_value_obj and isinstance(name_value_obj[0],
                                                                                            dict) and "value" in \
                            name_value_obj[0]:
                        device_model_name_from_json = str(name_value_obj[0]["value"])

                if device_model_name_from_json != "UnknownDevice":
                    logging.info(f"  提取到当前设备型号用于LLM提示: {device_model_name_from_json}")
                else:
                    # 从文件名回退
                    stem_from_filename = os.path.splitext(filename)[0]
                    if stem_from_filename.endswith("_merged"):
                        device_model_name_from_json = stem_from_filename[:-len("_merged")]
                        logging.info(f"  从文件名提取到设备型号: {device_model_name_from_json}")
                    else:
                        logging.warning(f"  未能从 {filename} 提取设备型号。将使用 '{device_model_name_from_json}'。")
            else:
                logging.warning(f"  文件 {filename} 加载的数据不是字典。将使用 '{device_model_name_from_json}'。")

            # 7. 定义输出路径
            input_filename_stem = os.path.splitext(filename)[0]
            output_filename = f"{input_filename_stem}_resolved_llm.json"
            output_json_path = os.path.join(resolved_output_dir, output_filename)

            # 8. 执行递归融合
            logging.info(f"开始对 {filename} 进行基于 LLM 的参数融合细化 (设备型号: {device_model_name_from_json})...")
            resolved_data = resolve_conflicts_recursively(preliminary_fused_data, "", chunks_data_map, llm_caller,
                                                          device_model_name_from_json)
            logging.info(f"对 {filename} 的基于 LLM 的参数融合细化完成。")

            # 9. 保存最终文件
            try:
                with open(output_json_path, "w", encoding="utf-8") as f:
                    json_str = json.dumps(resolved_data, indent=2, ensure_ascii=False)
                    # 格式化 source_chunks
                    json_str = re.sub(r'"source_chunks": \[\s+([^\]]+?)\s+\]',
                                      lambda m: '"source_chunks": [' + ''.join(m.group(1).split()) + ']',
                                      json_str)
                    f.write(json_str)
                logging.info(f"成功将 {filename} 的细化数据保存到: {output_json_path}")
                json_files_processed_count += 1
            except IOError as e:
                logging.error(f"无法将输出文件写入 {output_json_path}. 原因: {e}")
            except TypeError as e:
                logging.error(f"用于 JSON 序列化的数据对 {output_json_path} 无效. 原因: {e}")
            logging.info(f"----------------------------------------------------------------")

    if json_files_processed_count == 0:
        logging.warning(f"在目录 {preliminary_merged_dir} 中没有找到符合条件的 .json 文件进行处理。")
    else:
        logging.info(f"所有符合条件的 .json 文件处理完毕。共处理了 {json_files_processed_count} 个文件。")