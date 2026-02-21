"""
生成占位图片用于测试图片功能
需要安装 Pillow: pip install Pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 项目根目录
BASE_DIR = Path(__file__).parent.parent

# 配色方案（古风色调）
COLORS = {
    "gray": "#8B8B8B",
    "green": "#2F5233",
    "blue": "#4A90E2",
    "purple": "#9B59B6",
    "orange": "#E67E22",
    "red": "#E74C3C",
}


def generate_guest_avatar(name, color, size=128):
    """生成门客头像占位图"""
    # 创建图片
    img = Image.new("RGB", (size, size), color=COLORS.get(color, "#8B8B8B"))
    draw = ImageDraw.Draw(img)

    # 绘制首字母
    try:
        # 尝试使用中文字体
        font = ImageFont.truetype("msyh.ttc", size // 2)  # 微软雅黑
    except OSError:
        try:
            font = ImageFont.truetype("simhei.ttf", size // 2)  # 黑体
        except OSError:
            font = ImageFont.load_default()

    text = name[0] if name else "?"

    # 计算文本位置（居中）
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    position = ((size - text_width) // 2, (size - text_height) // 2 - 10)

    # 绘制文字阴影
    draw.text((position[0] + 2, position[1] + 2), text, fill=(50, 50, 50), font=font)
    # 绘制文字
    draw.text(position, text, fill="white", font=font)

    return img


def generate_item_icon(name, color, size=96):
    """生成物品图标占位图"""
    # 创建圆角矩形图片
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # 绘制圆角矩形背景
    radius = 10
    draw.rounded_rectangle([0, 0, size, size], radius=radius, fill=COLORS.get(color, "#8B8B8B"))

    # 添加边框
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=radius - 2, outline="white", width=3)

    # 绘制物品名称首字母
    try:
        font = ImageFont.truetype("msyh.ttc", size // 3)
    except OSError:
        try:
            font = ImageFont.truetype("simhei.ttf", size // 3)
        except OSError:
            font = ImageFont.load_default()

    text = name[0] if name else "?"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    position = ((size - text_width) // 2, (size - text_height) // 2 - 5)

    draw.text(position, text, fill="white", font=font)

    return img


def main():
    """生成示例占位图片"""
    # 创建目录
    guests_dir = BASE_DIR / "data" / "images" / "guests"
    items_dir = BASE_DIR / "data" / "images" / "items"
    guests_dir.mkdir(parents=True, exist_ok=True)
    items_dir.mkdir(parents=True, exist_ok=True)

    print("Generating guest avatars...")
    # 门客示例
    guests = [
        ("zhaoYun", "blue"),
        ("huangYueYing", "green"),
        ("zhuGeLiang", "purple"),
        ("guanYu", "red"),
        ("zhangFei", "orange"),
    ]

    for name, color in guests:
        img = generate_guest_avatar(name, color)
        filename = f"{name}_placeholder.png"
        filepath = guests_dir / filename
        img.save(filepath)
        print(f"  [OK] {filename}")

    print("\nGenerating item icons...")
    # 物品示例
    items = [
        ("grain", "orange"),
        ("silver", "orange"),
    ]

    for name, color in items:
        img = generate_item_icon(name, color)
        filename = f"{name}_placeholder.png"
        filepath = items_dir / filename
        img.save(filepath)
        print(f"  [OK] {filename}")

    print("\n[DONE] Images saved to:")
    print(f"  Guests: {guests_dir}")
    print(f"  Items: {items_dir}")
    print("\n[NOTE]")
    print("  1. These are simple placeholder images for testing")
    print("  2. For production, use professional artwork")
    print("  3. You can use AI tools to generate better images")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")
        print("\nPlease install Pillow:")
        print("  pip install Pillow")
