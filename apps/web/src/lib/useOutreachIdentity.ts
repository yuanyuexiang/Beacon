"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type SavedIdentity = { sender_identity: string; opt_out_text: string; configuration_error?: string };
export type ResolvedIdentity = { sender: string; optOut: string };

/** Refresh saved defaults before generating; never overwrite explicit local edits. */
export function useOutreachIdentity() {
  const [sender, updateSender] = useState("");
  const [optOut, updateOptOut] = useState("Please let me know if you would prefer not to hear from us again.");
  const [identityError, setIdentityError] = useState<string>();
  const edited = useRef({ sender: false, optOut: false });
  const current = useRef<ResolvedIdentity>({sender:"",optOut:"Please let me know if you would prefer not to hear from us again."});
  const mounted = useRef(false);
  const generation = useRef(0);
  const resolve = useCallback(async (): Promise<ResolvedIdentity> => {
    const request = ++generation.current;
    const data = await api<SavedIdentity>("/api/outreach-identity");
    if (data.configuration_error) throw new Error(data.configuration_error);
    const next = {
      sender: edited.current.sender ? current.current.sender : data.sender_identity || "",
      optOut: edited.current.optOut ? current.current.optOut : data.opt_out_text || current.current.optOut,
    };
    if (request !== generation.current) return next;
    current.current = next;
    if (mounted.current) {updateSender(next.sender);updateOptOut(next.optOut);setIdentityError(undefined);}
    return next;
  }, []);
  useEffect(() => {
    mounted.current = true;
    const refresh = () => {void resolve().catch(e => {if(mounted.current) setIdentityError((e as Error).message);});};
    refresh();
    window.addEventListener("focus", refresh);
    return () => {mounted.current = false;window.removeEventListener("focus",refresh);};
  }, [resolve]);
  return { sender, optOut, identityError, resolve, setSender: (value: string) => { edited.current.sender = true; current.current.sender=value; updateSender(value); }, setOptOut: (value: string) => { edited.current.optOut = true; current.current.optOut=value; updateOptOut(value); } };
}
