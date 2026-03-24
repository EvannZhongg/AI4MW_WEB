import os
import shutil  # <--- 添加
from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.db.models.signals import post_delete  # <--- 添加
from django.dispatch import receiver
from pgvector.django import VectorField
import uuid

def pdf_upload_path(instance, filename):
    # MEDIA_ROOT/pdf_uploads/<user_id>/<filename>
    return f'pdf_uploads/{instance.user.id}/{filename}'

def md_output_path(instance, filename):
    # MEDIA_ROOT/md_results/<task_id>/<filename>
    return f'md_results/{instance.id}/{filename}'


class PDFParsingTask(models.Model):
    class Status(models.TextChoices):
        # --- 10 阶段流水线 ---
        PENDING = 'PENDING', '排队中'
        TEXT_ANALYSIS = 'TEXT_ANALYSIS', '阶段1: 文本解析'
        VLM_ANALYSIS = 'VLM_ANALYSIS', '阶段2: 图片分析'
        TEXT_CHUNKING = 'TEXT_CHUNKING', '阶段3: 文本分块'
        MODEL_EXTRACTION = 'MODEL_EXTRACTION', '阶段4: 型号抽取/融合'
        PARAM_EXTRACTION = 'PARAM_EXTRACTION', '阶段5: 参数提取'
        PARAM_FUSION = 'PARAM_FUSION', '阶段6: 参数融合/细化'
        IMAGE_ASSOCIATION = 'IMAGE_ASSOCIATION', '阶段7: 图片关联'
        MANUFACTURER_STANDARDIZATION = 'MANUFACTURER_STANDARDIZATION', '阶段8: 厂商标准化'
        CLASSIFICATION = 'CLASSIFICATION', '阶段9: 器件分类'
        GRAPH_CONSTRUCTION = 'GRAPH_CONSTRUCTION', '阶段10: 图谱构建' # <--- 新增
        COMPLETED = 'COMPLETED', '已完成'
        FAILED = 'FAILED', '失败'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pdf_tasks", verbose_name="所属用户")
    pdf_file = models.FileField(upload_to=pdf_upload_path, verbose_name="原始PDF文件")

    status = models.CharField(
        max_length=50,  # 保持 50
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="任务状态"
    )

    celery_task_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="Celery 任务ID")

    pdf_file_hash = models.CharField(max_length=64, db_index=True, blank=True, null=True, verbose_name="PDF文件SHA256")
    text_preview = models.TextField(blank=True, null=True, verbose_name="文本内容预览")
    duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                     verbose_name="重复的任务")

    markdown_file = models.FileField(upload_to=md_output_path, verbose_name="Markdown输出文件", blank=True, null=True)
    output_directory = models.CharField(max_length=512, blank=True, null=True, verbose_name="输出目录路径")

    error_message = models.TextField(blank=True, null=True, verbose_name="错误信息")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return f"Task {self.id} for {self.user.username} - {self.status}"

    def get_pdf_filename(self):
        # ... (此函数保持不变) ...
        full_name = os.path.basename(self.pdf_file.name)
        dot_index = full_name.rfind('.')
        suffix_index = full_name.rfind('_', 0, dot_index if dot_index != -1 else len(full_name))
        if suffix_index != -1 and dot_index != -1 and (dot_index - suffix_index == 8):
            return full_name[:suffix_index] + full_name[dot_index:]
        elif suffix_index != -1 and dot_index == -1 and (len(full_name) - suffix_index == 8):
            return full_name[:suffix_index]
        return full_name

    class Meta:
        ordering = ['-created_at']

