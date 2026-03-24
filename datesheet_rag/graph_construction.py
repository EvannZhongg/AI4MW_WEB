# pdf_parser/graph_construction.py

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Set
import re
import copy
import uuid
import time
from openai import OpenAI
from django.conf import settings
from django.db import transaction
from .models import PDFParsingTask, GraphChunk, GraphNode, GraphEdge, NodeSourceLink
from .classification import load_json_file
from api.models import Device as ApiDevice  # <--- (*** 修复：添加导入 ***)

logger = logging.getLogger(__name__)

# --- 全局变量 (在 process_graph_construction 开始时重置) ---
links_to_create_map = {}
node_definitions = {}
edges_to_create = set()


# === 辅助函数：批量嵌入 ===
def get_embeddings_batch(
        texts: List[str],
        client: OpenAI,
        model: str,
        dimensions: int,
        batch_size: int
) -> Dict[str, List[float]]:
    """
    获取一批文本的嵌入向量，并返回一个 文本 -> 向量 的字典。
    """
    if not texts:
        return {}

    embedding_map = {}
    total_texts = len(texts)

    for i in range(0, total_texts, batch_size):
        batch_texts = texts[i: i + batch_size]
        try:
            response = client.embeddings.create(
                model=model,
                input=batch_texts,
                dimensions=dimensions,
                encoding_format="float"
            )
            for text, embedding_data in zip(batch_texts, response.data):
                embedding_map[text] = embedding_data.embedding
            logger.info(f"批量嵌入: 处理 {i + len(batch_texts)} / {total_texts} 个文本...")
        except Exception as e:
            logger.error(f"批量嵌入失败 (批次 {i}-{i + batch_size}): {e}")
            for text in batch_texts:
                embedding_map[text] = None
    return embedding_map


# === 辅助函数：图谱构建 ===

def add_node_definition(node_id: str, community: str, name: str, value: str, properties: Dict, text_for_embedding: str):
    """
    收集节点定义，以便稍后批量嵌入和创建。
    """
    if not node_id:
        logger.warning(f"跳过添加节点，ID为空。")
        return
    node_definitions[node_id] = {
        'node_id': node_id,
        'community': community,
        'name': name,
        'value': value,
        'properties': properties,
        'text_for_embedding': text_for_embedding
    }


def add_edge(source_id: str, target_id: str, type: str):
    """准备一个边以供批量 'get_or_create'。"""
    if not source_id or not target_id or not type:
        return
    edges_to_create.add((source_id, target_id, type))


def add_source_link(node_id: str, chunk_ids_in_doc: List[str]):
    """
    将 node_id 及其来源 chunks 聚合到全局映射中。
    """
    if not node_id:
        return
    chunk_set = links_to_create_map.setdefault(node_id, set())
    chunk_set.update(chunk_ids_in_doc)


# --- (*** 修复：添加缺失的函数 ***) ---
def _sync_device_to_api_model(device_data: Dict, task: PDFParsingTask):
    """
    从解析的JSON数据中提取信息，创建或更新 api.models.Device 表中的条目。
    """
    try:
        # 1. 提取器件名称 (Name / device_number)
        device_info = device_data.get("Device", {})
        name_val = device_info.get("name") or device_info.get("Name")
        device_name = "Unknown"
        if isinstance(name_val, list) and name_val:
            device_name = name_val[0].get("value", "Unknown")
        elif isinstance(name_val, str):  # 兼容旧格式
            device_name = name_val

        if device_name == "Unknown":
            logger.warning(f"无法从JSON中提取Device.Name，跳过同步到 api.Device。")
            return

        # 2. 提取器件类型 (Category)
        category_info = device_data.get("Category", {})
        type_val_list = category_info.get("level_3") or category_info.get("level_2") or category_info.get("level_1")
        device_type = "N/A"
        if isinstance(type_val_list, list) and type_val_list:
            device_type = type_val_list[0].get("value", "N/A")

        # 3. 提取描述和衬底 (Basic information)
        basic_info = device_data.get("Basic information", {})
        desc_val_list = basic_info.get("Description") or basic_info.get("description")
        tech_description = ""
        if isinstance(desc_val_list, list) and desc_val_list:
            tech_description = desc_val_list[0].get("value", "")

        subs_val_list = basic_info.get("Substrate") or basic_info.get("substrate")
        substrate = "N/A"
        if isinstance(subs_val_list, list) and subs_val_list:
            substrate = subs_val_list[0].get("value", "N/A")

        # 4. 执行数据库 Update or Create
        defaults = {
            'name': device_name,
            'device_type': device_type,
            'tech_description': tech_description,
            'substrate': substrate,
        }

        obj, created = ApiDevice.objects.update_or_create(
            device_number=device_name,
            defaults=defaults
        )

        if created:
            logger.info(f"已创建新的 api.Device 条目: {device_name}")
        else:
            logger.info(f"已更新已有的 api.Device 条目: {device_name}")

    except Exception as e:
        logger.error(f"同步到 api.Device 失败: {e}", exc_info=True)


