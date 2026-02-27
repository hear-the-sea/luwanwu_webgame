import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def create_icon(key, name, output_dir):
    # Setup
    size = 128
    bg_color = "#FFFDE7"  # Pale yellow (scroll paper)
    border_color = "#8D6E63"  # Brown border
    text_color = "#3E2723"  # Dark ink brown

    img = Image.new("RGB", (size, size), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Draw border (inset by 4px)
    draw.rectangle([4, 4, size - 5, size - 5], outline=border_color, width=4)
    # Draw inner line
    draw.rectangle([10, 10, size - 11, size - 11], outline=border_color, width=1)

    # Fonts
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", 64, index=0)
        font_small = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 16, index=0)
    except Exception as e:
        print("Font error:", e)
        # fallback
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Main Character (first char of name)
    main_char = name[0] if name else "?"

    # Text bounds for centering
    w, h = (
        draw.textsize(main_char, font=font_large)
        if hasattr(draw, "textsize")
        else (font_large.getlength(main_char), 64)
    )
    # Actually calculate accurate bbox in Pillow >= 8.0
    if hasattr(font_large, "getbbox"):
        bbox = font_large.getbbox(main_char)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    draw.text(((size - w) / 2, (size - h) / 2 - 15), main_char, fill=text_color, font=font_large)

    # Full name at the bottom
    if hasattr(font_small, "getbbox"):
        bbox2 = font_small.getbbox(name)
        w2 = bbox2[2] - bbox2[0]
    else:
        w2 = font_small.getlength(name)

    draw.text(((size - w2) / 2, size - 30), name, fill=text_color, font=font_small)

    out_path = os.path.join(output_dir, f"{key}.png")
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    out_dir = str(project_root / "data" / "images" / "items")
    os.makedirs(out_dir, exist_ok=True)

    # just create a single test icon
    create_icon("equip_test_suoyi", "蓑衣", out_dir)
    print("Test icon generated successfully.")
