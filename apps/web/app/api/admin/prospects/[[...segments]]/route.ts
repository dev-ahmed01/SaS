import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../lib/admin-backend";

/**
 * Explicit, same-origin backend-for-frontend for Admin Prospects.
 * No user-controlled upstream host or unrestricted API forwarding.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const allowedQuery = new Set(["status", "crm_stage", "q", "limit", "offset", "include_archived"]);
const responseHeaders = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Content-Type": "application/json",
};

function resolveRoute(segments: string[], method: string): string | null {
  if (segments.length === 0 && ["GET", "POST"].includes(method)) return "";
  if (segments.length === 1 && segments[0] === "bulk" && method === "POST") {
    return "/bulk";
  }
  if (segments.length === 2 && UUID.test(segments[0]) &&
      segments[1] === "activity" && method === "GET") {
    return "/" + segments[0] + "/activity";
  }
  if (segments.length === 3 && UUID.test(segments[0]) &&
      segments[1] === "otp" &&
      (segments[2] === "status" && method === "GET" ||
       ["request", "verify", "activate"].includes(segments[2]) && method === "POST")) {
    return "/" + segments[0] + "/otp/" + segments[2];
  }
  if (segments.length === 1 && UUID.test(segments[0]) &&
      ["GET", "PATCH", "DELETE"].includes(method)) return "/" + segments[0];
  if (segments.length === 2 && UUID.test(segments[0]) &&
      segments[1] === "followups" && ["GET", "POST"].includes(method)) {
    return "/" + segments[0] + "/followups";
  }
  if (segments.length === 2 && UUID.test(segments[0]) &&
      segments[1] === "stage" && method === "POST") {
    return "/" + segments[0] + "/stage";
  }
  if (segments.length === 2 && UUID.test(segments[0]) &&
      segments[1] === "restore" && method === "POST") {
    return "/" + segments[0] + "/restore";
  }
  if (segments.length === 2 && UUID.test(segments[0]) &&
      segments[1] === "upi-ids" && method === "POST") {
    return "/" + segments[0] + "/upi-ids";
  }
  if (segments.length === 3 && UUID.test(segments[0]) &&
      segments[1] === "upi-ids" && UUID.test(segments[2]) && method === "DELETE") {
    return "/" + segments[0] + "/upi-ids/" + segments[2];
  }
  return null;
}

async function handle(
  request: NextRequest,
  context: { params: Promise<{ segments?: string[] }> },
) {
  const { segments = [] } = await context.params;
  const path = resolveRoute(segments, request.method);
  if (path === null) {
    return NextResponse.json({detail: "Not found"}, {status: 404, headers: responseHeaders});
  }
  const upstream = backendOrigin();
  if (!upstream) {
    return NextResponse.json({detail: "API not configured"}, {status: 503, headers: responseHeaders});
  }
  const write = request.method !== "GET";
  if (write) {
    const origin = request.headers.get("origin");
    const host = request.headers.get("host");
    const approved = process.env.APP_PUBLIC_ORIGIN;
    try {
      const submitted = new URL(origin ?? "");
      if (!host || submitted.host !== host ||
          !["http:", "https:"].includes(submitted.protocol) ||
          (approved && submitted.origin !== approved)) {
        throw Error("untrusted origin");
      }
    } catch {
      return NextResponse.json(
        {detail: "Origin verification failed"}, {status: 403, headers: responseHeaders}
      );
    }
  }
  const query = new URLSearchParams();
  if (!segments.length && request.method === "GET") {
    for (const [key, value] of request.nextUrl.searchParams) {
      if (!allowedQuery.has(key) || value.length > 150 || query.has(key)) {
        return NextResponse.json(
          {detail: "Unsupported query"}, {status: 400, headers: responseHeaders}
        );
      }
      query.set(key, value);
    }
  }
  const headers = new Headers();
  const session = request.cookies.get("sas_session")?.value;
  if (session) headers.set("cookie", "sas_session=" + encodeURIComponent(session));
  const csrf = request.headers.get("x-csrf-token");
  if (csrf && csrf.length <= 128) headers.set("x-csrf-token", csrf);
  const version = request.headers.get("if-match");
  if (version && /^\d{1,12}$/.test(version)) headers.set("if-match", version);

  let body: string | undefined;
  if (write) {
    const size = Number(request.headers.get("content-length") ?? 0);
    const maxBody = path === "/bulk" ? 65536 : 16384;
    if (size > maxBody) {
      return NextResponse.json({detail: "Body too large"}, {status: 413, headers: responseHeaders});
    }
    if (request.method === "POST" || request.method === "PATCH") {
      const type = request.headers.get("content-type");
      if (type && !type.startsWith("application/json")) {
        return NextResponse.json({detail: "JSON required"}, {status: 415, headers: responseHeaders});
      }
    }
    body = await request.text();
    if (body.length > maxBody) {
      return NextResponse.json({detail: "Body too large"}, {status: 413, headers: responseHeaders});
    }
    if (body) headers.set("content-type", "application/json");
  }
  try {
    const suffix = query.toString();
    const result = await fetch(upstream + "/v1/prospects" + path + (suffix ? "?" + suffix : ""), {
      method: request.method,
      body: body || undefined,
      headers,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(result.status === 204 ? null : await result.text(), {
      status: result.status,
      headers: result.status === 204
        ? {"Cache-Control": "no-store"}
        : responseHeaders,
    });
  } catch {
    return NextResponse.json(
      {detail: "Service temporarily unavailable"}, {status: 503, headers: responseHeaders}
    );
  }
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
