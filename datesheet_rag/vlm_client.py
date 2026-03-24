
import base64
import json
import logging
from pathlib import Path
from openai import OpenAI
from django.conf import settings
from .prompts import get_vlm_image_analysis_prompt

logger = logging.getLogger(__name__)


def encode_image_to_base64(image_path: Path) -> str:
    """将本地图片文件编码为 Base64 字符串"""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"无法编码图片 {image_path}: {e}")
        return None


def analyze_chart_with_vlm(chart_image_path: Path, page_image_path: Path) -> dict:
    """
    使用 VLM 分析图表。
    :param chart_image_path: /image/ 目录下的图表路径 (Path 对象)
    :param page_image_path: /page/ 目录下的全页路径 (Path 对象)
    :return: 包含 "classification", "title", "description", "applicable_models" 的字典
    """

    # 1. 从 settings.py 获取 VLM 配置
    client = OpenAI(
        api_key=settings.DEFAULT_VLM_API_KEY,
        base_url=settings.DEFAULT_VLM_API_URL,
    )
    vlm_model = settings.DEFAULT_VLM_MODEL_NAME

    # 2. 编码两张图片
    base64_chart_image = encode_image_to_base64(chart_image_path)
    base64_page_image = encode_image_to_base64(page_image_path)

    if not base64_chart_image or not base64_page_image:
        raise ValueError(f"无法编码图像: chart={chart_image_path}, page={page_image_path}")

    # 3. 获取提示词 (已更新)
    prompt_text = get_vlm_image_analysis_prompt()

    # 4. 构建 OpenAI API 请求体 (不变)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_chart_image}"}},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_page_image}"}}
            ]
        }
    ]

    # 5. 发送请求
    logger.info(f"向 VLM ({vlm_model}) 发送请求: {chart_image_path.name}")
    try:
        response = client.chat.completions.create(
            model=vlm_model,
            messages=messages,
            max_tokens=1000,
            temperature=0.0,
            # 确保 VLM 返回 JSON 对象
            response_format={"type": "json_object"},
        )

        raw_response_text = response.choices[0].message.content
        logger.debug(f"VLM 原始响应: {raw_response_text}")

        # 6. 解析 JSON 响应
        # response_format="json_object" 模式下，不需要剥离 ```json
        result_json = json.loads(raw_response_text)

        # 验证必需的字段 (现在包含 'classification')
        required_keys = ["classification", "title", "description", "applicable_models"]
        if not all(k in result_json for k in required_keys):
            raise ValueError(f"VLM 响应 JSON 缺少必要字段。需要: {required_keys}, 收到: {result_json.keys()}")

        # --- 新增：按要求添加绝对路径 ---
        result_json["source_chart_image"] = str(chart_image_path.resolve())
        result_json["source_page_image"] = str(page_image_path.resolve())

        return result_json

    except json.JSONDecodeError:
        logger.error(f"VLM 响应 JSON 解析失败。原始响应: {raw_response_text}")
        raise ValueError(f"VLM 响应不是有效的 JSON: {raw_response_text}")
    except Exception as e:
        logger.error(f"VLM API 调用失败: {e}")
        raise e