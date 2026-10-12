import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export function GET() {
  return NextResponse.json({ status: "ok", release: process.env.BEACON_RELEASE_SHA || "development" }, { headers: { "Cache-Control": "no-store" } });
}
