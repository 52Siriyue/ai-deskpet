@echo off
chcp 65001 >nul
echo ============================================
echo   DeskPet 一键打包脚本（AI 版）
echo ============================================

echo [1/3] 安装依赖...
pip install -r requirements.txt -q

echo [2/3] 打包 EXE（onedir，含素材/人格/OCR 脚本）...
pyinstaller --onedir --windowed --name DeskPet ^
  --add-data "frames;frames" ^
  --add-data "fonts;fonts" ^
  --add-data "persona.md;." ^
  --add-data "persona_b.md;." ^
  --add-data "ocr.ps1;." ^
  main.py

echo [3/3] 完成！
echo 生成的 EXE 在 dist\DeskPet\DeskPet.exe
echo 提示：
echo   - 首次运行请把 .env.example 复制为 .env 并填入 LLM_API_KEY
echo   - 聊天记录/备忘录/长期记忆自动保存在 EXE 同目录
pause