# --- (*** 修复结束 ***) ---


def process_graph_from_json(
        data: Dict,
        source_file_name: str
):
    """
    解析JSON，填充全局的 node_definitions, edges_to_create, 和 links_to_create_map。
    """

    # --- 1. Device 节点 ---
    device_info = data.get("Device", {})
    name_val = device_info.get("name") or device_info.get("Name")
    device_name = "Unknown"
    if isinstance(name_val, list) and name_val:
        device_name = name_val[0].get("value", "Unknown")
    elif isinstance(name_val, str):
        device_name = name_val

    if device_name == "Unknown":
        logger.warning(f"JSON文件中缺少设备名称 {source_file_name}，跳过处理。")
        return

    # --- 2. Manufacturer 节点 ---
    manufacturer_name = None
    mfg_chunks = []
    if "Manufacturer" in data and isinstance(data["Manufacturer"], dict):
        name_list = data["Manufacturer"].get("Name")
        if isinstance(name_list, list) and name_list:
            mfg_entry = name_list[0]
            if isinstance(mfg_entry, dict):
                manufacturer_name = mfg_entry.get("value")
                mfg_chunks = mfg_entry.get("source_chunks", [])

    # --- 创建 Device 节点 ---
    device_readable_id = f"Device:{manufacturer_name}_{device_name}" if manufacturer_name else f"Device:{device_name}"
    device_text_for_embedding = f"Device: {device_name}"

    add_node_definition(
        node_id=device_readable_id,
        community="Device",
        name="Name",
        value=device_name,
        properties={"original_filename": source_file_name},
        text_for_embedding=device_text_for_embedding,
    )
    add_source_link(device_readable_id, [])

    # --- 创建 Manufacturer 节点及边 ---
    if manufacturer_name:
        mfg_readable_id = f"Manufacturer:{manufacturer_name}"
        mfg_text_for_embedding = f"Manufacturer: {manufacturer_name}"

        add_node_definition(
            node_id=mfg_readable_id,
            community="Manufacturer",
            name="Name",
            value=manufacturer_name,
            properties={},
            text_for_embedding=mfg_text_for_embedding
        )
        add_source_link(mfg_readable_id, mfg_chunks)
        add_edge(device_readable_id, mfg_readable_id, "is produced by")
        add_edge(mfg_readable_id, device_readable_id, "manufactures")

    # --- 3. Category 节点及边 ---
    if "Category" in data and isinstance(data["Category"], dict):
        category_data = data["Category"]
        levels = sorted([key for key in category_data.keys() if key.startswith('level_')])
        level_node_ids = []
        for level_key in levels:
            entry_list = category_data.get(level_key)
            if isinstance(entry_list, list) and entry_list:
                level_value = entry_list[0].get("value")
                level_chunks = entry_list[0].get("source_chunks", [])

                if level_value:
                    cat_readable_id = f"Category:{level_key}_{level_value}"
                    cat_text_for_embedding = f"{level_key}: {level_value}"

                    add_node_definition(
                        node_id=cat_readable_id,
                        community="Category",
                        name=level_key,
                        value=level_value,
                        properties={},
                        text_for_embedding=cat_text_for_embedding
                    )
                    add_source_link(cat_readable_id, level_chunks)
                    level_node_ids.append(cat_readable_id)

        for i in range(len(level_node_ids) - 1):
            add_edge(level_node_ids[i], level_node_ids[i + 1], "HAS SUBCATEGORY")
            add_edge(level_node_ids[i + 1], level_node_ids[i], "SUB CATEGORY OF")

        if level_node_ids:
            add_edge(device_readable_id, level_node_ids[-1], "Belongs to Category")
            add_edge(level_node_ids[-1], device_readable_id, "has device")

    # --- 4. 处理所有其他社区 (Parameters, Image, etc.) ---
    for community_name, community_data in data.items():
        if community_name in ["Device", "Manufacturer", "Category"]:
            continue
        if isinstance(community_data, dict):
            for key, value_list in community_data.items():
                if isinstance(value_list, list):
                    for item in value_list:
                        if not (isinstance(item, dict) and "value" in item):
                            continue
                        data_value = item.get("value")
                        if not data_value:
                            continue
                        source_chunks = item.get("source_chunks", [])
                        param_readable_id = f"{community_name}:{key}_{data_value}"
                        if community_name == "Image":
                            text_for_embedding = f"{key}: {item.get('description', '')}"
                            param_properties = item
                            edge_type = "has image"
                            reverse_edge_type = "is image of"
                        else:
                            text_for_embedding = f"{key}: {data_value}"
                            param_properties = {"value": data_value}
                            match = re.match(r'^(.*?)(?:\s*[@(（].*)?$', key)
                            base_name = match.group(1).strip() if match else key
                            edge_type = f"has {base_name}"
                            reverse_edge_type = f"is {base_name} of"

                        add_node_definition(
                            node_id=param_readable_id,
                            community=community_name,
                            name=key,
                            value=data_value,
                            properties=param_properties,
                            text_for_embedding=text_for_embedding
                        )
                        add_source_link(param_readable_id, source_chunks)
                        add_edge(device_readable_id, param_readable_id, edge_type)
                        add_edge(param_readable_id, device_readable_id, reverse_edge_type)


