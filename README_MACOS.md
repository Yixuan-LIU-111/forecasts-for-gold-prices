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

## 五、演示模式开关与配置项

系统支持 **演示模式 / 实时模式** 一键切换，无需重启服务：

- **界面操作**：打开仪表盘 → 系统设置 → 模型配置瓦片 →「演示模式」开关；顶栏实时显示「演示模式 / 实时模式」文字标识。
- **运行时切换**：通过接口切换后，后端立即重配置调度器（实时模式挂载采集/信号任务，演示模式卸载），并把结果持久化到 `.env`，服务重启后仍生效。
- 同源托管页面已加 `no-cache` 响应头，切换后刷新即可看到最新界面，不会被浏览器旧缓存命中。

### 相关接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system/demo-mode` | 读取当前 `demo_mode`、调度任务清单、是否已持久化 |
| POST | `/api/v1/system/demo-mode` | 运行时切换 `demo_mode`（请求体 `{"enabled": true/false}`），自动重配置调度器并写回 `.env` |

示例：

```bash
# 查询当前模式
curl http://127.0.0.1:8000/api/v1/system/demo-mode

# 切换到实时模式
curl -X POST http://127.0.0.1:8000/api/v1/system/demo-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### 配置项（`.env`，运行时可改）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEMO_MODE` | `true` | 演示模式：读内置 demo 数据；`false` 切换实时模式 |
| `SCHEDULER_ENABLED` | `true` | 后台调度器总开关；`false` 则完全不启动后台任务 |
| `NEWS_SCRAPE_ENABLED` | `true` | 新闻实时爬取任务开关（Playwright + LLM，不依赖付费外部 API） |
| `NEWS_SCRAPE_INTERVAL_SECONDS` | `300` | 新闻爬取周期（秒） |
| `NEWS_SCRAPE_MAX_ITEMS` | `4` | 每次每站点抓取条数（控制 LLM 调用量） |
| `API_HOST` | `0.0.0.0` | 监听地址（打包后实际绑定 127.0.0.1） |
| `API_PORT` | `8000` | 监听端口 |

> 说明：`demo-mode` 接口写入的是 `DEMO_MODE` 这一行；其余字段改动需手动编辑 `.env` 后重启生效。

## 六、已知限制（非阻塞）

- 新闻实时爬虫（`news_scraper_llm`）依赖独立的 Python venv（playwright/langchain/sqlalchemy），
  未打入 app；缺失时系统会优雅跳过该后台任务，主预测功能不受影响。
