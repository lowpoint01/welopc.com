# WelOPC

WelOPC 是一个围绕 Agent 生态和 OPC 场景包构建的 AI 信号雷达。当前仓库来自线上 `welopc.com` 已部署版本，包含 AI HOT 情报工作台、公众号爆文采集、OPC 一人公司筛选、Agent 场景包页面、后台管理端和部署脚本。

## 目录

- `app/`：后端源码、Vue 前端源码、Agent 场景包源码、后台页面、配置模板与部署脚本。
- `app/src/ecom_research/aihot_service.py`：AI HOT 后端服务入口，负责公开接口、后台接口、公众号动态采集、频道筛选、日报与模型增强。
- `app/frontend-vue/`：AI HOT Vue 前端源码。
- `app/agent-vue/`：Agent 场景包 Vue 前端源码。
- `app/admin-web/`：后台管理端静态页面。
- `web-dist/`：当前服务器线上静态发布产物，可作为部署参考。
- `.env.example`：运行环境变量模板，不包含任何真实密钥。

## 已移除内容

为了安全开源，仓库不包含以下线上运行态内容：

- 管理员密码、服务器凭据和运行时 `.env`。
- DeepSeek、GitHub、公众号授权 Cookie、Token 或任何 API Key。
- SQLite 数据库、WAL/SHM 文件、备份包和日志。
- Python 虚拟环境、Node 依赖目录和缓存文件。

## 本地运行后端

```bash
cd app
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
cp ../.env.example .env
python -m ecom_research.aihot_service init
python -m ecom_research.aihot_service serve --host 127.0.0.1 --port 8790
```

Windows PowerShell 可将激活命令换成：

```powershell
.\.venv\Scripts\Activate.ps1
```

## 本地运行 AI HOT 前端

```bash
cd app/frontend-vue
npm install
npm run dev
```

## 本地运行 Agent 场景包前端

```bash
cd app/agent-vue
npm install
npm run dev
```

## 生产部署参考

线上版本使用 Python 后端服务加静态前端发布：

- 后端服务监听 `127.0.0.1:8790`。
- Web 根目录可参考 `web-dist/`。
- 反向代理将 `/ai-hot/api/*` 转发到后端服务。
- 定时任务每日运行 `python -m ecom_research.aihot_service import-latest` 更新内容。

部署前请复制 `.env.example` 为 `.env` 并填入自己的运行路径和模型密钥。
