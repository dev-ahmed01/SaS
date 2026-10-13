import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../lib/admin-backend";

const responseHeaders = {
  "Cache-Control": "private, no-store",
  "Content-Type": "application/json",
  "X-Content-Type-Options": "nosniff",
};

export async function GET(request: NextRequest) {
  if (request.nextUrl.searchParams.size !== 0) {
    return NextResponse.json(
      {detail: "Unsupported query"}, {status: 400, headers: responseHeaders},
    );
  }
  const origin = backendOrigin();
  if (!origin) {
    return NextResponse.json(
      {detail: "API is not configured"}, {status: 503, headers: responseHeaders},
    );
  }
  const session = request.cookies.get("sas_session")?.value;
  const headers = new Headers();
  if (session) headers.set("cookie", "sas_session=" + encodeURIComponent(session));
  try {
    const response = await fetch(origin + "/v1/dashboard/overview", {
      method: "GET", headers, cache: "no-store", redirect: "manual",
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await response.text(), {
      status: response.status, headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      {detail: "Dashboard temporarily unavailable"},
      {status: 503, headers: responseHeaders},
    );
  }
}
