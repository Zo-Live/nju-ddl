# NJU DDL Tool

汇总 NJU 课程作业 DDL 的小型网站。

## 已实现功能

- 用户注册/登录
- 加密平台 cookie 存储（Fernet，按用户隔离）
- Educoder、NJU LMS、CSLab CMS 三平台作业抓取
- 基于 Playwright 的浏览器辅助登录
- 统一的平台适配器接口（策略模式）
- 作业存储、筛选、排序、手动标记完成
- 定时自动后台刷新
- 57 个后端单元测试覆盖

## 后端

```bash
cd nju-ddl-tool/backend
uv sync
uv run playwright install chromium
export NJU_DDL_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run uvicorn app.main:app --reload --port 8000
```

后端默认使用 SQLite（`./nju_ddl_tool.db`），通过 `NJU_DDL_DATABASE_URL` 可切换。

```bash
uv run pytest tests/ -v    # 运行测试
```

## 前端

```bash
cd nju-ddl-tool/frontend
npm install
npm run dev                 # 开发服务器 http://localhost:5173
npm run build               # 生产构建
```

前端默认请求同源 `/api`；开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。如需覆盖 API 地址：

```bash
VITE_API_BASE=http://other-host:8000 npm run dev
```

仓库根目录的 `./deploy.sh` 默认会安装依赖、构建前端，并启动后端与前端。只安装构建可用：

```bash
./deploy.sh --setup-only
```

## 平台适配器

每个平台适配器实现 `PlatformAdapter` 接口：

- `id` / `name` / `login_url` — 标识
- `is_logged_in(page)` — 检测登录状态
- `fetch_assignments(storage_state)` → `list[NormalizedAssignment]` — 抓取作业

添加新平台只需实现此接口并在 `registry.py` 注册。

## 安全

- 不记录 cookie、密码、storage state 到日志
- 不实现验证码 OCR 绕过（浏览器手动输入）
- 共享部署必须使用 HTTPS
- 更换 `NJU_DDL_SECRET` 会使已加密 cookie 失效
