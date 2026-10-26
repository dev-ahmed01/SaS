import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../../lib/admin-backend";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const meta = {
  "Cache-Control": "no-store",
  "Content-Type": "application/json",
  "X-Content-Type-Options": "nosniff",
};

export async function POST(
  request: NextRequest,
  context: {params: Promise<{collectionId: string}>},
) {
  const {collectionId} = await context.params;
  if (!UUID.test(collectionId)) {
    return NextResponse.json({detail: "Not found"}, {status: 404, headers: meta});
  }
  try {
    const submitted = new URL(request.headers.get("origin") ?? "");
    const host = request.headers.get("host");
    if (!host || submitted.host !== host ||
      !["http:", "https:"].includes(submitted.protocol) ||
      (process.env.APP_PUBLIC_ORIGIN && submitted.origin !== process.env.APP_PUBLIC_ORIGIN)
    ) {
      throw Error("Untrusted origin");
    }
  } catch {
    return NextResponse.json(
      {detail: "Origin verification failed"}, {status: 403, headers: meta},
    );
  }
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return NextResponse.json({detail: "JSON required"}, {status: 415, headers: meta});
  }
  const length = Number(request.headers.get("content-length") ?? 0);
  if (!Number.isFinite(length) || length > 4096) {
    return NextResponse.json({detail: "Request too large"}, {status: 413, headers: meta});
  }
  const body = await request.text();
  if (body.length > 4096) {
    return NextResponse.json({detail: "Request too large"}, {status: 413, headers: meta});
  }
  const backend = backendOrigin();
  if (!backend) {
    return NextResponse.json({detail: "API unavailable"}, {status: 503, headers: meta});
  }
  const headers = new Headers({"content-type": "application/json"});
  const session = request.cookies.get("sas_session")?.value;
  if (session) headers.set("cookie", "sas_session=" + encodeURIComponent(session));
  const csrf = request.headers.get("x-csrf-token");
  if (csrf && csrf.length <= 128) headers.set("x-csrf-token", csrf);

  try {
    const upstream = await fetch(
      backend + "/v1/collections/" + collectionId + "/resend-confirmation",
      {method: "POST", headers, body, cache: "no-store", redirect: "manual",
        signal: AbortSignal.timeout(10000)},
    );
    return new NextResponse(await upstream.text(), {status: upstream.status, headers: meta});
  } catch {
    return NextResponse.json(
      {detail: "Service temporarily unavailable"}, {status: 503, headers: meta},
    );
  }
}
