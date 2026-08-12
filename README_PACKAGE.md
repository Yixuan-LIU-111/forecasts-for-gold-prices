# 点时成金 — 可执行文件（.exe）打包与部署说明

> 将「黄金价格 30 分钟方向预测系统」打包为 Windows 可执行文件，无需安装 Python 运行环境，双击即可运行。

## 一、交付物说明

打包成功后，`dist\点时成金\` 目录下包含：

| 文件 / 目录 | 说明 |
|---|---|
| `点时成金.exe` | 主程序入口，双击运行 |
| `data\` | 运行时数据库（SQLite），自动生成/初始化 |
| `models\` | 预训练模型（predictor.joblib），首次运行自动拷贝 |
| `logs\` | 运行日志 |
| `.env` | 配置文件（可选，缺省使用内置默认值） |
| `打包说明.txt` | 本说明的副本 |

## 二、打包方法（在 Windows 上执行一次）

### 前置条件
- Windows 10 / 11
- 安装 **Python 3.10 ~ 3.12**（安装时务必勾选 "Add Python to PATH"）

### 一键打包
双击运行项目根目录下的 `build\build_exe.bat`，脚本会自动：
1. 检查 Python 环境
2. 创建 `.venv` 虚拟环境并安装 `requirements.txt` + `pyinstaller`
3. 调用 `build\gold_predictor.spec` 执行打包
4. 将 `.env` 与说明文档拷贝到 `dist\点时成金\`

完成后在 `dist\点时成金\点时成金.exe` 即可得到可执行文件。

### 手动打包（等价命令）
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
pyinstaller build\gold_predictor.spec --noconfirm --clean
```

## 三、运行方式

1. 进入 `dist\点时成金\` 目录
2. **双击 `点时成金.exe`**
3. 程序自动：
   - 创建 `data/`、`models/`、`logs/` 目录
   - 启动 FastAPI 后端（默认 `http://127.0.0.1:8000`）
   - 打开浏览器访问仪表盘 `http://127.0.0.1:8000/dashboard`
4. 控制台显示运行状态；按 `Ctrl+C` 停止

> 首次启动会初始化数据库并导入演示数据，可能需要数秒至十几秒，请耐心等待浏览器弹出。

## 四、路径与资源引用处理（打包核心）

打包的关键是区分 **只读资源** 与 **可写运行时文件**：

| 类别 | 开发环境 | 打包环境 |
|---|---|---|
| 只读代码/资源 | 项目源码目录 | PyInstaller 解压目录 `sys._MEIPASS` |
| 可写数据 (data/models/logs) | 项目目录 | **exe 同级目录** |

实现方式：
- `app/frozen.py` 统一封装路径解析：
  - `IS_FROZEN` 判断是否处于打包环境
  - `PROJECT_ROOT` → 开发时为仓库根，打包时为 `_MEIPASS`
  - `DATA_DIR` / `MODELS_DIR` / `LOGS_DIR` → 始终指向 **exe 同级目录**（可写）
  - `ensure_runtime_dirs()` → 首次运行从 `_MEIPASS` 拷贝预置数据库与模型
- `app/config.py`、`app/main.py` 等全部改用 `app.frozen` 提供路径，不再使用 `Path(__file__).parent.parent` 硬编码
- `build/gold_predictor.spec` 中通过 `datas=` 将 `frontend/dashboard.html`、`app/dashboard/demo_data/`、`models/predictor.joblib` 打包进 `_MEIPASS`

## 五、配置项（可选 `.env`）

在 `dist\点时成金\.env` 中可覆盖默认配置，常用项：

```ini
DEMO_MODE=true                         # 演示模式（读内置 demo 数据）；false 切换实时模式
SCHEDULER_ENABLED=true                 # 后台调度器总开关；false 则完全不启动后台任务
NEWS_SCRAPE_ENABLED=true               # 新闻实时爬取任务开关（不依赖付费外部 API）
NEWS_SCRAPE_INTERVAL_SECONDS=300       # 新闻爬取周期（秒）
NEWS_SCRAPE_MAX_ITEMS=4                # 每次每站点抓取条数（控制 LLM 调用量）
API_HOST=127.0.0.1
API_PORT=8000
OPENAI_API_KEY=                        # 留空则用规则引擎降级
```

> **运行时切换演示模式**：服务启动后也可通过接口实时切换，无需重启。
> `POST /api/v1/system/demo-mode`，请求体 `{"enabled": true|false}`；切换后会自动重配置调度器并写回 `.env`，重启仍生效。
> 前端入口：系统设置 → 模型配置瓦片 →「演示模式」开关。

完整模板见项目根的 `.env.example`。

## 六、常见问题

| 问题 | 解决 |
|---|---|
| 双击无反应 / 闪退 | 在 `dist\点时成金\` 目录打开命令行运行 `点时成金.exe`，查看报错信息 |
| 浏览器未自动打开 | 手动访问 `http://127.0.0.1:8000/dashboard` |
| 端口被占用 | 在 `.env` 中修改 `API_PORT` |
| 杀毒软件拦截 | 将 `点时成金.exe` 加入白名单（PyInstaller 程序偶发被误报） |

## 七、跨平台说明

- 当前 `.exe` 仅能在 **Windows** 运行，需在 Windows 上执行打包。
- 在 macOS / Linux 上验证打包逻辑可用 `build/build_local.sh`：生成对应平台可执行文件，验证 `app.frozen` 路径适配是否生效。
