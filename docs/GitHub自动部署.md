# GitHub 自动部署操作说明

## 部署范围

用户于 2026-10-14 调整发布策略：向 `main` 提交只自动执行 CI 和构建 GHCR 镜像，不自动更新服务器。先完成本地测试，用户明确确认发布后，手动运行工作流并勾选 `deploy`；该选项默认关闭。PR 只检查；失败的测试不发布。服务器为 `18.175.156.130`。访问域名为 `https://beacon.ai-onestep.com`。Traefik 是独立基础设施，应用发布不重启它。

仓库：`yuanyuexiang/Beacon`。流水线入口是 [ci-cd.yml](../.github/workflows/ci-cd.yml)。构建与发布都在 GitHub 托管 runner 上运行，服务器不安装 runner、不现场编译源码。

## 文件与服务器布局

| 文件 | 用途 |
|---|---|
| [docker-compose-traefik.yaml](../infra/docker-compose-traefik.yaml) | 基础 HTTPS 入口及共享 `matrix-network`；公网 Dashboard 默认关闭 |
| [docker-compose.production.yaml](../infra/docker-compose.production.yaml) | 独立业务栈，只使用镜像；没有公网数据库／API／内部服务端口 |
| [gateway.py](../infra/deploy/gateway.py) | 服务器固定发布入口，锁、备份、一次迁移、验证、回滚 |
| [send_release.py](../infra/deploy/send_release.py) | CI 校验五个镜像 digest 后通过受限 SSH 提交清单 |
| [compatibility.json](../infra/deploy/compatibility.json) | 目标迁移版本及旧数据格式回滚声明 |
| [bootstrap_server.py](../infra/deploy/bootstrap_server.py) | 管理员首次配置或显式更新发布规范 |
| [validate.py](../infra/deploy/validate.py) | 无真实凭据的 Compose 与迁移声明检查 |

服务器使用 `/opt/beacon/config`、`releases`、`state`、`backups`，权限为 root 私有。发布入口安装在 `/usr/local/lib/beacon-deploy/gateway.py`。基础 Traefik 的实际文件位于 `/home/ubuntu/infrastructure/docker-compose.yaml`，首次调整会备份原文件及保留 ACME 数据。

固定数据卷为 `beacon-pgdata`、`beacon-data`、`beacon-gmail-data`、`beacon-meta-data`。不运行 `down -v`，不自动数据库降级或恢复旧数据库。现有本机开发文件 [docker-compose.yml](../infra/docker-compose.yml) 保留独立使用。

## 首次配置

本次已连接管理员 `ubuntu` 并记录用户接受的首次主机密钥。其他机器首次连接应核对服务器指纹；后续 CI 严格校验已保存密钥，不自动 `ssh-keyscan` 信任新结果。

```bash
chmod 400 Beacon.pem
uv run --project apps/api python infra/deploy/bootstrap_server.py --key Beacon.pem
```

此操作使用管理密钥准备独立 `beacon-deploy` 用户、固定 sudo 入口及配置。CI 的私钥保存在本机受控 `data/devops/beacon-deploy-key`，不是管理用 `Beacon.pem`。SSH key 限制交互终端与转发，并强制执行固定发布程序。

配置文件首次生成后保留已有值，不覆盖现有账号、数据库密码或第三方密钥。首次管理员密码随机生成；本次登录信息保存在本机受控 `data/devops/server-login.json`，不提交 Git，不输出到 CI。服务器配置包含应用运行凭据；仅按需复制本机已有的后端集成配置，不复制本机代理、Google 浏览器 profile 或 Gmail OAuth 会话。

部署身份仍具有受控的 Docker 发布权限。仓库写权限、工作流修改权限和 CI 私钥属于信任边界；不能将它们开放给不可信代码。

### GitHub 仓库配置

| 类型 | 名称 | 内容 |
|---|---|---|
| Secret | `BEACON_DEPLOY_SSH_KEY` | 独立部署私钥 |
| Secret | `BEACON_DEPLOY_KNOWN_HOSTS` | 已确认的服务器主机密钥 |
| Variable | `BEACON_DEPLOY_HOST` | `18.175.156.130` |
| Variable | `BEACON_DEPLOY_USER` | `beacon-deploy` |
| Variable | `BEACON_DOMAIN` | `beacon.ai-onestep.com` |

不需要长期 GHCR PAT。发布 job 使用 `GITHUB_TOKEN` 的 `packages:write`，部署 job 只用 `packages:read`，经 SSH stdin 传给服务器用于本次拉取。临时 Docker 配置在发布结束后清除，Token 不写入发布清单。新 package 通过源码 label 关联本仓库，需保留本仓库的读取权限。

## 流水线顺序

