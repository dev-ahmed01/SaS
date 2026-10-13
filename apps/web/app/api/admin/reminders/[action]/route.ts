import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../lib/admin-backend";

const out = {
  "Cache-Control":"no-store",
  "Content-Type":"application/json",
  "X-Content-Type-Options":"nosniff",
};
type Context = {params:Promise<{action:string}>};

async function handle(request:NextRequest,ctx:Context) {
  const {action}=await ctx.params;
  const isPreview=action==="preview"&&request.method==="GET";
  const isHistory=action==="batches"&&request.method==="GET";
  const isPrepare=action==="prepare"&&request.method==="POST";
  if(!isPreview&&!isHistory&&!isPrepare) {
    return NextResponse.json({detail:"Not found"},{status:404,headers:out});
  }
  if(isPrepare) {
    try {
      const origin=new URL(request.headers.get("origin")??"");
      const host=request.headers.get("host");
      if(!host||origin.host!==host||!["https:","http:"].includes(origin.protocol)||
        (process.env.APP_PUBLIC_ORIGIN&&origin.origin!==process.env.APP_PUBLIC_ORIGIN)) {
        throw Error("Untrusted request");
      }
    }catch{
      return NextResponse.json(
        {detail:"Origin verification failed"},{status:403,headers:out},
      );
    }
    if(!(request.headers.get("content-type")??"").startsWith("application/json")) {
      return NextResponse.json(
        {detail:"JSON body required"},{status:415,headers:out},
      );
    }
  }
  const params=new URLSearchParams();
  const accepted=isPreview?["kind"]:isHistory?["limit","offset"]:[];
  if(!isPrepare)for(const [key,value] of request.nextUrl.searchParams) {
    if(!accepted.includes(key)||params.has(key)||value.length>60) {
      return NextResponse.json(
        {detail:"Unsupported query"},{status:400,headers:out},
      );
    }
    params.set(key,value);
  }
  const backend=backendOrigin();
  if(!backend) {
    return NextResponse.json(
      {detail:"Backend unavailable"},{status:503,headers:out},
    );
  }
  const headers=new Headers();
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  let body:string|undefined;
  if(isPrepare) {
    const length=Number(request.headers.get("content-length")??0);
    if(!Number.isFinite(length)||length>4096) {
      return NextResponse.json(
        {detail:"Request too large"},{status:413,headers:out},
      );
    }
    body=await request.text();
    if(body.length>4096) {
      return NextResponse.json(
        {detail:"Request too large"},{status:413,headers:out},
      );
    }
    headers.set("content-type","application/json");
    const csrf=request.headers.get("x-csrf-token");
    if(csrf&&csrf.length<=128)headers.set("x-csrf-token",csrf);
  }
  try {
    const upstream=await fetch(
      backend+"/v1/reminders/"+action+(params.size?"?"+params.toString():""),{
        method:request.method,headers,body,cache:"no-store",redirect:"manual",
        signal:AbortSignal.timeout(15000),
      },
    );
    return new NextResponse(await upstream.text(),{
      status:upstream.status,headers:out,
    });
  }catch{
    return NextResponse.json(
      {detail:"Service temporarily unavailable"},{status:503,headers:out},
    );
  }
}
export const GET=handle;
export const POST=handle;