@receiver(post_delete, sender=PDFParsingTask)
def _delete_pdf_task_files(sender, instance, **kwargs):
    """
    在 PDFParsingTask 记录从数据库删除后，自动清理其关联的物理文件和目录。
    """
    # 1. 删除原始上传的 PDF 文件
    if instance.pdf_file and instance.pdf_file.storage.exists(instance.pdf_file.name):
        try:
            instance.pdf_file.storage.delete(instance.pdf_file.name)
            print(f"Deleted PDF file: {instance.pdf_file.name}")
        except Exception as e:
            # 记录错误，但继续尝试删除其他文件
            print(f"Error deleting PDF file {instance.pdf_file.name}: {e}")

    # 2. 删除整个输出目录 (md_results/<task_id>/)
    #    这会一并删除 .md 文件和 /image 文件夹
    if instance.output_directory:
        full_output_dir_path = os.path.join(settings.MEDIA_ROOT, instance.output_directory)
        if os.path.isdir(full_output_dir_path):
            try:
                shutil.rmtree(full_output_dir_path)
                print(f"Deleted output directory: {full_output_dir_path}")
            except OSError as e:
                print(f"Error deleting directory {full_output_dir_path}: {e}")

    # 3. (备用方案) 如果 output_directory 为空 (可能任务早期失败)
    #    但 markdown_file 字段仍有值，则单独删除它
    elif instance.markdown_file and instance.markdown_file.storage.exists(instance.markdown_file.name):
         try:
            instance.markdown_file.storage.delete(instance.markdown_file.name)
            print(f"Deleted markdown file (fallback): {instance.markdown_file.name}")
         except Exception as e:
            print(f"Error deleting markdown file {instance.markdown_file.name}: {e}")


# --- 新增：知识图谱模型 (阶段10) ---
#

class GraphChunk(models.Model):
    """
    存储来自 chunks.json 的原始文本块及其向量。
    """
    # 唯一标识符 (例如 "task_39_chunk_1")
    unique_id = models.CharField(max_length=100, unique=True, primary_key=True)
    task = models.ForeignKey(PDFParsingTask, on_delete=models.CASCADE, related_name="graph_chunks")
    chunk_id_in_doc = models.CharField(max_length=50)  # chunks.json中的 "id" (例如 "1", "2")
    text = models.TextField()
    embedding = VectorField(dimensions=settings.DEFAULT_EMBEDDING_DIMENSIONS)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.unique_id

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['task', 'chunk_id_in_doc']),
        ]


class GraphNode(models.Model):
    """
    知识图谱中的一个节点（实体）。
    使用 "readable_id" 作为主键，以实现增量更新 (Upsert)。
    """
    # 节点的可读唯一ID (例如 "Device:ON Semiconductor_UD1006FR")
    node_id = models.CharField(max_length=1024, unique=True, primary_key=True)

    community = models.CharField(max_length=100, db_index=True)  # 例如 "Device", "Manufacturer", "Package type"
    name = models.CharField(max_length=512, db_index=True)  # 键名 (例如 "Name", "Package")
    value = models.TextField(db_index=True)  # 值 (例如 "UD1006FR", "TO-220F-2FS")

    # 存储额外信息，例如图片路径、描述等
    properties = models.JSONField(default=dict, null=True, blank=True)

    # 用于向量搜索的文本和向量
    text_for_embedding = models.TextField()
    embedding = VectorField(dimensions=settings.DEFAULT_EMBEDDING_DIMENSIONS)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.node_id


class GraphEdge(models.Model):
    """
    知识图谱中的一条边（关系）。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_node = models.ForeignKey(GraphNode, on_delete=models.CASCADE, related_name="source_of_edges")
    target_node = models.ForeignKey(GraphNode, on_delete=models.CASCADE, related_name="target_of_edges")
    type = models.CharField(max_length=100, db_index=True)  # 关系类型 (例如 "is produced by")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.source_node_id} -> {self.type} -> {self.target_node_id}"

    class Meta:
        # 确保边是唯一的
        unique_together = ('source_node', 'target_node', 'type')
        ordering = ['created_at']


class NodeSourceLink(models.Model):
    """
    连接节点和其来源的PDF任务及具体Chunks。
    这是实现“删除”功能的关键。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(GraphNode, on_delete=models.CASCADE, related_name="source_links")
    task = models.ForeignKey(PDFParsingTask, on_delete=models.CASCADE, related_name="created_nodes")
    # 一个节点实例（例如 "Package: TO-220F-2FS" from PDF 39）
    # 可能来源于多个chunks (例如 ["1", "5"])
    source_chunks = models.ManyToManyField(GraphChunk, blank=True)

    def __str__(self):
        return f"Node {self.node_id} linked to Task {self.task_id}"

    class Meta:
        unique_together = ('node', 'task')  # 一个节点在一个任务中只应出现一次