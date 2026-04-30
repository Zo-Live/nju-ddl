# NJU DDL Tool

汇总南京大学课程作业 DDL 的小型网站。通过 Playwright 浏览器辅助登录，自动抓取三个教学平台的作业数据，统一展示未完成的截止日期。

## 支持的平台

| 平台 | 网址 | 登录方式 |
|---|---|---|
| Educoder（头歌） | `educoder.net` | 手机号 + 密码 |
| NJU LMS | `lms.nju.edu.cn` | NJU 统一身份认证（含图形验证码） |
| CSLab CMS | `cslab-cms.nju.edu.cn` | NJU 统一身份认证（含图形验证码） |

## 功能

- 用户注册/登录
- 浏览器辅助平台登录（Playwright），手动完成验证码
- 加密存储平台 cookie（Fernet），不存储明文密码
- 自动定时刷新作业数据
- 手动标记作业完成状态
- 按截止时间/课程/平台/状态排序
- 手动导入作业

## 快速开始

### 一键部署

```bash
./deploy.sh
```

脚本会自动完成：检查依赖 → 安装后端/前端依赖 → 安装 Chromium → 构建前端 → 生成密钥 → 启动后端和前端。

启动完成后打开 `http://localhost:5173`。默认后端地址为 `http://127.0.0.1:8000`，前端开发服务器会把 `/api` 请求代理到后端。

平台的「登录」需要后端能启动可见 Chromium。`deploy.sh` 会自动检测 `DISPLAY`/`WAYLAND_DISPLAY`：有图形环境时启用可见浏览器；无图形环境时保持 headless，点击平台登录会返回明确的 503 提示。服务器无桌面时请在本机桌面终端运行，或自行配置 Xvfb/noVNC 等远程可视化。

如果只想安装依赖并构建，不启动服务：

```bash
./deploy.sh --setup-only
```

### 手动部署

#### 后端

```bash
cd nju-ddl-tool/backend
uv sync
uv run playwright install chromium
```

启动开发服务器（需要设置加密密钥）：

```bash
export NJU_DDL_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run uvicorn app.main:app --reload --port 8000
```

运行测试：

```bash
uv run pytest tests/ -v
```

#### 前端

```bash
cd nju-ddl-tool/frontend
npm install
npm run dev
```

打开 `http://localhost:5173`，注册账号，然后点击各平台的「登录」按钮完成浏览器登录。平台登录需要可见浏览器；开发模式下前端默认使用同源 `/api`，Vite 会代理到 `http://127.0.0.1:8000`。

#### 生产构建

```bash
# 后端
cd nju-ddl-tool/backend
export NJU_DDL_SECRET="<长随机字符串>"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd nju-ddl-tool/frontend
npm run build     # 输出到 dist/
# 将 dist/ 下的文件部署到任意静态文件服务器
```

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NJU_DDL_SECRET` | `dev-secret-change-me` | 加密密钥，生产环境必换 |
| `NJU_DDL_DATABASE_URL` | `sqlite:///./nju_ddl_tool.db` | 数据库连接字符串 |
| `NJU_DDL_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | CORS 允许的源 |
| `NJU_DDL_PLAYWRIGHT_HEADLESS` | `true` | Playwright 是否 headless；`deploy.sh` 未设置时会按图形环境自动选择 |
| `NJU_DDL_BROWSER_DIR` | `./browser-sessions` | 浏览器用户数据目录 |
| `NJU_DDL_REFRESH_INTERVAL_MINUTES` | `30` | 自动刷新间隔（分钟） |
| `NJU_DDL_REFRESH_INITIAL_DELAY_SECONDS` | `60` | 首次刷新延迟（秒） |
| `NJU_DDL_BACKEND_PORT` | `8000` | `deploy.sh` 本地后端端口 |
| `NJU_DDL_FRONTEND_PORT` | `5173` | `deploy.sh` 本地前端端口 |
| `VITE_API_BASE` | 同源 `/api` | 前端 API 地址（编译时），设置后会覆盖默认同源请求 |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite 开发代理目标 |

## 架构

```
nju-ddl-tool/
├── backend/app/
│   ├── main.py                # FastAPI 应用 & 路由
│   ├── models.py              # ORM 模型
│   ├── schemas.py             # Pydantic 模型
│   ├── config.py              # 配置
│   ├── db.py                  # 数据库引擎
│   ├── security.py            # 密码、令牌、加密
│   ├── platforms/             # 平台适配器（策略模式）
│   │   ├── base.py            # 抽象基类
│   │   ├── educoder.py        # Educoder
│   │   ├── nju_lms.py         # NJU LMS
│   │   ├── cslab_cms.py       # CSLab CMS
│   │   └── registry.py        # 适配器注册表
│   └── services/
│       ├── auth.py            # 认证
│       ├── assignments.py     # 作业 CRUD
│       └── browser_login.py   # 浏览器登录管理
├── frontend/src/
│   ├── App.vue                # 单文件组件
│   ├── api.ts                 # API 客户端
│   └── styles.css             # 全局样式
└── tests/                     # 后端测试
```

## 安全

- 平台 cookie 经 Fernet 加密存储，密钥由 `NJU_DDL_SECRET` 派生
- 不记录 cookie、密码、storage state 到日志
- 生产部署必须使用 HTTPS
- 更换 `NJU_DDL_SECRET` 会导致已加密的 cookie 失效，需要迁移方案
