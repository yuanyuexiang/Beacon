# 仓库贡献指南

## 项目结构与模块组织

Beacon 是餐厅菜单销售线索工具。T0/T1 技术探索已完成（`plan/exploration.md`），研究脚本位于 `scripts/`，最小工具按 `plan/development.md` 开发中。

- `欧洲餐厅菜单设计与印刷获客系统方案.md`：主要产品方案。
- `plan/roadmap.md`：验证阶段、开发顺序与实施边界。
- `plan/validation.md`：抽样、证据、渠道准入、指标与阶段判定条件。
- `plan/development.md`：开发任务、依赖关系与验收用例。
- `plan/archive/`：历史方案，不作为当前执行指令。
- `plan/exploration.md`：T0/T1 探索记录、可测量发现、复现命令。
- `plan/validation-report-v1.md`：V 第一批 50 家的漏斗、提取质量、成本与工具问题。
- `plan/model-eval-v1.md`：DeepSeek 转录评测（准确率、观察精确率、成本）。
- `apps/web/public/brand/`：客户（南京小当家文化咨询有限公司）官网的 logo 与主视觉，仅用于客户自己的内部工作台；主题色红 #cf010e、金 #fab736 取自官网。
- 名单来源：`app/integrations/fsa.py`（FSA API）、`app/integrations/overture.py`（Overture Places，缓存在数据目录）；不使用 Google Maps 抓取。
- `plan/tasks.md`、`plan/decisions.md`：任务进度与决策记录。
- `scripts/`：抽样、抓取、探针、提取、样稿渲染脚本；`templates/`：样稿模板；`data/`：受控数据（gitignore）。
- `reports/`：综合研究报告。
- `research_notes/`：按报告主题组织的研究资料。
- `汇报/`：演示材料（`.pptx`）。

采用 Monorepo：`apps/api/`（FastAPI，已实现 D1～D10）、`apps/web/`（Next.js + Ant Design，三组页面已实现），共享包按需放 `packages/`（尚未创建）；根目录 `templates/`（样稿模板）、`infra/`（compose、备份恢复脚本）、`scripts/`（研究脚本）、`docs/操作手册.md`。模块边界见 `plan/development.md`。

## 构建、测试与开发命令

研究脚本（已实测）：

- `python3 scripts/fsa_sample.py <raw.json> --seed N --n K --exclude-awaiting --out <csv>`
- `uv run --python 3.12 --no-project scripts/fetch_evidence.py --fhrsid <id> <url>...`
- `uv run --python 3.12 --no-project --with pdfplumber scripts/menu_probe.py data/evidence --out <json>`
- `uv run --python 3.12 --no-project --with pdfplumber scripts/extract_items.py <pdf> --out <json>`
- `python3 scripts/render_sample.py <spec.json> --out <path>`（本机 Chrome 无头渲染）

Docker 全套（已实测）：`cp infra/.env.example infra/.env && docker compose -f infra/docker-compose.yml up -d --build`（postgres + api 自动迁移 + web，http://localhost:3000）；容器内测试 `docker compose -f infra/docker-compose.yml --profile test run --rm api-test`。

后端（`apps/api`，本机开发，需先 `docker compose -f infra/docker-compose.yml up -d postgres`）：

- `docker compose -f infra/docker-compose.yml up -d postgres`：只启动 PostgreSQL 16（端口 5433，开发库 `beacon`、测试库 `beacon_test`）。
- `cd apps/api && uv sync`：安装依赖（Python 3.12，`.python-version`）。
- `cp apps/api/.env.example apps/api/.env`：填写 `BEACON_*` 变量；`BEACON_DATA_DIR` 必须是绝对路径。模型转录需 `BEACON_LLM_PROVIDER=deepseek` 与 `BEACON_DEEPSEEK_API_KEY`（默认 fake，不调用模型；评测记录 `plan/model-eval-v1.md`）。
- `cd apps/api && uv run alembic upgrade head`：迁移；`uv run alembic revision --autogenerate -m "..."` 生成新迁移。
- `cd apps/api && uv run uvicorn app.main:app --reload --port 8000`：启动 API（`/api/health`、`/api/health/db`）。
- `cd apps/api && uv run pytest`：测试（自动对 `beacon_test` 做 upgrade/downgrade，不依赖网络与真实模型）。
- `cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`：lint 与类型检查。

前端（`apps/web`，已实测）：

- `pnpm install`：根目录 workspace 安装（`pnpm-workspace.yaml` 的 `allowBuilds` 已放行 esbuild、unrs-resolver）。
- `pnpm --filter beacon-web dev`：开发服务器 3000 端口，`/api/*` 重写到 `BEACON_API_URL`（默认 http://localhost:8000）。
- `pnpm --filter beacon-web typecheck`、`lint`、`test`（Vitest）、`build`（Next 生产构建）。
- 页面（管理系统布局：左侧导航 + 顶部面包屑）：`/login`、`/`（仪表盘：漏斗、渠道、成本）、`/leads`（批次与线索：统计、筛选、自动建名单抽屉、导入、批量运行、导出）、`/leads/[id]`（文件、证据与修正、审核、样稿与文案、审批）、`/tasks`（任务、渠道准入、回复回填、抑制名单页签）、`/settings`（流程与边界说明）。

文档工作可使用：

- `rg --files`：查看仓库文件。
- `git diff --check`：检查已跟踪文件改动中的空白字符错误。
- `git diff --stat`、`git status --short`：检查改动范围及新增文件。

项目骨架建立后，将验证过的命令同步到本文件和 `CLAUDE.md`。计划工具包括 uv、pnpm 和 Docker Compose，不应假定它们已经配置。

## 编码风格与命名约定

项目文档使用中文，采用清晰的标题、相对链接和对比表格。保留按主题命名的文件及现有列表缩进。研究结论注明来源，明确区分建议与已确认决策。

目前未配置格式化或代码检查工具。计划采用 Ruff 和 mypy；添加源码时再落实缩进和命名规范。

## 测试要求

文档修改需检查链接、路径，以及方案、路线图和任务清单的一致性，并预览修改后的 Markdown 或演示材料。

计划采用 pytest、Vitest/Testing Library 和 Playwright。优先覆盖渠道准入、审批、拒收抑制及重试规则的成功和失败路径，暂不设全局覆盖率目标。未来测试夹具放在 `apps/api/tests/fixtures/`；普通测试使用本地夹具和 `FakeProvider`。测试命名与实际运行命令待实现时确定。

## 提交与合并请求规范

沿用历史记录，以英文祈使句作为提交标题，例如 `Add proposal …`、`Refactor code structure …`，不强制添加前缀。

每次改动保持聚焦。PR 应说明目的、涉及的文档或里程碑、关联问题或任务，以及已完成的验证。演示材料或未来界面发生变化时附截图。

## 协作流程

开展功能工作前，阅读 `CLAUDE.md`、产品方案和路线图。开始或完成跟踪任务时，更新任务复选框与进度；确定的设计选择记录到 `plan/decisions.md`。

先做技术探索，再开发工具；销售验证独立推进。流程获认可不代表获准联系潜在客户。保留工作区中与当前任务无关的改动。
