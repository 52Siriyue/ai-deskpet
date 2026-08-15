# 🐾 AI 桌宠（DeskPet）

桌面上的 AI 桌宠框架：双角色桌宠 + LLM 聊天（流式输出）+ 11 个工具 + 全屏动画提醒 + 聊天记录窗口 + 截图/划词问答。

> **已合并两个仓库**：cute-deskpet（经典桌宠） + ai-deskpet（AI 增强）→ 本仓库。
> AI 能力分块在 `ai/` 包，素材工具在 `tools/`，支持多桌宠：上传素材跑一次生成器即可。

## ✨ 功能

| 能力 | 说明 |
|---|---|
| 💬 AI 聊天 | 流式输出 + 打字机逐字显示 + ReAct 推理链可视化，双桌宠独立人格 |
| 🛠️ 11 个工具 | 定时提醒 / 备忘 / 番茄钟 / 查时间 / 计算器 / 联网搜索 / 小游戏 / 自我感知… |
| 🎬 全屏动画提醒 | 按提醒内容智能归类（喝水💧/休息☕/吃饭🍚/工作💻…），优先级最高 |
| 📜 聊天记录窗口 | 桌宠消息靠左、用户靠右，自动弹出，可继续对话 |
| 📷 截图问答 | Win+Shift+S 截图 → 输入问题 → Windows OCR 识别 → 按问题回答 |
| 🔍 划词问答 | 复制文字 → 右键"解释剪贴板文字" |
| 🧠 记忆 | 对话历史 + 长期事实（LLM 自动提取）+ RAG 知识库（备忘录/历史/文档检索） |
| 🤝 多 Agent | 群聊广播（🎭 问他俩）+ 消息路由（提到名字 → 对应桌宠）+ 工具可视化 |
| 🎮 互动 | 双桌宠贴贴 / 猜拳 / 掷骰子 / 猜数字 / 喂食 / 睡觉 / 跟随鼠标 |

## 📁 项目结构（AI 内容分块）

```
deskpet/
├── main.py              # 桌宠主程序（配置驱动，任意数量桌宠）
├── ai/                  # ★ AI 模块分块
│   ├── engine.py        #   引擎：流式 SSE / 工具循环 / 长期记忆
│   ├── knowledge.py     #   RAG 知识库（bigram 检索，零依赖）
│   └── emoji.py         #   表情占位符 → emoji 转换
├── tools/               # 素材工具：抠图 / 帧生成 / 相册读取
├── setup_pet.py         # 🐾 桌宠生成器（上传素材 → 生成桌宠）
├── tests/               # pytest 单元测试
├── ocr.ps1              # Windows 内置 OCR（截图问答，零依赖）
├── build.bat            # 一键打包 EXE
└── pets_config.example.json / .env.example / requirements.txt
```

## 🚀 快速开始

```bash
pip install PyQt5
# 配置 API Key（OpenAI 兼容协议）
cp .env.example .env   # 填入你的 LLM_API_KEY
python main.py
```

## 🐾 做一只你自己的桌宠

```bash
python setup_pet.py
```

1. 准备素材：角色帧图放进 `frames/你的桌宠名/`（`idle_1.png`… 待机、`walk_1.png`… 走路）
2. 运行生成器，填写：名字 / 主题色 / 性格人设
3. 自动生成 `pets_config.json` + `persona_你的名字.md`
4. 启动 `python main.py`，新桌宠上桌

多桌宠 = 多跑几次生成器，代码零改动。配置示例见 `pets_config.example.json`。

## 📁 目录结构

```
AI-DeskPet/
├── main.py               # 桌宠主程序（配置驱动，支持任意数量桌宠）
├── ai_engine.py          # LLM 引擎：流式输出 + Function Calling 工具循环
├── setup_pet.py          # 🐾 桌宠生成器（上传素材 → 生成桌宠）
├── pets_config.example.json  # 桌宠配置模板
├── ocr.ps1               # Windows 内置 OCR（截图问答用，零依赖）
├── frames/               # 角色素材（本地，不入库）
├── persona.md            # 人格文件（本地，含个人信息，不入库）
└── .env                  # API Key（本地，绝不入库）
```

## 🔒 隐私说明

本项目默认不会把以下内容提交到 Git（见 `.gitignore`）：
- `.env`（API Key）、`persona*.md`（人格含个人信息）、`frames/`（素材）、`chat_history_*.json` / `memos.json`（聊天记录）

## 🛠️ 技术要点（学习价值）

- **流式输出**：SSE 解析 + 打字机动画，TTFT 优化
- **Function Calling**：工具注册 + 调用循环 + 多步编排（一次对话连调多个工具）
- **跨线程安全**：后台线程 → Qt 信号 → 主线程更新 UI
- **记忆持久化**：对话历史 JSON 落盘，重启恢复
- **截图 OCR**：Windows.Media.Ocr（WinRT）零依赖识别中文
