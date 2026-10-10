export default function PrivacyPage() {
  return <main style={{ maxWidth: 760, margin: "40px auto", padding: 24, lineHeight: 1.8 }}>
    <h1>工作台隐私说明</h1>
    <p>工作台保存操作者账号、门店资料、人工审核、菜单证据及联系记录。访问业务数据需要登录；真实凭证与受控资料不进入代码仓库。</p>
    <h2>Google 查询</h2>
    <p>操作者点击搜索时，工作台向 Google 发送店名、地址或邮编等搜索词；点击查看详情或照片时发送地点 ID 或照片引用。Google 及网络代理可能获取请求的出口 IP 等网络信息。请勿在搜索框输入私人联系方式、密码或其他无关敏感信息。</p>
    <p>Google 返回信息仅在当前页面展示。工作台不将这些响应、照片和价格写入数据库、证据文件或备份，也不发送给模型服务。关联记录仅保存地点 ID、审核人、时间和版本；调用审计只记录操作者、线索、时间和计费档位，不记录密钥、查询响应或照片引用。</p>
    <p>点击 Google Maps 链接或加载作者头像时，浏览器会连接 Google 服务，其数据处理遵循 <a href="https://policies.google.com/privacy" target="_blank" rel="noreferrer">Google 隐私政策</a>。</p>
    <p>需要更正门店关联时可在详情页解除并重新核对；账号、受控数据和保留期问题请联系工作台管理员。</p>
    <p><a href="/terms">工作台使用说明</a></p>
  </main>;
}
