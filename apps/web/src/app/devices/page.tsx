"use client";
import { Alert } from "antd";
import MobileSettings from "@/components/MobileChannel";
import { HeroBand } from "@/components/ui";
import { useOperator } from "@/lib/auth";

export default function DevicesPage() {
  const { me } = useOperator();
  if (!me || me.must_change_password) return null;
  if (me.role === "viewer") return <Alert type="info" showIcon message="只读账号不能绑定或执行手机任务。" />;
  return <>
    <HeroBand kicker="MY DEVICES" title="我的手机" subtitle="绑定自己的手机，接收已确认的任务并回填处理结果。这里只管理当前登录账号的设备。" />
    <MobileSettings />
  </>;
}
