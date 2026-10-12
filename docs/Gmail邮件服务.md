# Gmail 邮件服务（D47）

## 本地首次配置

1. 在仓库根目录运行 `python3 scripts/configure_gmail_service.py`。生成 `infra/secrets/gmail-service-token`，已有密钥不覆盖。文件不进 Git、不进镜像。
2. `docker compose -f infra/docker-compose.yml up -d --build`，新增 gmail-service 和 gmail-worker。Gmail HTTP/MCP 无宿主机公开端口，容器运行进程 uid=10001。
3. 已有 OPC 授权可导入：`python3 scripts/configure_gmail_service.py --import-opc`。只复制客户端与刷新令牌到专用服务存储，原文件保持原样，不发送邮件。
4. 打开“设置 → Gmail 邮件服务”，点击“检查连接”。此操作刷新 access token 并读取 Gmail 账户信息，不发送邮件。
5. 发送和批量队列默认关闭；准备开始已确认的邮件任务时再保存开关设置。每日限额 0 表示没有本地额度限制；Google 限额仍生效。

## OAuth 管理与服务器部署

- 设置页“配置 OAuth 或导入已有授权”上传 Google OAuth 客户端 JSON；可同时上传兼容的已有 Token JSON（包含 scope、refresh_token，OPC 格式兼容）。只上传客户端会清除旧令牌，需要重新授权。
- 服务器“连接 / 重新授权 Gmail”使用 Web application 类型客户端，Google Cloud 中登记完全相同的回调地址。`BEACON_GMAIL_REDIRECT_URI` 默认 `http://localhost:3000/api/gmail/oauth/callback`；部署时改为实际 HTTPS 域名。
- 原 Desktop 客户端 + refresh token 可导入离线使用；不将 Desktop 客户端直接用于服务器 Web 授权回调。
- 现有 OAuth 客户端和 refresh token 必须属于同一 Google Cloud 客户端。导入检查未验证 Google 项目发布状态；External/Testing 的 Gmail 刷新令牌可能七天过期，需在 Google Cloud 检查。
- `BEACON_GMAIL_PROXY` 可配置 HTTP CONNECT 代理，本机容器示例 `http://host.docker.internal:7890`；服务器按网络情况设置，不要求代理。
- 服务访问密钥和 Google OAuth 令牌不同：前者通过 Compose secret 给 API 与邮件服务；后者仅在 gmail-service 的 `beacon-gmail-data` 卷中持久化。Compose secret 不是自动加密密钥库；备份卷含敏感数据，需限制访问。
- 导入或重新授权会暂停发送并使旧预览令牌失效；避免旧账号审批的邮件从新账号发出。断开仅移除服务中令牌并暂停发送，不代表撤销 Google Cloud 侧授权。

## 单家发送与批量队列

1. 在线索页完成菜单审核、生成并审批文案。
2. “任务 → 渠道准入”给该邮箱设置 allowed，填写证据和规则版本，创建邮箱任务。
3. “任务 → Gmail 邮件”选择任务、输入主题，点击预览。每封正文来自其已审批内容，收件人来自准入记录。
4. 弹窗完整展示所有收件人、主题和正文；勾选已核对后确认。单家进入 ready，多家进入 queued；每封独立发送，不抄送其他客户。
5. 每次发送前再次复核地址、文案版本、准入、复核日期、抑制和预览有效期。完整预览令牌 30 分钟有效，过期需重新预览确认，不能靠后台自行延长。
6. 批量队列默认暂停，需要设置页打开队列执行。暂停开关阻止后续请求，不承诺撤回已经提交给 Gmail 的邮件。
7. 取消待执行邮件在发送记录中操作；已开始发送或结果未知不可直接取消或重发。其他渠道仍人工联系与回填。

## 结果、回复与恢复

- Gmail 返回有效 message ID 后才标记“已通过 Gmail 发送”，保存 thread ID、发送时间、审批人和发送尝试；任务、漏斗与导出都计入已发送。
- 发送网络中断标记 unknown，不自动重试。点“查询发送结果”读取服务持久审计；可恢复已知成功结果。服务 pending/unknown 审计同样阻止重复。
- 重启保留已审批队列；超过五分钟的 sending 项只查询结果、不重复 POST。若服务器审计也未知，需要核对 Gmail 已发送邮件后按维护工具处理，不自动猜测失败。维护步骤：先在设置页暂停发送，用发送记录接口 `/api/gmail/deliveries` 的 preview_key（即 request_key）执行 `docker compose -f infra/docker-compose.yml exec --user 10001 gmail-service /srv/.venv/bin/python -m gmail_service.maintenance <request_key> --status sent --message-id <gmail_message_id> --note "已核对依据"`；明确未发送时用 `--status failed`，不填 message ID。该命令不发送邮件；再在 Beacon 点“查询发送结果”同步。
- worker 每分钟同步最多 20 个已发送线程，循环轮转；可手动点击“同步回复”。只获取邮件头元数据，重复回复按 Gmail message ID 幂等。收到回复暂停待处理任务；不从标题推断拒收、退订或意向。拒收/退订继续在回复回填中明确记录。
- 邮件服务 sqlite 发送尝试审计、账户/策略和 OAuth 状态在专用卷；Beacon 业务状态在 PostgreSQL。需同时备份恢复两者，以免丢失防重复依据。单实例 worker 为当前部署边界。

## MCP 与开发验证

独立服务使用 MCP Streamable HTTP，Compose 内地址 `http://gmail-service:8090/mcp/`，Bearer 访问密钥通过文件读取。工具：gmail_auth_status、gmail_preview_email、gmail_send_approved_email、gmail_get_send_status、gmail_check_replies。MCP 与 HTTP 共享审批令牌、发送开关、滚动限额及防重复审计。现有 OPC 插件保持不变，不自动把它切换到新服务；对外部署 MCP 需配置 HTTPS、允许的 Host/Origin 和访问控制。

- 后端测试：`cd apps/api && uv run pytest`。
- 邮件服务测试：`cd services/gmail && uv sync --python 3.12 && uv run pytest -q`。
- 前端检查：`pnpm --filter beacon-web typecheck && pnpm --filter beacon-web test && pnpm --filter beacon-web build`。

普通测试禁止访问真实 Gmail；真实导入、OAuth 刷新和账户连接检查单列记录。当前不向客户发送开发测试邮件。

依据：[Google OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)、[Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)、[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。
