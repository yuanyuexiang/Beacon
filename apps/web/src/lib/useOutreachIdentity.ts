"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Load defaults once, without replacing anything the user has already edited. */
export function useOutreachIdentity() {
  const [sender, updateSender] = useState("");
  const [optOut, updateOptOut] = useState("Please let me know if you would prefer not to hear from us again.");
  const [identityError, setIdentityError] = useState<string>();
  const edited = useRef({ sender: false, optOut: false });
  useEffect(() => {
    let active = true;
    void api<{ sender_identity: string; opt_out_text: string; configuration_error?: string }>("/api/outreach-identity").then(data => {
      if (!active) return;
      setIdentityError(data.configuration_error);
      if (!edited.current.sender) updateSender(data.sender_identity || "");
      if (!edited.current.optOut && data.opt_out_text) updateOptOut(data.opt_out_text);
    }).catch(() => { /* Manual entry remains available if defaults cannot be read. */ });
    return () => { active = false; };
  }, []);
  return { sender, optOut, identityError, setSender: (value: string) => { edited.current.sender = true; updateSender(value); }, setOptOut: (value: string) => { edited.current.optOut = true; updateOptOut(value); } };
}
