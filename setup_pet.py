# -*- coding: utf-8 -*-
"""
🐾 桌宠生成器 — 教你怎么做一只自己的 AI 桌宠

用法：
    1. 准备素材：把你的角色帧图放进 frames/你的桌宠名/ 目录
       命名规则（自动识别动作和序号）：
         idle_1.png idle_2.png ...   ← 待机动画（必填）
         walk_1.png walk_2.png ...   ← 走路动画（可选）
         jump_1.png ... / sleep_1.png ...（任意动作名都行）
       图片建议：透明背景 PNG，竖版（高 > 宽），角色居中
    2. 运行：python setup_pet.py
    3. 按提示填写：名字 / 素材确认 / 主题色 / 性格人设
    4. 自动生成：pets_config.json + persona_你的名字.md
    5. 启动 main.py，你的新桌宠就上桌了！

框架完全可复用：加几只桌宠 = 放素材 + 运行本脚本，代码零改动。
"""
import os
import json
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "pets_config.json")

PERSONA_TEMPLATE = """# {name} — 人物性格

## Layer 0：硬规则
1. 你是{name}，不是 AI，不是助手，不是程序。你是桌面上的一只小桌宠。
2. 永远用第一人称说话，简短口语化，1-2 句话，可以用 emoji。
3. 回复控制在 1-2 句话，不用列表，不用长句。

## Layer 1：性格标签
{traits}

## Layer 2：背景设定
{background}

## Layer 3：口头禅 / 说话风格
{style}

## Layer 4：对用户
- 称呼：{call_user}
- 陪伴型桌宠，记住用户说过的重要的事，关心用户的感受。
"""

THEMES = {
    "pink": "粉色可爱",
    "blue": "蓝色沉稳",
    "green": "绿色清新",
    "purple": "紫色神秘",
    "orange": "橙色活力",
}


def ask(prompt, default=""):
    val = input(prompt).strip()
    return val if val else default


def build_persona(name, traits, background, style, call_user):
    return PERSONA_TEMPLATE.format(
        name=name, traits=traits, background=background,
        style=style, call_user=call_user)


def main():
    print("=" * 52)
    print("🐾 桌宠生成器 v1.0 — 创建你的专属 AI 桌宠")
    print("=" * 52)

    # 1. 名字
    name = ask("① 桌宠名字（比如：小美 / 阿黄）：", "")
    if not name:
        print("❌ 名字不能为空，已退出。")
        return

    # 2. 素材目录
    frames_dir = os.path.join(BASE, "frames", name)
    if not os.path.isdir(frames_dir):
        print(f"\n⚠️ 还没找到素材目录 frames/{name}/")
        mk = ask("   要现在创建空目录吗？(y/n，默认 y)：", "y")
        if mk.lower() == "y":
            os.makedirs(frames_dir, exist_ok=True)
            print(f"   ✅ 已创建 {frames_dir}")
            print(f"   请把角色帧图放进去（idle_1.png、walk_1.png…），再重新运行本脚本")
            print("   或先继续填写信息，素材之后补上也能用。")
        else:
            print("❌ 已退出。")
            return
    else:
        pngs = [f for f in os.listdir(frames_dir) if f.lower().endswith(".png")]
        print(f"   ✅ 素材目录存在，检测到 {len(pngs)} 张 PNG")
        if pngs:
            actions = sorted({p.rsplit("_", 1)[0] for p in pngs})
            print(f"   动作集：{', '.join(actions)}")
        else:
            print("   ⚠️ 目录是空的，之后把帧图放进去即可")

    # 3. 主题色
    theme_list = " / ".join(f"{k}({v})" for k, v in THEMES.items())
    theme = ask(f"③ 主题色 [{theme_list}]（默认 pink）：", "pink")
    if theme not in THEMES:
        theme = "pink"
    print(f"   ✅ 主题色：{THEMES[theme]}")

    # 4. 性格人设
    print("\n④ 性格人设（直接回车用默认）")
    traits = ask("   性格标签（如：傲娇但温柔 / 话痨 / 冷静理性）：", "活泼可爱，偶尔傲娇")
    background = ask("   背景设定（如：程序员桌上的一只小猫咪）：", "桌面上的快乐小桌宠")
    style = ask("   说话风格（如：爱用'喵'结尾 / 喜欢讲冷笑话）：", "简短可爱，常用 emoji")
    call_user = ask("   怎么称呼用户（如：主人 / 老板 / 猪头）：", "主人")

    # 5. 生成 persona 文件
    persona_file = f"persona_{name}.md"
    persona = build_persona(name, traits, background, style, call_user)
    with open(os.path.join(BASE, persona_file), "w", encoding="utf-8") as f:
        f.write(persona)
    print(f"   ✅ 已生成人格文件 {persona_file}")

    # 6. 更新配置
    cfg = {"pets": []}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {"pets": []}
    # 去重：同名覆盖
    cfg["pets"] = [p for p in cfg.get("pets", []) if p.get("name") != name]
    cfg["pets"].append({
        "name": name,
        "frames": f"frames/{name}",
        "theme": theme,
        "persona": persona_file,
    })
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"   ✅ 已更新 {CONFIG_PATH}，当前共 {len(cfg['pets'])} 只桌宠")

    # 7. 完成提示
    print("\n" + "=" * 52)
    print(f"🎉 桌宠「{name}」创建完成！")
    print("   启动方式：python main.py")
    print("   想换人格？编辑 persona_{}.md 即可（重启生效）".format(name))
    print("=" * 52)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(0)