1. 后端在临时 PostgreSQL 中跑测试、Ruff、mypy；前端跑 typecheck、lint、Vitest 和生产构建；Gmail／Meta 独立测试；部署脚本测试及配置检查。
2. 全部通过后构建 `beacon-api`、`beacon-web`、`beacon-gmail`、`beacon-meta`。两个 worker 复用 API 镜像。服务器为 x86_64，构建 `linux/amd64`。
3. 推送 `sha-提交SHA` 标记，实际部署固定 `@sha256:...`，同时生成 SBOM 和 provenance。Actions 及基础镜像均固定完整 SHA／digest。
4. 部署 job 不抢断已运行发布，服务器还使用文件锁，并拒绝较旧工作流覆盖已上线的新版本。
5. 校验部署规范和磁盘；先拉完镜像，再停止 worker 和应用写入；备份数据库、资产和两个凭据卷。
6. 运行一次性 `migrate`；API 启动命令不再包含迁移。只运行一个 API 进程，保持当前后台任务与浏览器心跳约束。
7. 启动应用并验证容器健康、数据库连通、公网 HTTPS、Web 与 API 的提交 SHA。通过后启动 worker，并保存当前／上一发布清单。

API `/api/health` 和 Web `/healthz` 返回实际运行的提交 SHA。首张证书可能需要等待基础配置的 90 秒 DNS 检查，发布程序会有界等待。生产会话设置 Secure Cookie；Meta 配置页默认回调随实际域名生成，Gmail 回调由业务 Compose 设置为 HTTPS 域名。

CI 不读取应用密钥，不发送真实客户消息。发布不改业务发送开关；新 Gmail／Meta 服务仍默认暂停。

## 回滚与失败处理

镜像拉取失败发生在停止服务之前，不影响已运行版本。备份失败不会继续迁移；有上一版本时恢复上一版本应用。候选应用不健康时，只有数据结构与持久化格式兼容才自动回滚镜像，流水线仍报告失败。

新增迁移必须更新 `compatibility.json` 的 `migration_head`，否则 CI 阻断。数据库 revision 不变且 provider 存储格式兼容时可回滚；revision 改变时须在 `rollback_compatible_from` 明确声明对应旧版本，并确认新结构能被旧程序读取。服务 SQLite／JSON 格式不兼容时将 `provider_storage_compatible` 设为 false。

不兼容或发布中断会保留 `/opt/beacon/state/pending.json`，停止继续覆盖。管理员需核对其中阶段、数据库 revision、`releases/*/deploy.log` 和实际服务状态，确认恢复或完成方案后再清理该记录；不要直接删除记录来跳过未确认状态。

应用发布清单在 `state/current.json`，上一成功版本在 `state/previous.json`；失败回滚另记 `state/last_failure.json`。日志与备份不进入 GitHub artifact，避免上传业务凭据或证据。

## 基础设施升级与维护

业务源码提交不会自动上线。用户确认发布后，通过 Actions 的 Run workflow 在 main 上运行并勾选 deploy；或执行 `gh workflow run ci-cd.yml --ref main -f deploy=true`。发布前核对 main 对应提交已经完成本地验证；未获用户明确确认时不得触发 deploy=true。修改生产 Compose 或固定 gateway 时，先用管理员 bootstrap 同步相同版本，再提交并发布；脚本 hash 不一致会在停止服务前拒绝部署。Traefik 自身升级独立执行，不混入应用 CD。

发布前备份包含校验和，并检查数据库 dump 可被 pg_restore 读取；完整恢复演练应在独立环境进行。默认保留最近至少 5 份完整备份，超过 14 天的更旧完整备份在成功发布后清理；不自动清理未完成备份或上一版本镜像。

当前备份仍在同一台服务器。进入正式生产前再落实加密异机备份、恢复演练、外部可用性告警及主机维护；单机不提供主机级高可用。发送／Maps／分析等正在执行任务在发布时可能中断，未知发送继续走现有对账规则，分析按界面状态重试。

### 本地检查

```bash
uv run --project apps/api python infra/deploy/validate.py
uv run --project apps/api python -m pytest tests/deploy -q
uv run --project apps/api ruff check --config apps/api/pyproject.toml infra/deploy tests/deploy
actionlint .github/workflows/ci-cd.yml
```

