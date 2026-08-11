# 点时成金 — macOS 可执行文件（.app）使用说明

> 已生成 `dist/点时成金.app`，无需安装 Python，双击即可在 macOS 上运行「黄金价格 30 分钟方向预测系统」。

## 一、运行方式

### 方式 A：双击运行（推荐）
1. 进入 `dist/` 目录
2. **双击 `点时成金.app`**
3. 系统会自动弹出「终端」窗口显示启动日志，并在浏览器打开仪表盘：
   `http://127.0.0.1:8000/dashboard`
4. 关闭终端窗口（或 `Ctrl+C`）即停止服务

### 方式 B：命令行运行
```bash
open "dist/点时成金.app"
# 或直接运行内部可执行文件（便于查看日志）
"dist/点时成金.app/Contents/MacOS/点时成金"
```

## 二、兼容性

- 架构：**Apple Silicon (arm64)**，在 Apple 芯片 Mac 上原生运行；Intel Mac 需重新在本机打包。
- 最低系统版本：已将 Mach-O 最低 SDK 下调至 **macOS 15.5（Sequoia）** 以兼容较低版本。
- 代码签名：**ad-hoc 自签名**（`codesign --force --deep --sign -`），并已移除隔离属性，本机双击无 Gatekeeper 拦截。

> 若要把 app 拷到**另一台 Mac** 使用：首次打开可能仍被拦截，请右键 → 打开，或在终端执行
> `xattr -dr com.apple.quarantine /path/to/点时成金.app`。若要分发给他人，需用 **Apple Developer ID** 证书重签。

## 三、数据与模型存放位置

- 运行时生成的数据库、模型、日志默认落在 **`.app` 同级目录**（如 `dist/data`、`dist/models`、`dist/logs`），
  不在 app 包体内，避免破坏签名。
- 首次启动会自动从内置种子拷贝 `gold_predictor.db` 与 `predictor.joblib` 到上述目录。

## 四、重新打包（如需更新）

```bash
bash build/build_macos.sh
```

脚本会自动：建虚拟环境 → 安装依赖 → PyInstaller 打包 → ad-hoc 签名 → 移除隔离。

## 五、已知限制（非阻塞）

- 新闻实时爬虫（`news_scraper_llm`）依赖独立的 Python venv（playwright/langchain/sqlalchemy），
  未打入 app；缺失时系统会优雅跳过该后台任务，主预测功能不受影响。
