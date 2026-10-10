export default function TermsPage() {
  return <main style={{ maxWidth: 760, margin: "40px auto", padding: 24, lineHeight: 1.8 }}>
    <h1>工作台使用说明</h1>
    <p>本工作台用于餐厅线索研究、菜单证据审核和人工联系记录。操作者应核对门店归属、素材来源和渠道准入；消费价格参考不能代表采购预算。</p>
    <h2>Google Maps 内容</h2>
    <p>Google 查询由操作者按需发起。使用 Google Maps 功能及内容须遵守 <a href="https://maps.google.com/help/terms_maps/" target="_blank" rel="noreferrer">Google Maps / Google Earth 附加服务条款</a>。</p>
    <p>工作台仅保存人工确认的地点 ID 和关联审核记录。Google 返回的名称、地址、价格信息与照片用于当前页面实时查看，不提供这些内容的批量导出、菜单转录或样稿生成。</p>
    <p>照片可能属于其他分店、不是菜单或已经过时，应打开 Google Maps 核对原始内容。照片拍摄质量不能直接证明菜单制作质量。</p>
    <p>更多信息见 <a href="/privacy">隐私说明</a>。</p>
  </main>;
}