后端、前端及 provider 使用各自现有命令。提交触发后在 [GitHub Actions](https://github.com/yuanyuexiang/Beacon/actions) 查看结果；流水线失败时先看失败阶段，再核对服务器发布状态。

参考：[GHCR 认证与仓库权限](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)、[GitHub Actions 安全实践](https://docs.github.com/en/actions/reference/security/secure-use)、[Docker 构建来源与 SBOM](https://docs.docker.com/build/ci/github-actions/attestations/)、[Traefik Dashboard 安全](https://doc.traefik.io/traefik/operations/dashboard/)。


## 实际验收记录

2026-10-13：提交 `3acfcb7` 的 [GitHub Actions](https://github.com/yuanyuexiang/Beacon/actions/runs/38281693112) 全流程成功。270 后端、两个 provider 各 11 测试、15 个部署测试及 8 前端测试通过；四个镜像推送 GHCR 后，服务器完成一致性备份、迁移、应用健康检查、公网 HTTPS 与双端提交版本验证，再启动两个 worker。首次调试的两次 create 参数失败均发生在迁移之前，已验证初始库无迁移后归档失败记录，并加入实际 CLI 参数校验。

D50 扩展：新增第五个 GHCR 镜像 `beacon-maps`、`maps-worker` 与 `beacon-maps-data` 备份。升级前先同步 bootstrap；首轮兼容旧 release 时补充 Maps 镜像引用，使新固定 Compose 能停止或回滚上一版本。密钥保留在服务器，不写入 Actions secrets。


D57（2026-10-15，本地已准备、服务器未发布）：新增 directory-worker，复用 API 镜像，没有新增 registry／账号／凭据卷。发布清单 compatibility.directory_worker=true 才启动；恢复旧 API 时不启动它。迁移 d157a0010001 含新 pool 流水线阶段，旧代码不能处理，不声明跨迁移自动回滚。发布前按既有流程由管理员同步固定 gateway 与生产 Compose，并确认目标源码已本地验收；当前未执行服务器升级。

2026-10-17：用户明确授权发布。固定 gateway／生产 Compose 已同步，[Actions 38929226284](https://github.com/yuanyuexiang/Beacon/actions/runs/38929226284) 成功发布 `405c68bc6673d100a7caaae7b752d22b1df00c30`，包含 D54～D59 及 8～128 字符密码要求。迁移到 `d159a0010001`；备份与公网 HTTPS 双端版本验证通过。原管理员密码仍可登录，角色迁移为 admin；用户／策略／门店池接口正常，directory-worker 在线，所有服务容器运行正常，pending 为空。本次不创建真实测试用户、不发送客户消息；Google／AI 匹配质量及来源池真实变化观测仍须另行验证。


## PostgreSQL 远程连接（2026-10-18）

用户授权在生产 Compose 发布 PostgreSQL `5432:5432`。安全组需仅允许可信客户端 IP；数据库连接主机 `18.175.156.130`、端口 `5432`、库名与用户名 `beacon`。密码保留在服务器受控 runtime.env，不写入文档。当前未配置 PostgreSQL 服务端 TLS；加密访问仍推荐 SSH 隧道，不能将公网直连描述为 TLS 加密连接。

修改已通过固定 bootstrap 同步服务器规范，只重建 PostgreSQL，保留数据卷；先完成独立数据库备份并验证 dump。未发布本地其他应用变更，后续 Actions 继续沿用该端口映射。


2026-10-18：用户明确授权发布，开发分支快进合并 main 并推送；[Actions 39115107357](https://github.com/yuanyuexiang/Beacon/actions/runs/39115107357) 检查、五镜像构建、备份、迁移及公网验证全部成功。云端 Web／API 版本均为 `1624dd6a4cf67db09069fbd49e28b430846269d7`，数据库 `d161a0010001`，服务容器正常，pending 为空，5432 映射保留。包含 D60～D67、联系方式核验／准入及结束任务修复；未更改发送开关、未执行客户测试触达。

2026-10-20：用户明确授权发布，开发分支快进合并 main；[Actions 39415861487](https://github.com/yuanyuexiang/Beacon/actions/runs/39415861487) 成功发布 `d14c3d1fb3a71f5686acae7e680bb9c31d12f926`。515 项后端测试、前端、provider、部署配置检查及五镜像构建全部通过。数据库迁移到 `d170a0010001`，数据库／资产／Gmail／Meta／Maps 数据卷备份齐全；公网 Web／API SHA 一致，9 个业务容器运行正常，pending 为空。DeepSeek 已配置，新 AI 触达路由存在；未调用真实模型或发送客户消息。首次使用需在设置中填写真实服务介绍。验证产物保存在受控 `data/devops/release-20261020-verification.json`。

2026-10-22：用户确认本地测试发送成功并授权发布。[Actions 39742889480](https://github.com/yuanyuexiang/Beacon/actions/runs/39742889480) 成功发布 `8df200acbbaf39a4fa47be9ef99755fc40d697cf`，包含 Gmail Web OAuth、测试邮件预览确认和错误诊断。修复测试回调 mypy 错误后全部检查及五镜像构建通过。公网 Web/API SHA 一致，数据库仍为 `d170a0010001`，9 个业务容器正常、备份完整、pending 为空。云端保留原 Desktop 凭据但未连接，未导入本机 Token；需在设置页配置云端 Web 客户端，回调 `https://beacon.ai-onestep.com/api/gmail/oauth/callback`。发送与批量队列保持暂停，未发送邮件。验证记录位于受控 `data/devops/release-20261022-verification.json`。
