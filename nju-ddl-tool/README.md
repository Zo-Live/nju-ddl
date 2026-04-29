# NJU DDL Tool

用于汇总多个 NJU 相关课程平台中未完成作业截止日期的小型共享网站。

## 已实现功能

- 后端 API，支持网站用户注册/登录。
- 按用户隔离的加密平台 cookie 存储。
- Educoder、NJU LMS 和 CSLab CMS 的平台会话记录。
- 基于 Playwright 的浏览器辅助登录会话管理器。
- 统一的平台适配器接口。
- 作业存储、筛选、手动标记完成和手动导入 API。
- 用于平台登录状态、刷新操作和 DDL 展示的 Vue 控制面板。

各平台的实际作业提取代码有意隔离在 `backend/app/platforms/` 中，需通过真实账号抓包分析认证后的平台页面/API 响应来完成。

## 后端

```bash
cd nju-ddl-tool/backend
uv sync
uv run playwright install chromium
export NJU_DDL_SECRET="replace-with-a-long-random-secret"
uv run uvicorn app.main:app --reload --port 8000
```

后端默认使用 SQLite，数据库文件为 `./nju_ddl_tool.db`。

如果需要用户在服务端浏览器中完成登录（例如桌面环境或无头 VNC/Xvfb 部署），在本地开发时可设置：

```bash
export NJU_DDL_PLAYWRIGHT_HEADLESS=false
```

## 前端

```bash
cd nju-ddl-tool/frontend
npm install
npm run dev
```

前端默认连接 `http://127.0.0.1:8000`，可通过以下方式覆盖：

```bash
VITE_API_BASE=http://your-backend-host:8000 npm run dev
```

## 平台适配器开发

每个平台适配器必须实现：

- `login_url`
- `is_logged_in`
- `fetch_assignments`

当前适配器文件：

- `backend/app/platforms/educoder.py`
- `backend/app/platforms/nju_lms.py`
- `backend/app/platforms/cslab_cms.py`

推荐开发流程：

1. 从 UI 发起浏览器登录。
2. 手动完成登录。
3. 使用 Playwright tracing 或浏览器开发者工具定位平台的作业 API/页面。
4. 在对应适配器中实现解析逻辑。
5. 使用脱敏的 HTML/JSON fixture 添加测试。

## 安全注意事项

- 不要记录 cookie、密码、storage state 或认证头到日志中。
- 不要添加验证码 OCR 或绕过验证码的功能。
- 任何共享部署必须使用 HTTPS。
- 更换 `NJU_DDL_SECRET` 前需制定 cookie/会话迁移方案，因为已加密的平台 cookie 依赖此密钥。
