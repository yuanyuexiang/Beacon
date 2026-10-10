# Places API 连通性探测（2026-10-10）

## 范围与状态

用户授权使用本机专用 Key 开始小样本测试。仅尝试 Text Search (New) 的最小 ID 字段请求；未接入正式线索库，未取得或保存 Google 照片，未调用模型，未触达餐厅。

状态：连通性未通过；10 家菜单照片与价格覆盖率测试尚未执行完成。不能判断密钥、结算、API 启用或 IP 限制是否正确。

## 已观察结果

- 系统代理及 HTTP_PROXY/HTTPS_PROXY 指向本机 127.0.0.1:7890。
- Python urllib 和 httpx 经当前代理访问 places.googleapis.com，TLS 阶段报 EOF / UNEXPECTED_EOF_WHILE_READING，未取得 API HTTP 响应。
- 不携带 Key 的 curl 请求：代理返回 `200 Connection established`，后续 SSL 握手超时。这表明此次故障出现在 API 鉴权之前，而非已收到 Google 的密钥拒绝响应。
- 尝试不读取环境代理的直连，未及时取得响应；停止等待。不能据此确认直连可用。
- 未取得计费事件信息，实际费用须在 Google Cloud 结算中确认，不能把无响应等同于零计费。

## 后续

先恢复本机到 places.googleapis.com 的 HTTPS 连通性；若更换网络出口，核对 Key 的 IP 限制。连通后先执行一次 ID 搜索，再执行详情请求；通过后才扩大到最多 10 家。保持最小字段掩码、限制照片请求数，不保存原始响应或照片引用，不进入模型分析流程。

官方参考：[Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)、[Place Photos (New)](https://developers.google.com/maps/documentation/places/web-service/place-photos)。
