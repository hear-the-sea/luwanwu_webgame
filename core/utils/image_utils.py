"""图片处理工具"""

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Tuple

from django.core.files.base import ContentFile
from PIL import Image


def get_file_hash(file_path: Path) -> str:
    """
    计算文件的 MD5 哈希值

    Args:
        file_path: 文件路径

    Returns:
        MD5 哈希值（16进制字符串）
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def compress_and_resize_image(
    image_path: Path,
    max_size: Tuple[int, int] = (400, 400),
    quality: int = 85,
    convert_to_webp: bool = True,
) -> Tuple[ContentFile, str]:
    """
    压缩并调整图片大小

    Args:
        image_path: 原始图片路径
        max_size: 最大尺寸 (width, height)
        quality: 压缩质量 (1-100)
        convert_to_webp: 是否转换为 WebP 格式

    Returns:
        (压缩后的文件对象, 文件名)
    """
    with Image.open(image_path) as img:
        # 转换为 RGB 模式（WebP 不支持 RGBA 某些情况）
        if img.mode in ("RGBA", "LA", "P"):
            # 如果有透明通道，保留它
            if img.mode == "P":
                img = img.convert("RGBA")
            # 创建白色背景
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA" or img.mode == "LA":
                background.paste(img, mask=img.split()[-1])  # 使用 alpha 通道作为 mask
            else:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 保持宽高比缩放
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # 保存到内存
        buffer = BytesIO()

        if convert_to_webp:
            # 转换为 WebP 格式
            img.save(buffer, format="WEBP", quality=quality, method=6)
            # 修改文件扩展名
            original_name = image_path.stem
            new_filename = f"{original_name}.webp"
        else:
            # 保持原格式
            img_format = img.format or "JPEG"
            img.save(buffer, format=img_format, quality=quality, optimize=True)
            new_filename = image_path.name

        buffer.seek(0)
        return ContentFile(buffer.read()), new_filename


def get_image_info(image_path: Path) -> dict:
    """
    获取图片信息

    Args:
        image_path: 图片路径

    Returns:
        包含图片信息的字典
    """
    with Image.open(image_path) as img:
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "size_bytes": image_path.stat().st_size,
        }
