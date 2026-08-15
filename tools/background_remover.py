# -*- coding: utf-8 -*-
"""
AI 抠图工具（rembg / U2Net）
- 去除图片背景，保留主体，输出透明 PNG
依赖：rembg, onnxruntime, pillow
"""
import os
import argparse
from PIL import Image


def remove_background(src_path, dst_path, max_side=800, model="u2netp"):
    """单张抠图"""
    from rembg import new_session, remove

    session = new_session(model)
    pil = Image.open(src_path).convert("RGB")
    w, h = pil.size
    if max(w, h) > max_side:
        k = max_side / max(w, h)
        pil = pil.resize((int(w * k), int(h * k)), Image.LANCZOS)
    out = remove(pil, session=session)  # RGBA
    out.save(dst_path)
    return dst_path


def batch_remove(src_dir, dst_dir, max_side=800):
    """批量抠图"""
    os.makedirs(dst_dir, exist_ok=True)
    results = []
    for name in sorted(os.listdir(src_dir)):
        if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, os.path.splitext(name)[0] + ".png")
        remove_background(src, dst, max_side)
        results.append(dst)
        print(f"  ✓ {name} -> {os.path.basename(dst)}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 抠图工具")
    parser.add_argument("src", help="源图片路径或目录")
    parser.add_argument("dst", help="输出路径或目录")
    parser.add_argument("--batch", action="store_true", help="批量模式（src/dst 为目录）")
    parser.add_argument("--max-side", type=int, default=800, help="最长边限制（加速）")
    args = parser.parse_args()

    if args.batch:
        batch_remove(args.src, args.dst, args.max_side)
    else:
        remove_background(args.src, args.dst, args.max_side)
        print(f"完成: {args.dst}")
