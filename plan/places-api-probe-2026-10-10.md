# Places API 连通性探测（2026-10-10）

## 范围与状态

用户授权使用本机专用 Key 开始小样本测试。仅尝试 Text Search (New) 的最小 ID 字段请求；未接入正式线索库，未取得或保存 Google 照片，未调用模型，未触达餐厅。

状态：后续通过 SOCKS5 取得最小 ID 查询和部分价格/照片引用查询响应，确认当前 Key 可调用 Places API (New)。10 家已尝试，4 家成功、6 家网络失败；菜单照片内容覆盖率尚未验证。

## SOCKS5 路径与小样本结果

用户要求再次比较浏览器与命令行代理访问。当前显式 HTTP 代理可访问 Google 首页，但访问 Places 域名仍 TLS 超时；显式 `socks5h://127.0.0.1:7890` 则曾取得 Places 根路径 HTTP 404，随后最小 ID 搜索成功。SOCKS5 连接也有间歇性超时，并非已稳定解决。

从已有研究记录选 10 个门店查询，非随机样本，搜索每次最多返回一个候选，最多尝试两次，不按搜索排名自动确认门店匹配。查询最小必要名称、地址、价格档位、价格区间和照片引用；没有把照片媒体下载到证据目录，没有模型处理，没有写入正式线索库。

| 指标 | 结果 |
|---|---:|
| 计划查询 | 10 家 |
| 搜索调用尝试 | 18 次（含网络失败重试） |
| 成功取得响应与候选 | 4/10 |
| 网络失败、无商家结果可判定 | 6/10 |
| 成功响应中有价格档位 | 4/4 |
| 成功响应中有价格区间 | 4/4 |
| 成功响应中有照片引用 | 4/4，各 10 条 |
| 已核对为菜单图片 | 尚未检查，不能报告覆盖率 |

成功查询输入为 Zen Mondo、Saperavi、Fare、Pandas Kitchen；失败查询输入为 Sushi Wa、Brags and Brams、Hanoi Pho、Aetos、Sutton and Sons、Kuhaku（均加 Islington London UK 地域词）。这些是测试输入，不是长期保存 Google 返回的商家名录。原始响应、照片引用和返回地址未保存到文件。成功响应中存在餐厅名称变化等候选核对需求，不能把返回一个候选等同于已匹配正确。

费用尚未从 Google Cloud 结算核对；成功批次包含 Text Search Enterprise 字段，不应沿用 IDs Only 的计费档位。结果仅证明字段在部分样本中可取得，不能外推总体覆盖率或精确客单价。

## 已观察结果

- 系统代理及 HTTP_PROXY/HTTPS_PROXY 指向本机 127.0.0.1:7890。
- Python urllib 和 httpx 经当前代理访问 places.googleapis.com，TLS 阶段报 EOF / UNEXPECTED_EOF_WHILE_READING，未取得 API HTTP 响应。
- 不携带 Key 的 curl 请求：代理返回 `200 Connection established`，后续 SSL 握手超时。这表明此次故障出现在 API 鉴权之前，而非已收到 Google 的密钥拒绝响应。
- 尝试不读取环境代理的直连，未及时取得响应；停止等待。不能据此确认直连可用。
- 未取得计费事件信息，实际费用须在 Google Cloud 结算中确认，不能把无响应等同于零计费。

## 后续

系统重启后再次测试：命令行环境中已无 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY，但 `scutil --proxy` 仍显示系统 HTTP/HTTPS/SOCKS 代理启用并指向 127.0.0.1:7890。curl 无代理 IPv4 访问 Google 首页和 Places 域名均连接超时；显式使用系统代理提交最小 ID 搜索仍 TLS 握手超时。未取得 API 响应，小样本测试仍未完成。

用户随后明确要求不使用本机代理：使用 `trust_env=False` 禁用环境代理后仍未连接成功；DNS 能正常返回 Google 的 IPv4/IPv6 地址。补充使用 `curl --noproxy '*' -4` 强制无代理 IPv4 连接，5 秒连接超时，未收到 HTTP 响应。未修改系统代理设置；仍不能验证密钥或取得餐厅数据。

用户要求当日重试：环境代理路径仍报 `UNEXPECTED_EOF_WHILE_READING`；显式指定 `http://127.0.0.1:7890` 的代理路径在 15 秒 TLS 握手超时。两次均未取得 API HTTP 响应，仍不能判断 Key 与权限状态，小样本测试尚未完成。

先恢复本机到 places.googleapis.com 的 HTTPS 连通性；若更换网络出口，核对 Key 的 IP 限制。连通后先执行一次 ID 搜索，再执行详情请求；通过后才扩大到最多 10 家。保持最小字段掩码、限制照片请求数，不保存原始响应或照片引用，不进入模型分析流程。

官方参考：[Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)、[Place Photos (New)](https://developers.google.com/maps/documentation/places/web-service/place-photos)。

## D41 适配器复测

实际适配器再次取得一家已知餐厅详情：价格区间、10 条照片引用、10 条作者署名和原图链接；首张 JPEG 在内存加载成功（349,814 字节），未落盘、未送模型。尚未确认该图片为菜单。早期失败记录保留作为网络诊断历史，不能视为当前 Key 不可用。容器连通性另见实施验收记录。

容器复测：配置已读取，API 健康；宿主机代理 TCP 连接失败，两轮详情调用均失败，容器联网验收尚未通过。没有关闭系统代理或打开公网监听。
