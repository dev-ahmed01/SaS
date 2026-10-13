import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../lib/admin-backend";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const headersOut = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Content-Type": "application/json",
};

function allow(segments: string[], method: string): string | null {
  if (segments.length === 1 && segments[0] === "plans" &&
      ["GET", "POST"].includes(method)) return "/plans";
  if (segments.length === 1 && segments[0] === "payments" &&
      method === "GET") return "/payments";
  if (segments.length === 3 && segments[0] === "plans" &&
      UUID.test(segments[1]) && segments[2] === "status" && method === "POST") {
    return "/plans/" + segments[1] + "/status";
  }
  if (segments.length === 3 && segments[0] === "plans" &&
      UUID.test(segments[1]) && segments[2] === "payments" && method === "POST") {
    return "/plans/" + segments[1] + "/payments";
  }
  return null;
}

async function handle(
  request: NextRequest,
  context: {params: Promise<{segments: string[]}>},
) {
  const {segments} = await context.params;
  const suffix = allow(segments, request.method);
  if (suffix === null) {
    return NextResponse.json({detail:"Not found"}, {status:404, headers:headersOut});
  }
  const url = backendOrigin();
  if (!url) {
    return NextResponse.json({detail:"API unavailable"}, {status:503, headers:headersOut});
  }
  const write = request.method !== "GET";
  if (write) {
    try {
      const origin = new URL(request.headers.get("origin") ?? "");
      const host = request.headers.get("host");
      if (!host || origin.host !== host || !["http:", "https:"].includes(origin.protocol) ||
          (process.env.APP_PUBLIC_ORIGIN && origin.origin !== process.env.APP_PUBLIC_ORIGIN)) {
        throw Error("untrusted origin");
      }
    } catch {
      return NextResponse.json(
        {detail:"Origin verification failed"}, {status:403, headers:headersOut}
      );
    }
    if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
      return NextResponse.json({detail:"JSON required"}, {status:415, headers:headersOut});
    }
  }
  const params = new URLSearchParams();
  if (!write) {
    const allowed = segments[0] === "plans" ?
      new Set(["view","month","limit","offset"]) : new Set(["plan_id","limit","offset"]);
    for (const [key,value] of request.nextUrl.searchParams) {
      if (!allowed.has(key) || params.has(key) || value.length > 64) {
        return NextResponse.json({detail:"Invalid query"}, {status:400, headers:headersOut});
      }
      params.set(key,value);
    }
  }
  const headers = new Headers();
  const session = request.cookies.get("sas_session")?.value;
  if (session) headers.set("cookie", "sas_session=" + encodeURIComponent(session));
  const csrf = request.headers.get("x-csrf-token");
  if (csrf && csrf.length <= 128) headers.set("x-csrf-token", csrf);
  let body: string | undefined;
  if (write) {
    const length = Number(request.headers.get("content-length") ?? 0);
    if (!Number.isFinite(length) || length > 8192) {
      return NextResponse.json({detail:"Body too large"}, {status:413, headers:headersOut});
    }
    body = await request.text();
    if (body.length > 8192) {
      return NextResponse.json({detail:"Body too large"}, {status:413, headers:headersOut});
    }
    headers.set("content-type", "application/json");
  }
  try {
    const upstream = await fetch(
      url + "/v1/payouts" + suffix + (params.size ? "?" + params.toString() : ""),
      {
        method:request.method, headers, body, cache:"no-store",
        redirect:"manual", signal:AbortSignal.timeout(10000),
      }
    );
    return new NextResponse(await upstream.text(), {
      status:upstream.status, headers:headersOut,
    });
  } catch {
    return NextResponse.json(
      {detail:"Service temporarily unavailable"}, {status:503, headers:headersOut}
    );
  }
}

export const GET = handle;
export const POST = handle;
