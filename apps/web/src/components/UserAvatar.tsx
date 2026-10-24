"use client";
import { Avatar } from "antd";
export function UserAvatar({ user, size = 24 }: { user?: { username: string; display_name?: string | null; avatar_url?: string | null } | null; size?: number }) {
  const name = user?.display_name || user?.username || "?";
  return <Avatar key={user?.avatar_url || user?.username} size={size} src={user?.avatar_url || undefined} alt={`${name}的头像`} style={{ background: "#cf010e", flexShrink: 0 }}>{Array.from(name)[0]?.toUpperCase()}</Avatar>;
}

export function UserIdentity({ username }: { username?: string | null }) {
  if (!username) return <>未分配</>;
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><UserAvatar user={{ username, avatar_url: `/api/avatars/${encodeURIComponent(username)}` }} />{username}</span>;
}
