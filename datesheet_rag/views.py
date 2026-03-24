# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/views.py

from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import action  # <--- (1) 导入 action
from .models import PDFParsingTask, GraphNode, GraphEdge  # <--- (2) 导入图谱模型 (假设)
from .serializers import PDFParsingTaskSerializer
from .tasks import task_pipeline
from django.db import transaction


class PDFTaskViewSet(viewsets.ModelViewSet):
    """
    用于管理 PDF 解析任务的视图集。
    - POST /: 上传新的 PDF 并创建任务
    - GET /: 获取当前用户的所有任务列表
    - GET /<id>/: 获取特定任务的状态
    - GET /<id>/graph/: 获取任务的知识图谱数据 (新增)
    """
    serializer_class = PDFParsingTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]  # 支持文件上传

    def get_queryset(self):
        # 用户只能看到自己的任务
        return PDFParsingTask.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            return Response({'error': '未找到 "pdf_file" 字段'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. 创建任务实例
        task = PDFParsingTask(
            user=request.user,
            pdf_file=pdf_file,
            status=PDFParsingTask.Status.PENDING
        )
        task.save()  # 保存以获取 ID

        # 2. 启动 Celery 流水线
        try:
            # <--- 修改：调用新的编排器任务 ---
            transaction.on_commit(lambda: task_pipeline.delay(task.id))
        except Exception as e:
            # (异常处理不变)
            task.status = PDFParsingTask.Status.FAILED
            task.error_message = f"无法启动后台任务: {e}"
            task.save()
            return Response(
                {'error': '无法启动后台处理任务，请联系管理员。'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 3. 立即返回 (不变)
        serializer = self.get_serializer(task)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    # 禁用 PUT 和 PATCH
    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    # 允许删除任务
    # destroy 方法 (DELETE /<id>/) 已由 ModelViewSet 默认提供

    # --- (3) 新增的 API 动作 ---
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def graph(self, request, pk=None):
        """
        获取指定 PDF 任务的知识图谱数据 (所有节点和边)。
        对应前端 ECharts GraphVisualizer.vue 的格式。
        """
        try:
            task = self.get_object()
        except Exception:
            return Response({'error': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            # --- 1. (保持不变) 正确的查询逻辑 ---
            nodes = GraphNode.objects.filter(source_links__task=task).distinct()
            edges = GraphEdge.objects.filter(
                source_node__source_links__task=task,
                target_node__source_links__task=task
            ).distinct()

            # --- 2. (*** 关键修改 ***) 格式化节点 (动态标签) ---
            echarts_nodes = []
            for node in nodes:
                label = node.value  # 默认标签

                # 如果是参数，格式为 "键: 值"
                if node.community == 'Parameters':
                    label = f"{node.name}: {node.value}"
                # (对于 Device 和 Category, 默认的 node.value 格式正确)

                echarts_nodes.append({
                    "id": node.node_id,  # 使用 models.py 中的 'node_id'
                    "label": label,  # <--- 使用新格式化的 'label'
                    "group": node.community  # 使用 models.py 中的 'community'
                })

            # --- 3. (保持不变) 格式化边 ---
            echarts_edges = [
                {
                    "source": str(edge.source_node_id),
                    "target": str(edge.target_node_id),
                    "label": edge.type  # 使用 models.py 中的 'type'
                }
                for edge in edges
            ]

            graph_data = {
                "nodes": echarts_nodes,
                "edges": echarts_edges
            }

            return Response(graph_data)

        except AttributeError as e:
            msg = f"序列化图谱数据时出错: {e}。请检查 GraphNode/GraphEdge 模型的字段名。"
            print(f"[GRAPH_API_ERROR] {msg}")
            return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            msg = f"构建图谱 API 响应时发生意外错误: {e}"
            print(f"[GRAPH_API_ERROR] {msg}")
            import traceback
            traceback.print_exc()
            return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)