# --- 主协调函数 (供 Celery 调用) ---
def process_graph_construction(
        task_db_id: int,
        results_dir_path: str,
        llm_config: Dict[str, Any],
        embedding_config: Dict[str, Any],
        construction_config: Dict[str, Any]
):
    global node_definitions, edges_to_create, links_to_create_map

    # --- 0. 重置全局变量 ---
    node_definitions = {}
    edges_to_create = set()
    links_to_create_map = {}

    input_dir = Path(results_dir_path) / "param_results" / "classified_results"
    chunks_json_path = Path(results_dir_path) / "chunks.json"
    logger.info(f"开始图谱构建流程 (阶段10)，输入目录: {input_dir}")

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
    except PDFParsingTask.DoesNotExist:
        logger.error(f"图谱构建失败：找不到任务 {task_db_id}")
        return

    # 1. 初始化客户端
    try:
        embedding_client = OpenAI(
            api_key=embedding_config["api_key"],
            base_url=embedding_config["base_url"]
        )
        embedding_model_config = {
            "model": embedding_config["model_name"],
            "dimensions": embedding_config["dimensions"],
            "batch_size": embedding_config.get("BATCH_SIZE", 10)
        }
        logger.info(f"Embedding({embedding_config['model_name']}) 客户端初始化成功。")
    except Exception as e:
        logger.error(f"初始化Embedding客户端失败: {e}")
        raise

    # 2. 加载数据
    chunk_data_list = load_json_file(chunks_json_path) or []
    json_files_to_process = list(input_dir.glob("*.json"))
    if not json_files_to_process:
        logger.warning(f"在 '{input_dir}' 中没有找到需要处理的JSON文件。")

    # --- 3. 收集所有待嵌入的文本 ---
    texts_to_embed_set = set()
    for chunk in chunk_data_list:
        if chunk.get("text"):
            texts_to_embed_set.add(chunk.get("text"))

    for filepath in json_files_to_process:
        logger.info(f"正在解析图谱文件: {filepath.name}")
        device_data = load_json_file(filepath)
        if device_data:
            # (调用修复)
            _sync_device_to_api_model(device_data, task)
            process_graph_from_json(device_data, filepath.name)

    for node_def in node_definitions.values():
        if node_def.get("text_for_embedding"):
            texts_to_embed_set.add(node_def.get("text_for_embedding"))

    # --- 4. 批量执行嵌入 ---
    logger.info(f"收集到 {len(texts_to_embed_set)} 个唯一文本待嵌入...")
    embedding_map = get_embeddings_batch(
        texts=list(texts_to_embed_set),
        client=embedding_client,
        **embedding_model_config
    )
    logger.info(f"成功生成 {len(embedding_map)} 个嵌入向量。")

    # --- 5. 开启数据库事务 ---
    try:
        with transaction.atomic():
            logger.info("--- 阶段10.1: 处理 Chunks ---")
            NodeSourceLink.objects.filter(task=task).delete()
            GraphChunk.objects.filter(task=task).delete()
            logger.info(f"已清理任务 {task.id} 的旧 Chunks 和 Links。")

            chunks_to_bulk_create = []
            for chunk in chunk_data_list:
                text = chunk.get("text")
                embedding = embedding_map.get(text)
                if chunk.get("id") and text and embedding:
                    chunks_to_bulk_create.append(GraphChunk(
                        unique_id=f"{task.id}_{chunk.get('id')}",
                        task=task,
                        chunk_id_in_doc=chunk.get("id"),
                        text=text,
                        embedding=embedding
                    ))
            if chunks_to_bulk_create:
                GraphChunk.objects.bulk_create(chunks_to_bulk_create, batch_size=construction_config["BATCH_SIZE"])
                logger.info(f"成功创建 {len(chunks_to_bulk_create)} 个 GraphChunk 节点。")

            chunks_map = {chunk.chunk_id_in_doc: chunk for chunk in GraphChunk.objects.filter(task=task)}
            logger.info(f"创建了 {len(chunks_map)} 个 GraphChunk 映射。")

            logger.info("--- 阶段10.2: 处理 节点 和 边 ---")
            nodes_to_bulk_op = []
            for node_def in node_definitions.values():
                embedding = embedding_map.get(node_def['text_for_embedding'])
                if embedding:
                    nodes_to_bulk_op.append(GraphNode(
                        node_id=node_def['node_id'],
                        community=node_def['community'],
                        name=node_def['name'],
                        value=node_def['value'],
                        properties=node_def['properties'],
                        text_for_embedding=node_def['text_for_embedding'],
                        embedding=embedding
                    ))
                else:
                    logger.warning(f"跳过节点 {node_def['node_id']}，因为未能生成嵌入。")

            if nodes_to_bulk_op:
                logger.info(f"正在批量更新/创建 {len(nodes_to_bulk_op)} 个 GraphNode...")
                GraphNode.objects.bulk_create(
                    nodes_to_bulk_op,
                    batch_size=construction_config["BATCH_SIZE"],
                    update_conflicts=True,
                    unique_fields=['node_id'],
                    update_fields=['community', 'name', 'value', 'properties', 'text_for_embedding', 'embedding',
                                   'updated_at']
                )
                logger.info("GraphNode 批量操作完成。")

            links_to_bulk_create = []
            for node_id in links_to_create_map.keys():
                links_to_bulk_create.append(NodeSourceLink(
                    node_id=node_id,
                    task=task
                ))

            if links_to_bulk_create:
                logger.info(f"正在批量创建 {len(links_to_bulk_create)} 个 NodeSourceLink...")
                created_links = NodeSourceLink.objects.bulk_create(
                    links_to_bulk_create,
                    batch_size=construction_config["BATCH_SIZE"],
                    ignore_conflicts=True
                )
                logger.info("NodeSourceLink 批量创建完成。")

                logger.info("正在准备 M2M 关联 (Link <-> Chunks)...")
                link_instance_map = {
                    link.node_id: link
                    for link in NodeSourceLink.objects.filter(
                        task=task,
                        node_id__in=links_to_create_map.keys()
                    )
                }
                ThroughModel = NodeSourceLink.source_chunks.through
                m2m_links_to_create = []
                for node_id, chunk_ids_in_doc_set in links_to_create_map.items():
                    link_instance = link_instance_map.get(node_id)
                    if not link_instance:
                        logger.warning(f"未能在数据库中找到刚创建的 Link (NodeID: {node_id})，跳过 M2M 关联。")
                        continue
                    for chunk_id_in_doc in chunk_ids_in_doc_set:
                        graph_chunk = chunks_map.get(chunk_id_in_doc)
                        if graph_chunk:
                            m2m_links_to_create.append(
                                ThroughModel(nodesourcelink_id=link_instance.id, graphchunk_id=graph_chunk.unique_id)
                            )
                if m2m_links_to_create:
                    logger.info(f"正在批量添加 {len(m2m_links_to_create)} 个 M2M 关联...")
                    ThroughModel.objects.bulk_create(m2m_links_to_create, batch_size=construction_config["BATCH_SIZE"],
                                                     ignore_conflicts=True)
                    logger.info("M2M 关联完成。")

            if edges_to_create:
                logger.info(f"正在批量创建/获取 {len(edges_to_create)} 条 GraphEdge...")
                edges_to_bulk_create = []
                for (source_id, target_id, type) in edges_to_create:
                    edges_to_bulk_create.append(GraphEdge(
                        source_node_id=source_id,
                        target_node_id=target_id,
                        type=type
                    ))
                if edges_to_bulk_create:
                    GraphEdge.objects.bulk_create(
                        edges_to_bulk_create,
                        batch_size=construction_config["BATCH_SIZE"],
                        ignore_conflicts=True
                    )
                logger.info(f"GraphEdge 批量操作完成。")

        logger.info(f"--- 阶段10.3: 事务提交 ---")
    except Exception as e:
        logger.error(f"图谱构建失败: {e}", exc_info=True)
        raise

    logger.info("阶段10 (图谱构建) 成功完成。")