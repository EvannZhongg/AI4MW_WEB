# pdf_parser/signals.py

import logging
from django.db import transaction
from django.db.models import Q
from django.dispatch import receiver
from django.db.models.signals import post_delete
from api.models import Device as ApiDevice
from .models import GraphNode, GraphEdge, NodeSourceLink

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=ApiDevice)
def delete_associated_graph_data(sender, instance, **kwargs):
    """
    在 ApiDevice 被删除后，触发此信号。

    它将执行以下操作:
    1. 找到所有与被删除器件名称匹配的 "Device" 类型的 GraphNode。
    2. 收集所有与这些 "Device" 节点直接相连的 "child" 节点 (参数、图片等)。
    3. 在一个事务中，删除 "Device" 节点 (这将级联删除所有连接的边)。
    4. 检查所有 "child" 节点，如果它们不再连接任何其他边 (即成为孤儿)，则一并删除。
    """

    device_name = instance.device_number
    if not device_name:
        return

    logger.info(f"[Signal] 接收到 ApiDevice 的删除信号: {device_name}")

    # 1. 找到所有匹配的 GraphNode (一个器件名称可能对应多个制造商)
    device_nodes_to_delete = GraphNode.objects.filter(
        community="Device",
        value=device_name
    )

    if not device_nodes_to_delete.exists():
        logger.info(f"[Signal] 未在知识图谱中找到 {device_name} 的匹配节点，跳过清理。")
        return

    # 2. 收集所有潜在的孤儿节点
    nodes_to_prune = set()
    for device_node in device_nodes_to_delete:
        # 查找所有与此 Device 节点相连的边 (无论方向)
        connected_edges = GraphEdge.objects.filter(
            Q(source_node=device_node) | Q(target_node=device_node)
        )

        # 将边的另一端节点ID添加到待检查列表
        for edge in connected_edges:
            if edge.source_node_id != device_node.node_id:
                nodes_to_prune.add(edge.source_node_id)
            if edge.target_node_id != device_node.node_id:
                nodes_to_prune.add(edge.target_node_id)

    logger.info(
        f"[Signal] 准备清理 {device_nodes_to_delete.count()} 个 Device 节点和 {len(nodes_to_prune)} 个潜在的孤儿节点。")

    try:
        with transaction.atomic():
            # 3. 删除 "Device" 节点
            # (这将自动级联删除所有连接的 GraphEdge 和 NodeSourceLink)
            delete_result = device_nodes_to_delete.delete()
            logger.info(f"[Signal] 已删除 {delete_result[0]} 个 Device 节点及其关联。")

            # 4. 检查并删除孤儿节点
            if nodes_to_prune:
                orphaned_node_ids = []

                # 重新查询这些节点，检查它们是否还连接有任何边
                nodes_to_check = GraphNode.objects.filter(node_id__in=list(nodes_to_prune))

                for node in nodes_to_check:
                    # 检查是否还存在与此节点相关的 *任何* 边
                    has_edges = GraphEdge.objects.filter(
                        Q(source_node=node) | Q(target_node=node)
                    ).exists()

                    if not has_edges:
                        orphaned_node_ids.append(node.node_id)

                # 5. 批量删除所有已确认的孤儿节点
                if orphaned_node_ids:
                    logger.info(f"[Signal] 发现 {len(orphaned_node_ids)} 个孤儿节点，正在删除...")
                    # 删除这些节点将自动级联删除它们剩余的 NodeSourceLink
                    orphan_delete_result = GraphNode.objects.filter(node_id__in=orphaned_node_ids).delete()
                    logger.info(f"[Signal] 孤儿节点清理完毕: {orphan_delete_result[0]} 个节点被删除。")
                else:
                    logger.info(f"[Signal] 没有发现孤儿节点，无需清理。")

    except Exception as e:
        logger.error(f"[Signal] 清理图谱数据时发生错误 (Device: {device_name}): {e}", exc_info=True)
        # 错误发生，事务将自动回滚