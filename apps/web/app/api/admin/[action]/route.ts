import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../lib/admin-backend";

type Action = "login" | "logout" | "session" | "settings";
const allowed: Record<Action, { method: string; path: string }> = {
  login: {method: "POST", path: "/v1/auth/login"},
  logout: {method: "POST", path: "/v1/auth/logout"},
  session: {method: "GET", path: "/v1/auth/session"},
  settings: {method: "GET,PATCH", path: "/v1/settings"},
};
const noStore = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };

async function forward(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;
  if (!(action in allowed)) return NextResponse.json({detail:"Not found"}, {status:404,headers:noStore});
  const route = allowed[action as Action];
  if (!route.method.split(",").includes(request.method)) {
    return NextResponse.json({detail:"Method not allowed"}, {status:405,headers:noStore});
  }
  const backend = backendOrigin();
  if (!backend) return NextResponse.json({detail:"Application API is not configured"}, {status:503,headers:noStore});
  const write = request.method !== "GET";
  if (write) {
    // Reject cross-origin requests before forwarding session cookies or issuing login cookies.
    // Browser JS automatically sets the Origin header for JSON mutations.
    const origin = request.headers.get("origin");
    if (!origin || origin !== request.nextUrl.origin) {
      return NextResponse.json({detail:"Origin verification failed"}, {status:403,headers:noStore});
    }
    const contentType = request.headers.get("content-type") ?? "";
    if (request.method === "PATCH" || action === "login") {
      if (!contentType.startsWith("application/json")) {
        return NextResponse.json({detail:"JSON request required"}, {status:415,headers:noStore});
      }
    }
  }
  const cookie = request.cookies.get("sas_session")?.value;
  const headers = new Headers();
  if (cookie) headers.set("cookie", "sas_session=" + encodeURIComponent(cookie));
  const csrf = request.headers.get("x-csrf-token");
  if (csrf && csrf.length < 200) headers.set("x-csrf-token", csrf);
  let body: string | undefined;
  if (write) {
    const length = Number(request.headers.get("content-length") ?? 0);
    if (length > 16384) return NextResponse.json({detail:"Request too large"}, {status:413,headers:noStore});
    body = await request.text();
    if (body.length > 16384) return NextResponse.json({detail:"Request too large"}, {status:413,headers:noStore});
    if (body) headers.set("content-type", "application/json");
  }
  try {
    const response = await fetch(backend + route.path, {
      method: request.method,
      headers,
      body: body || undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(10000),
    });
    const proxyResponse = new NextResponse(await response.text(), {
      status: response.status,
      headers: { ...noStore, "Content-Type": "application/json" },
    });
    const setCookie = response.headers.get("set-cookie");
    if (setCookie) proxyResponse.headers.append("Set-Cookie", setCookie);
    return proxyResponse;
  } catch {
    return NextResponse.json({detail:"The service is temporarily unavailable"}, {status:503,headers:noStore});
  }
}
export const GET = forward;
export const POST = forward;
export const PATCH = forward;
