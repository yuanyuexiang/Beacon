"use client";
import { createContext, useContext } from "react";
export type Operator = { id: string; username: string; display_name: string | null; role: "admin" | "director" | "member" | "viewer"; must_change_password: boolean };
export const AuthContext = createContext<{ me: Operator | null; refresh: () => Promise<void> }>({ me: null, refresh: async () => {} });
export const useOperator = () => useContext(AuthContext);
export const ROLE_LABELS = { admin: "管理员", director: "销售总监", member: "业务成员", viewer: "只读成员" };
