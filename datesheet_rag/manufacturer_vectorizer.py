# pdf_parser/manufacturer_vectorizer.py

import json
import logging
import uuid
import os
from pathlib import Path
from typing import List, Dict
from filelock import FileLock
from openai import OpenAI
import django
import sys

# --- Django 环境设置 ---
# 允许此脚本作为独立脚本运行
# (假设此脚本在 pdf_parser 目录中)
sys.path.append(str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_web.settings')
django.setup()
# --- 必须在 setup() 之后导入 settings ---
from django.conf import settings

# --- 日志配置 ---
logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- 动态、安全地定义文件路径 ---
DATA_DIR = Path(__file__).resolve().parent / "data"
STANDARD_MANUFACTURERS_FILE = DATA_DIR / "standard_manufacturers.json"
OUTPUT_EMBEDDINGS_FILE = DATA_DIR / "manufacturers_with_embeddings.json"


# === 辅助函数 (Helpers) ===

def get_embedding(text: str, client: OpenAI, model: str, dimensions: int) -> List[float]:
    """使用配置的Embedding模型获取嵌入向量。"""
    if not text or not text.strip():
        logger.warning(f"输入文本为空，无法获取嵌入向量。")
        return None
    try:
        response = client.embeddings.create(
            model=model,
            input=text,
            dimensions=dimensions,
            encoding_format="float"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"获取嵌入向量失败 ('{text}'): {e}")
        return None


def load_standard_manufacturers() -> List[Dict]:
    """从JSON文件加载标准厂商列表 (线程安全)。"""
    lock_path = STANDARD_MANUFACTURERS_FILE.with_suffix(".json.lock")
    DATA_DIR.mkdir(exist_ok=True)  # 确保 data 目录存在
    with FileLock(lock_path):
        if not STANDARD_MANUFACTURERS_FILE.exists():
            logger.error(f"标准厂商文件未找到: {STANDARD_MANUFACTURERS_FILE}")
            # 自动创建示例文件的逻辑
            logger.info(f"提示: 标准厂商文件 '{STANDARD_MANUFACTURERS_FILE}' 未找到。正在创建一个示例文件。")
            example = [{"id": "mfg_001", "name": "Texas Instruments", "aliases": ["TI"]}]
            try:
                with open(STANDARD_MANUFACTURERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(example, f, indent=2, ensure_ascii=False)
                logger.info(f"示例文件 '{STANDARD_MANUFACTURERS_FILE}' 已创建。请填充后重新运行脚本。")
            except Exception as e:
                logger.error(f"创建示例文件失败: {e}")
            return []

        try:
            with open(STANDARD_MANUFACTURERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"解析标准厂商JSON文件失败: {STANDARD_MANUFACTURERS_FILE}")
            return []


# === 核心逻辑 ===

def generate_manufacturer_embeddings():
    """
    为厂商列表中的主名称及其所有别名生成嵌入向量，并保存到JSON文件。
    """
    logger.info("--- 开始生成制造商嵌入向量 ---")

    # 1. 初始化客户端 (从 Django settings 读取)
    try:
        client = OpenAI(
            api_key=settings.DEFAULT_EMBEDDING_API_KEY,
            base_url=settings.DEFAULT_EMBEDDING_API_URL
        )
        model_name = settings.DEFAULT_EMBEDDING_MODEL_NAME
        dimensions = settings.DEFAULT_EMBEDDING_DIMENSIONS
        logger.info(f"Embedding客户端初始化成功，使用模型: {model_name}")
    except Exception as e:
        logger.critical(f"初始化OpenAI客户端失败: {e}")
        return

    # 2. 加载标准厂商列表
    manufacturers_list = load_standard_manufacturers()
    if not manufacturers_list:
        logger.critical("未能加载标准厂商列表或列表为空，程序终止。")
        return

    # 3. 生成嵌入并保存
    all_embeddings_data = []
    total_manufacturers_count = len(manufacturers_list)
    logger.info(f"开始为 {total_manufacturers_count} 个厂商的主名称及其别名生成嵌入向量...")

    for i, mfg_data in enumerate(manufacturers_list):
        logger.info(f"\n处理厂商 {i + 1}/{total_manufacturers_count}: {mfg_data.get('name', 'N/A')}")

        texts_to_process = []
        if primary_name := mfg_data.get("name"):
            texts_to_process.append(primary_name)

        if aliases := mfg_data.get("aliases", []):
            texts_to_process.extend(alias for alias in aliases if isinstance(alias, str) and alias.strip())

        if not texts_to_process:
            logger.warning(f"厂商 ID='{mfg_data.get('id', 'N/A')}' 没有有效的名称或别名。")
            continue

        for text in texts_to_process:
            logger.info(f"  正在获取 '{text}' 的嵌入向量...")
            embedding_vector = get_embedding(text, client, model_name, dimensions)

            # 为每个文本（主名称或别名）创建一个独立的条目
            entry_data = {
                "id": mfg_data.get("id"),
                "name": mfg_data.get("name"),
                "text_for_embedding": text,
                "embedding": embedding_vector,
                "aliases": mfg_data.get("aliases", [])  # 保留原始别名列表信息
            }
            if embedding_vector is None:
                entry_data["error_embedding"] = f"Failed to get embedding for '{text}'"

            all_embeddings_data.append(entry_data)

    # 4. 将带有嵌入向量的数据写入文件（带锁）
    lock_path = OUTPUT_EMBEDDINGS_FILE.with_suffix(".json.lock")
    with FileLock(lock_path):
        try:
            with open(OUTPUT_EMBEDDINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_embeddings_data, f, ensure_ascii=False, indent=2)
            logger.info(f"\n成功将 {len(all_embeddings_data)} 个条目保存到: {OUTPUT_EMBEDDINGS_FILE}")
        except Exception as e:
            logger.error(f"无法写入输出文件 {OUTPUT_EMBEDDINGS_FILE}: {e}")

    logger.info("--- 制造商嵌入向量生成完毕 ---")


# === 独立运行功能 ===
if __name__ == "__main__":
    logger.info("以独立脚本模式运行制造商向量生成器...")
    logger.info(f"将使用Django设置: {os.environ['DJANGO_SETTINGS_MODULE']}")
    logger.info(f"标准厂商文件: {STANDARD_MANUFACTURERS_FILE}")
    logger.info(f"输出嵌入文件: {OUTPUT_EMBEDDINGS_FILE}")
    generate_manufacturer_embeddings()
    logger.info("脚本执行完毕。")