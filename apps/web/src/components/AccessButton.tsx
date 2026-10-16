"use client";
import { Button, type ButtonProps } from "antd";
import { useOperator } from "@/lib/auth";

// 界面辅助；实际授权始终由后端复核。明确的查看操作可单独放行。
export default function AccessButton({ readOnlySafe = false, ...props }: ButtonProps & { readOnlySafe?: boolean }) {
  const { me } = useOperator();
  return <Button {...props} disabled={props.disabled || (!readOnlySafe && me?.role !== "admin" && me?.role !== "member")} />;
}
