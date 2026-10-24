"use client";
import { createContext, useContext, useEffect } from "react";
export const SettingsState = createContext<{ dirty: (key: string, value: boolean) => void; status: (key: string, value: string) => void }>({ dirty: () => {}, status: () => {} });
export function useSettingsDraft(key: string, changed: boolean) {
  const { dirty } = useContext(SettingsState);
  useEffect(() => { dirty(key, changed); return () => dirty(key, false); }, [key, changed, dirty]);
}
export function useSettingsStatus(key: string, value: string) {
  const { status } = useContext(SettingsState);
  useEffect(() => { status(key, value); }, [key, value, status]);
}
