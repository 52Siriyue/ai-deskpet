# -*- coding: utf-8 -*-
"""
动画帧生成工具：从一张角色图（透明 PNG）生成桌宠动画帧
- idle_N.png  呼吸动画（缩放微变 + 上浮）
- walk_N.png  走路动画（整体倾斜摆动 + 起伏）
输出到 frames/ 目录，重启桌宠即生效（无需重新打包）
依赖：pillow
"""
import os
import argparse
from PIL import Image


def generate_frames(src_img, out_dir, idle_frames=6, walk_frames=8):
    """从透明 PNG 生成 idle/walk 动画帧"""
    os.makedirs(out_dir, exist_ok=True)
    img = Image.open(src_img).convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    W, H = img.size

    CW, CH = int(W * 1.15), int(H * 1.22)

    def render(zoom, dy, tilt):
        f = img
        if tilt:
            f = f.rotate(tilt, resample=Image.BICUBIC, expand=False)
        w = max(2, int(W * zoom))
        h = max(2, int(H * zoom))
        f = f.resize((w, h), Image.LANCZOS)
        canvas = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        canvas.paste(f, ((CW - w) // 2, CH - h + int(dy * 6) - int(H * 0.01)), f)
        return canvas

    # idle：呼吸（缩放 1.00→1.035 + 轻微上浮）
    breath = [
        (1.00, 0.0, 0), (1.015, -0.01, 0), (1.03, -0.02, 0),
        (1.035, -0.025, 0), (1.03, -0.02, 0), (1.015, -0.01, 0),
    ]
    # 按 idle_frames 截取或循环
    if idle_frames > 6:
        breath = breath * (idle_frames // 6 + 1)
    breath = breath[:idle_frames]
    for i, (z, dy, t) in enumerate(breath, 1):
        render(z, dy, t).save(os.path.join(out_dir, f"idle_{i}.png"))

    # walk：整体摆动 ±10° + 上下起伏
    walk = [
        (-10, 1.00, 0, 0), (-5, 1.02, -2, 1), (0, 1.03, -3, 2), (5, 1.02, -2, 1),
        (10, 1.00, 0, 0), (5, 1.02, -1, -1), (0, 1.03, -2, -2), (-5, 1.02, -1, -1),
    ]
    if walk_frames > 8:
        walk = walk * (walk_frames // 8 + 1)
    walk = walk[:walk_frames]
    for i, (tilt, z, dy, _) in enumerate(walk, 1):
        render(z, dy, tilt).save(os.path.join(out_dir, f"walk_{i}.png"))

    return sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从角色图生成桌宠动画帧")
    parser.add_argument("src", help="透明 PNG 角色图")
    parser.add_argument("out", help="输出目录（默认 frames/）")
    args = parser.parse_args()
    frames = generate_frames(args.src, args.out)
    print(f"生成 {len(frames)} 帧 -> {args.out}")
    print("  ", ", ".join(frames))
