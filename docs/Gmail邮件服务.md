# Gmail 邮件服务（D47）

## 本地首次配置

1. 在仓库根目录运行 `python3 scripts/configure_gmail_service.py`。生成 `infra/secrets/gmail-service-token`，已有密钥不覆盖。文件不进 Git、不进镜像。
2. `docker compose -f infra/docker-compose.yml up -d --build`，新增 gmail-service 和 gmail-worker。Gmail HTTP/MCP 无宿主机公开端口，容器运行进程 uid=10001。
3. 已有 OPC 授权可导入：`python3 scripts/configure_gmail_service.py --import-opc`。只复制客户端与刷新令牌到专用服务存储，原文件保持原样，不发送邮件。
4. 打开“设置 → Gmail 邮件服务”，点击“检查连接”。此操作刷新 access token 并读取 Gmail 账户信息，不发送邮件。
5. 发送和批量队列默认关闭；准备开始已确认的邮件任务时再保存开关设置。每日限额 0 表示没有本地额度限制；Google 限额仍生效。

## 网页授权（D73，2026-10-22，本地验收）

日常连接不需要终端或上传 Token：管理员进入“设置 → Gmail 邮箱连接”，首次配置 Web OAuth，之后直接点击“连接 Gmail／重新连接 Gmail”。

1. 在 Google 项目启用 Gmail API，创建 **Web application** OAuth 客户端。Google 项目若处于 External／Testing，添加登录账号为测试用户；这类项目的 Gmail 刷新授权通常七天到期，长期使用前应检查发布与验证要求。
2. 将页面显示的完整回调地址登记到该客户端，上传对应 Web 客户端 JSON。JSON 内的 redirect_uris 是下载时的快照，控制台后续新增回调无需重新下载；Beacon 始终使用服务器配置的当前回调，由 Google 最终校验登记。开发默认 `http://localhost:3000/api/gmail/oauth/callback`；云端 `https://beacon.ai-onestep.com/api/gmail/oauth/callback`。开发／云端建议用不同客户端。本地由浏览器访问 localhost，不需要公网或终端回调；访问域名必须与回调一致。
3. 在“管理员首次配置／更换 Web 客户端”上传 JSON 并保存。仅保存候选配置，不删除原 Token，也不替换当前邮箱。
4. 点击“连接 Gmail”，在正常 Chrome／Safari 中选账号并同意发送和身份权限。回到工作台显示邮箱与授权状态，发送和队列仍暂停。
5. 需要回复同步时再点击“开启／重新授权回复同步”，申请 `gmail.metadata` 邮件头权限。旧 `gmail.readonly` 授权兼容；两者都是 Google 受限权限，metadata 不代表免验证。
6. 核对连接邮箱，先用自己可控的收件邮箱测试单家任务。开启发送、限额 1、批量队列关闭，完整预览确认后才发送。

`invalid_grant` 显示重新连接及 Testing 状态提示；客户端、回调不匹配、取消／测试用户、身份读取、浏览器／会话失败各有处理提示。未展示的 Google 原始响应、Token、code 与客户端 secret 不回显。

重新连接绑定发起管理员、会话版本及 HttpOnly 浏览器 nonce，state 单次使用／十分钟有效，并使用 PKCE S256。配置与令牌通过 Google 验证成功后才替换旧连接；失败保留原凭据。成功后暂停发送、轮换预览密钥，并将 Beacon 中未执行的 preview／ready／queued 标记过期；已发送或结果未知记录不修改。任务与历史保留，重新预览后再执行。

设置页只保留 Web 客户端配置与浏览器授权，不再提供 Desktop／Token 文件导入入口。旧迁移脚本及服务接口仅保留维护兼容，普通用户无需上传 Token。现有有效 Web 授权不受影响。

独立服务仍保存令牌，API 仅代理控制接口，前端不获取 Token。新 SQLite 表 `oauth_sessions_v2` 不改变旧表结构，不新增 PostgreSQL 迁移。仅本地验收，未执行真实 OAuth、未发送、未发布。

参考：[Web OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)、[Token 到期](https://developers.google.com/identity/protocols/oauth2#expiration)、[Gmail 权限](https://developers.google.com/workspace/gmail/api/auth/scopes)。

## 单家发送与批量队列

1. 在线索页完善资料，生成并确认触达消息；没有菜单也可起草询问菜单／负责人的消息。
2. “任务 → 渠道准入”给该邮箱设置 allowed，填写证据和规则版本，创建邮箱任务。
3. 在“触达任务与回复”打开邮箱任务并预览邮件。主题可留空复用已确认消息；正文来自已确认内容，收件人来自准入记录。
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

### 设置页发送测试邮件

连接成功并取得发送权限后，在“发送测试邮件”输入自己的邮箱，点击“预览测试邮件”，核对发件人、收件人和固定正文，再点击“确认发送一封”。

测试无需开启客户发送或批量队列，不创建客户任务，仍受每日限额及重复发送检查约束。成功提示表示 Gmail 已接受，请检查收件箱或垃圾邮件。失败请检查授权、限额及服务记录；结果未知或网络中断时先查 Gmail 已发送邮件，不要直接重复发送。每次预览只能提交一次，修改收件人必须重新预览。

容器内诊断若会写入连接状态，必须使用运行用户：`docker compose -f infra/docker-compose.yml exec --user 10001:10001 -T gmail-service /srv/.venv/bin/python ...`。不要以 root 调用连接检查，否则新建的 0600 状态文件可能无法被服务读取。

设置页刷新不会覆盖尚未保存的发送设置。客户端文件保存成功后清空选择；Gmail 同一邮箱的服务操作互斥、当前操作独立加载，本地表单编辑不随连接检查整体禁用。社媒操作按账号隔离，同账号互斥，应用配置操作与账号操作互斥。

## 2026-10-26 简化发送操作

连接邮箱后直接在门店或任务页预览、确认发送，无需开启额外发送开关。批量确认后自动排队；发送记录中可暂停尚未执行的邮件或继续已暂停邮件。已开始发送或结果未知时先查询结果，避免重复发送。

设置页“高级设置 · 可选发送限额”可设置滚动24小时总量，0为不设系统额外限制。已有自定义额度保留；Google自身额度仍有效。同邮箱重新授权不撤销已有预览，更换邮箱需要重新确认。历史被旧开关暂停的任务显示暂停，显式继续后执行。
