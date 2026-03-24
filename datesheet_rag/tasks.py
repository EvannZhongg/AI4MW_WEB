from celery import shared_task, chain
from .models import PDFParsingTask
from .utils import process_pdf_task_logic
from .vlm_client import analyze_chart_with_vlm
from .chunking import process_markdown_to_chunks
from .extraction import process_chunks_for_model_extraction
from .merging import process_model_merging
from .param_extraction import process_parameter_extraction
from .param_fusion import process_parameter_fusion
from .param_fusion_refinement import process_parameter_fusion_refinement
from .image_association import process_image_association
from .manufacturer_standardization import process_manufacturer_standardization
from .classification import process_device_classification
from .graph_construction import process_graph_construction
from django.conf import settings
from django.core.files.base import ContentFile
import os
import logging
import hashlib
import shutil
import json
import re
from pathlib import Path
from openai import OpenAI

logger = logging.getLogger(__name__)


# --- 辅助函数 (保持不变) ---
def calculate_sha256(file_path):
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"无法计算哈希 {file_path}: {e}")
        return None


def cleanup_generated_files(output_dir):
    if os.path.isdir(output_dir):
        try:
            shutil.rmtree(output_dir)
            logger.info(f"已清理重复任务的输出目录: {output_dir}")
        except OSError as e:
            logger.error(f"无法清理目录 {output_dir}: {e}")


