export function nextSendIssue(issues: string[]): {title:string;action:"settings"|"contact"|"basis"|"message"|"ownership"|"none"} | undefined {
  if (!issues.length) return;
  if (issues.some(x => /拒收|抑制/.test(x))) return {title:"该客户已停止接收联系，不能发送",action:"none"};
  if (issues.some(x => /Gmail|发件邮箱/.test(x))) return {title:issues.find(x => /Gmail|发件邮箱/.test(x))!,action:"settings"};
  if (issues.some(x => /尚未选择联系方式|缺少有效邮箱/.test(x))) return {title:"请选择一个有效的收件人",action:"contact"};
  if (issues.some(x => /属于目标门店|归属证据/.test(x))) return {title:"尚未确认这个联系方式属于该门店，请补查来源或人工核对",action:"ownership"};
  if (issues.some(x => /无效|不一致|变化|更新版本/.test(x))) return {title:"信息已变化，请核对最新联系人和消息",action:"none"};
  if (issues.some(x => /准入|依据|证据|订户|职务|邮箱|同意|TPS|CTPS/.test(x))) return {title:"暂时无法确认本次联系依据，请补充确认",action:"basis"};
  if (issues.some(x => /消息|文案|主题/.test(x))) return {title:"请补齐主题和消息内容",action:"message"};
  return {title:issues[0],action:"none"};
}