# --- 编排器任务：启动流水线 (修正为10阶段) ---
@shared_task(bind=True)
def task_pipeline(self, task_db_id):
    """
    这是主编排器。它根据设置构建一个 10 阶段任务链。
    """
    try:
        task = PDFParsingTask.objects.get(id=task_db_id)

        stage1 = run_text_analysis_task.s()
        stage3 = run_chunking_task.s()
        stage4 = run_model_extraction_task.s()
        stage5 = run_param_extraction_task.s()
        stage6 = run_param_fusion_task.s()
        stage7 = run_image_association_task.s()
        stage8 = run_manufacturer_standardization_task.s()
        stage9 = run_classify_device_task.s()
        stage10 = run_graph_construction_task.s() # <--- 新增

        if settings.PDF_PARSER_SAVE_PAGES:
            stage2 = run_vlm_analysis_task.s()
            # 构建链: 1 -> 2 -> ... -> 8 -> 9 -> 10
            pipeline = chain(stage1, stage2, stage3, stage4, stage5, stage6, stage7, stage8, stage9, stage10) # <--- 修改
        else:
            # 构建链: 1 -> 3 -> ... -> 8 -> 9 -> 10
            pipeline = chain(stage1, stage3, stage4, stage5, stage6, stage7, stage8, stage9, stage10) # <--- 修改

        logger.info(f"为任务 {task_db_id} 创建 10 阶段流水线: {pipeline}") # <--- 修改

        pipeline.apply_async(args=[task_db_id])

    except PDFParsingTask.DoesNotExist:
        logger.error(f"流水线启动失败：找不到任务 {task_db_id}")
    except Exception as e:
        logger.error(f"流水线启动失败 {task_db_id}: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[流水线启动失败] {e}"
        task.save(update_fields=['status', 'error_message'])

# --- 阶段1：文本解析 (保持不变) ---
@shared_task(bind=True)
def run_text_analysis_task(self, task_db_id):
    """
    阶段1：执行 Docling 文本解析和去重。
    """

    task = PDFParsingTask.objects.get(id=task_db_id)
    task.celery_task_id = self.request.id
    task.status = PDFParsingTask.Status.TEXT_ANALYSIS
    task.save(update_fields=['celery_task_id', 'status'])

    logger.info(f"阶段1 (文本解析) 开始: {task_db_id} ({task.pdf_file.path})")
    output_dir = os.path.join(settings.MEDIA_ROOT, 'md_results', str(task.id))

    try:
        # (去重逻辑...)
        task.pdf_file_hash = calculate_sha256(task.pdf_file.path)
        if task.pdf_file_hash:
            exact_duplicate = PDFParsingTask.objects.filter(
                user=task.user,
                pdf_file_hash=task.pdf_file_hash,
                status=PDFParsingTask.Status.COMPLETED
            ).exclude(id=task.id).first()
            if exact_duplicate:
                task.status = PDFParsingTask.Status.COMPLETED
                task.duplicate_of = exact_duplicate
                task.error_message = f"文件内容与已完成任务 #{exact_duplicate.id} 完全相同。"
                task.save()
                logger.info(f"任务 {task_db_id} 是精确重复任务 {exact_duplicate.id}")
                return None  # 停止流水线

        # (运行 Docling...)
        md_file_path, image_dir_path = process_pdf_task_logic(
            pdf_file_path_str=task.pdf_file.path,
            output_dir_str=output_dir
        )
        if not md_file_path.exists():
            raise FileNotFoundError("Markdown 文件未成功生成")

        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # (软重复检查...)
        PREVIEW_LENGTH = 1000
        task.text_preview = md_content[:PREVIEW_LENGTH]
        original_filename = task.get_pdf_filename()
        soft_duplicate = PDFParsingTask.objects.filter(
            user=task.user,
            pdf_file__endswith=original_filename,
            text_preview=task.text_preview,
            status=PDFParsingTask.Status.COMPLETED
        ).exclude(id=task.id).first()

        if soft_duplicate:
            task.status = PDFParsingTask.Status.COMPLETED
            task.duplicate_of = soft_duplicate
            task.error_message = f"文件与任务 #{soft_duplicate.id} 的文件名和内容预览相同。"
            task.save()
            cleanup_generated_files(output_dir)
            logger.info(f"任务 {task_db_id} 是软重复任务 {soft_duplicate.id}")
            return None  # 停止流水线

        # (保存文本结果...)
        relative_md_path = os.path.join('md_results', str(task.id), md_file_path.name)
        task.markdown_file.name = relative_md_path
        task.output_directory = os.path.join('md_results', str(task.id))
        task.save()  # 保存 MD 路径和预览

        logger.info(f"任务 {task_db_id} 文本解析完成，传递到下一阶段。")
        return task_db_id  # 传递 ID 给链

    except Exception as e:
        logger.error(f"任务 {task_db_id} (文本解析) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[文本解析失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        cleanup_generated_files(output_dir)
        raise

    # --- 阶段2：VLM 图片分析 (保持不变) ---


@shared_task(bind=True)
def run_vlm_analysis_task(self, task_db_id):
    """
    阶段2：VLM 分析。
    """
    if task_db_id is None:
        logger.info("VLM 阶段跳过，因为任务是重复的。")
        return None

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.VLM_ANALYSIS
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段2 (VLM 分析) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"VLM 任务 {task_db_id} 开始时未找到。")
        return

    try:
        base_dir = Path(settings.MEDIA_ROOT) / task.output_directory
        image_dir = base_dir / "image"
        page_dir = base_dir / "page"
        if not image_dir.exists() or not page_dir.exists():
            raise FileNotFoundError(f"/image 或 /page 目录不存在。")

        page_map = {}
        for page_file in page_dir.glob("page_*.png"):
            match = re.match(r"page_(\d+)\.png", page_file.name)
            if match:
                page_map[int(match.group(1))] = page_file
        if not page_map:
            raise FileNotFoundError(f"/page 目录中未找到有效的 'page_N.png' 图像。")

        all_results = []
        chart_images = list(image_dir.glob("page_*.png"))
        for chart_file in chart_images:
            match = re.match(r"page_(\d+)_", chart_file.name)
            if not match: continue
            page_num = int(match.group(1))
            if page_num not in page_map: continue
            page_file_path = page_map[page_num]
            try:
                vlm_json = analyze_chart_with_vlm(chart_file, page_file_path)
                all_results.append(vlm_json)
            except Exception as e:
                logger.error(f"VLM 分析失败 (图表: {chart_file.name}): {e}")
                pass

        filtered_results = [r for r in all_results if r.get("classification") != "Else"]

        results_dir = base_dir / "results"
        results_dir.mkdir(exist_ok=True)
        json_output_path = results_dir / "image_descriptions.json"

        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(filtered_results, f, indent=2, ensure_ascii=False)

        logger.info(f"任务 {task_db_id} VLM 分析完成，传递到下一阶段。")
        return task_db_id

    except Exception as e:
        logger.error(f"任务 {task_db_id} (VLM 分析) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[VLM 分析失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段3：文本分块 (修改) ---
@shared_task(bind=True)
def run_chunking_task(self, task_db_id):
    """
    阶段3：文本分块。
    """
    if task_db_id is None:
        logger.info("Chunking 阶段跳过，因为任务是重复的。")
        return None
    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.TEXT_CHUNKING
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段3 (文本分块) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Chunking 任务 {task_db_id} 开始时未找到。")
        return
    try:
        if not task.markdown_file or not task.markdown_file.name:
            raise FileNotFoundError("任务记录中没有 Markdown 文件")
        md_file_abs_path = task.markdown_file.path
        if not os.path.exists(md_file_abs_path):
            raise FileNotFoundError(f"Markdown 文件物理丢失: {md_file_abs_path}")

        source_doc_name = task.get_pdf_filename()
        config = settings.PDF_PARSER_CHUNKING
        results_dir_abs_path = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")
        os.makedirs(results_dir_abs_path, exist_ok=True)

        process_markdown_to_chunks(
            md_file_path=md_file_abs_path,
            source_document_name=source_doc_name,
            config=config,
            output_dir_path=results_dir_abs_path
        )

        logger.info(f"任务 {task_db_id} 文本分块完成，传递到下一阶段。")
        return task_db_id  # <--- 传递 ID 给阶段4
    except Exception as e:
        logger.error(f"任务 {task_db_id} (文本分块) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[文本分块失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段4：型号抽取与融合 (合并) ---
@shared_task(bind=True)
def run_model_extraction_task(self, task_db_id):
    """
    阶段4：型号抽取与融合。
    """
    if task_db_id is None:
        logger.info("型号抽取/融合阶段跳过，因为任务是重复的。")
        return None

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.MODEL_EXTRACTION
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段4 (型号抽取与融合) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Model Extraction 任务 {task_db_id} 开始时未找到。")
        return

    try:
        results_dir_abs_path = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")
        basic_chunk_file_path = os.path.join(results_dir_abs_path, "basic_chunk.json")
        if not os.path.exists(basic_chunk_file_path):
            raise FileNotFoundError(f"basic_chunk.json 物理丢失: {basic_chunk_file_path}")

        # --- 4.1 型号抽取 ---
        logger.info(f"阶段4.1 (型号抽取) 子任务开始: {task_db_id}")
        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        extraction_config = settings.PDF_PARSER_MODEL_EXTRACTION
        process_chunks_for_model_extraction(
            basic_chunk_path=basic_chunk_file_path,
            results_dir=results_dir_abs_path,
            llm_config=llm_config,
            extraction_config=extraction_config
        )
        logger.info(f"阶段4.1 (型号抽取) 子任务完成: {task_db_id}")

        # --- 4.2 器件融合 ---
        logger.info(f"阶段4.2 (器件融合) 子任务开始: {task_db_id}")
        model_chunks_file = os.path.join(results_dir_abs_path, "model_chunks.json")
        if not os.path.exists(model_chunks_file):
            raise FileNotFoundError(f"器件融合无法启动：缺少 model_chunks.json")

        # 复用相同的 LLM 配置
        process_model_merging(
            results_dir_path=results_dir_abs_path,
            llm_config=llm_config
        )
        logger.info(f"阶段4.2 (器件融合) 子任务完成: {task_db_id}")

        logger.info(f"任务 {task_db_id} 型号抽取与融合完成，传递到下一阶段。")
        return task_db_id  # <--- 传递 ID 给阶段5

    except Exception as e:
        logger.error(f"任务 {task_db_id} (型号抽取与融合) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[型号抽取/融合失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段5：参数提取 (原阶段6) ---
@shared_task(bind=True)
def run_param_extraction_task(self, task_db_id):
    """
    阶段5：参数提取。
    """
    if task_db_id is None:
        logger.info("参数提取阶段跳过，因为任务是重复的。")
        return None
    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.PARAM_EXTRACTION
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段5 (参数提取) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Param Extraction 任务 {task_db_id} 开始时未找到。")
        return
    try:
        results_dir_abs_path = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")
        merged_model_chunks_file = os.path.join(results_dir_abs_path, "model_chunks_merged.json")
        chunks_file = os.path.join(results_dir_abs_path, "chunks.json")
        if not os.path.exists(merged_model_chunks_file) or not os.path.exists(chunks_file):
            raise FileNotFoundError(f"阶段5无法启动：缺少 model_chunks_merged.json 或 chunks.json")
        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        extraction_config = settings.PDF_PARSER_PARAM_EXTRACTION
        process_parameter_extraction(
            results_dir_path=results_dir_abs_path,
            llm_config=llm_config,
            extraction_config=extraction_config
        )

        logger.info(f"任务 {task_db_id} 参数提取完成，传递到下一阶段。")
        return task_db_id  # <--- **关键修复**：添加这一行

    except Exception as e:
        logger.error(f"任务 {task_db_id} (参数提取) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[参数提取失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段6：参数融合  ---
@shared_task(bind=True)
def run_param_fusion_task(self, task_db_id):
    """
    阶段6：参数融合（包含步骤1：聚合 和 步骤2：LLM细化）。
    (修改：不再是流水线的最后一站)
    """
    if task_db_id is None:
        logger.info("参数融合阶段跳过，因为任务是重复的。")
        return None

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.PARAM_FUSION
        task.save(update_fields=['celery_task_id', 'status'])

        logger.info(f"阶段6 (参数融合) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Param Fusion 任务 {task_db_id} 开始时未找到。")
        return

    try:
        # --- 步骤 1: 聚合 ---
        # ... (聚合代码不变) ...
        logger.info(f"阶段6.1 (聚合) 子任务开始: {task_db_id}")
        results_dir_abs_path_str = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")
        param_results_dir = os.path.join(results_dir_abs_path_str, "param_results")

        if not os.path.exists(param_results_dir):
            raise FileNotFoundError(f"阶段5的输出目录 'param_results' 物理丢失: {param_results_dir}")

        process_parameter_fusion(
            param_results_dir_path=str(param_results_dir)
        )
        logger.info(f"阶段6.1 (聚合) 子任务完成: {task_db_id}")

        # --- 步骤 2: LLM 细化 ---
        # ... (细化代码不变) ...
        logger.info(f"阶段6.2 (LLM细化) 子任务开始: {task_db_id}")

        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        fusion_config = settings.PDF_PARSER_PARAM_FUSION

        process_parameter_fusion_refinement(
            base_input_dir=results_dir_abs_path_str,  # 传入 .../results/ 目录
            llm_config=llm_config,
            fusion_config=fusion_config
        )
        logger.info(f"阶段6.2 (LLM细化) 子任务完成: {task_db_id}")

        # --- 阶段6 结束 (修改) ---
        # 移除 task.status = PDFParsingTask.Status.COMPLETED
        # 移除 task.save(...)
        logger.info(f"任务 {task_db_id} 参数融合与细化完成。传递到阶段7。")
        return task_db_id  # <--- 必须返回 task_db_id 给阶段7

    except Exception as e:
        logger.error(f"任务 {task_db_id} (参数融合/细化) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[参数融合/细化失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段7：图片关联 ---
@shared_task(bind=True)
def run_image_association_task(self, task_db_id):
    """
    阶段7：图片关联。
    (修改：不再是流水线的最后一站)
    """
    if task_db_id is None:
        logger.info("图片关联阶段跳过，因为任务是重复的。")
        return None

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.IMAGE_ASSOCIATION
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段7 (图片关联) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Image Association 任务 {task_db_id} 开始时未找到。")
        return

    try:
        results_dir_abs_path_str = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")

        # ... (检查阶段6输出是否存在) ...
        resolved_dir = os.path.join(results_dir_abs_path_str, "param_results", "resolved")
        if not os.path.exists(resolved_dir):
            raise FileNotFoundError(f"阶段6的输出目录 'resolved' 物理丢失: {resolved_dir}")

        # 检查阶段2的输出是否存在 (如果VLM开启)
        vlm_skipped = False
        if settings.PDF_PARSER_SAVE_PAGES:
            image_desc_file = os.path.join(results_dir_abs_path_str, "image_descriptions.json")
            if not os.path.exists(image_desc_file):
                logger.warning(f"VLM已启用，但 'image_descriptions.json' 未找到。跳过图片关联。")
                vlm_skipped = True
        else:
            logger.info("VLM未启用，跳过图片关联。")
            vlm_skipped = True

        if vlm_skipped:
            # 复制 resolved -> resolved_with_images 以便阶段8可以继续
            try:
                target_dir = os.path.join(results_dir_abs_path_str, "param_results", "resolved_with_images")
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)  # 清理旧的
                shutil.copytree(resolved_dir, target_dir)
                logger.info(f"VLM跳过，已复制 'resolved' 到 'resolved_with_images' 供下一阶段使用。")
            except Exception as e:
                logger.error(f"复制 'resolved' 目录失败: {e}")
                raise

            logger.info(f"任务 {task_db_id} (图片关联) 跳过。传递到阶段8。")
            return task_db_id  # <--- 传递ID

        # --- 如果 VLM 没跳过，执行正常逻辑 ---

        # 准备配置
        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        assoc_config = settings.PDF_PARSER_IMAGE_ASSOCIATION

        # 执行阶段7逻辑
        process_image_association(
            results_dir_path=results_dir_abs_path_str,
            llm_config=llm_config,
            assoc_config=assoc_config
        )

        # --- 阶段7 结束 ---
        # 移除 task.status = PDFParsingTask.Status.COMPLETED
        logger.info(f"任务 {task_db_id} 图片关联完成。传递到阶段8。")
        return task_db_id  # <--- 必须返回 task_db_id 给阶段8

    except Exception as e:
        logger.error(f"任务 {task_db_id} (图片关联) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[图片关联失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段8：厂商标准化 ---
@shared_task(bind=True)
def run_manufacturer_standardization_task(self, task_db_id):
    """
    阶段8：厂商标准化。
    (修改：不再是流水线的最后一站)
    """
    if task_db_id is None:
        logger.info("厂商标准化阶段跳过，因为任务是重复的。")
        return None

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.MANUFACTURER_STANDARDIZATION
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段8 (厂商标准化) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Manufacturer Standardization 任务 {task_db_id} 开始时未找到。")
        return

    try:
        results_dir_abs_path_str = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")

        # 检查阶段7的输出是否存在
        resolved_dir = os.path.join(results_dir_abs_path_str, "param_results", "resolved_with_images")
        if not os.path.exists(resolved_dir):
            raise FileNotFoundError(f"阶段7的输出目录 'resolved_with_images' 物理丢失: {resolved_dir}")

        # 准备配置
        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        embedding_config = {
            "api_key": settings.DEFAULT_EMBEDDING_API_KEY,
            "base_url": settings.DEFAULT_EMBEDDING_API_URL,
            "model_name": settings.DEFAULT_EMBEDDING_MODEL_NAME,
            "dimensions": settings.DEFAULT_EMBEDDING_DIMENSIONS
        }
        standardization_config = settings.PDF_PARSER_MANUFACTURER_STANDARDIZATION

        # 执行阶段8逻辑
        process_manufacturer_standardization(
            results_dir_path=results_dir_abs_path_str,
            llm_config=llm_config,
            embedding_config=embedding_config,
            standardization_config=standardization_config
        )

        # --- 阶段8 结束 ---
        # 移除 COMPLETED 状态设置
        logger.info(f"任务 {task_db_id} 厂商标准化完成。传递到阶段9。")
        return task_db_id  # <--- 必须返回 task_db_id 给阶段9

    except Exception as e:
        logger.error(f"任务 {task_db_id} (厂商标准化) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[厂商标准化失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段9：器件分类 ---
@shared_task(bind=True)
def run_classify_device_task(self, task_db_id):
    """
    阶段9：器件分类。
    (修改：不再是流水线的最后一站)
    """
    if task_db_id is None:
        logger.info("器件分类阶段跳过，因为任务是重复的。")
        return None

    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.CLASSIFICATION
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段9 (器件分类) 开始: {task_db_id}")
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Classification 任务 {task_db_id} 开始时未找到。")
        return

    try:
        results_dir_abs_path_str = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")

        mfg_standardized_dir = os.path.join(results_dir_abs_path_str, "param_results", "manufacturer_standardized")
        if not os.path.exists(mfg_standardized_dir):
            raise FileNotFoundError(f"阶段8的输出目录 'manufacturer_standardized' 物理丢失: {mfg_standardized_dir}")

        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        classification_config = settings.PDF_PARSER_CLASSIFICATION

        process_device_classification(
            results_dir_path=results_dir_abs_path_str,
            llm_config=llm_config,
            classification_config=classification_config
        )

        # --- 阶段9 结束 ---
        # 移除 COMPLETED 状态设置
        logger.info(f"任务 {task_db_id} 器件分类完成。传递到阶段10。")
        return task_db_id  # <--- 必须返回 task_db_id 给阶段10

    except Exception as e:
        logger.error(f"任务 {task_db_id} (器件分类) 失败: {e}", exc_info=True)
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[器件分类失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise


# --- 阶段10：图谱构建 ---
@shared_task(bind=True)
def run_graph_construction_task(self, task_db_id):
    """
    阶段10：图谱构建。
    这是流水线的最后一站。
    """
    if task_db_id is None:
        logger.info("图谱构建阶段跳过，因为任务是重复的。")
        return None

    # --- (*** 关键修复 ***) ---
    # 1. 在 try 块之前获取 task 对象
    try:
        task = PDFParsingTask.objects.get(id=task_db_id)
    except PDFParsingTask.DoesNotExist:
        logger.error(f"Graph Construction 任务 {task_db_id} 开始时未找到。")
        return
    # --- (修复结束) ---

    try:
        # 2. 现在可以安全地设置状态和路径
        task.celery_task_id = self.request.id
        task.status = PDFParsingTask.Status.GRAPH_CONSTRUCTION  # <--- 设置新状态
        task.save(update_fields=['celery_task_id', 'status'])
        logger.info(f"阶段10 (图谱构建) 开始: {task_db_id}")

        results_dir_abs_path_str = os.path.join(settings.MEDIA_ROOT, task.output_directory, "results")

        # 检查阶段9的输出是否存在
        classified_dir = os.path.join(results_dir_abs_path_str, "param_results", "classified_results")
        if not os.path.exists(classified_dir):
            raise FileNotFoundError(f"阶段9的输出目录 'classified_results' 物理丢失: {classified_dir}")

        # 准备配置
        llm_config = {
            "api_key": settings.DEFAULT_LLM_API_KEY,
            "base_url": settings.DEFAULT_LLM_API_URL,
            "model_name": settings.DEFAULT_LLM_MODEL_NAME
        }
        embedding_config = {
            "api_key": settings.DEFAULT_EMBEDDING_API_KEY,
            "base_url": settings.DEFAULT_EMBEDDING_API_URL,
            "model_name": settings.DEFAULT_EMBEDDING_MODEL_NAME,
            "dimensions": settings.DEFAULT_EMBEDDING_DIMENSIONS,
            "BATCH_SIZE": settings.DEFAULT_EMBEDDING_BATCH_SIZE
        }
        construction_config = settings.PDF_PARSER_GRAPH_CONSTRUCTION

        # 执行阶段10逻辑
        process_graph_construction(
            task_db_id=task_db_id,  # <--- 传递 task_id
            results_dir_path=results_dir_abs_path_str,
            llm_config=llm_config,
            embedding_config=embedding_config,
            construction_config=construction_config
        )

        # --- 阶段10 结束 ---
        task.status = PDFParsingTask.Status.COMPLETED
        task.save(update_fields=['status', 'updated_at'])

        logger.info(f"任务 {task_db_id} 图谱构建完成。流水线结束。")
        return f"Success (Graph Construction Complete)"

    except Exception as e:
        logger.error(f"任务 {task_db_id} (图谱构建) 失败: {e}", exc_info=True)
        # 此时 'task' 变量必定存在
        task.status = PDFParsingTask.Status.FAILED
        task.error_message = f"[图谱构建失败] {e}"
        task.save(update_fields=['status', 'error_message'])
        raise