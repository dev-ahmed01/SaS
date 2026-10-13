import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../lib/admin-backend";
const headersOut={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Content-Type":"application/json"};
async function handle(request:NextRequest,context:{params:Promise<{action:string}>}){
  const {action}=await context.params;
  const overview=action==="overview"&&request.method==="GET";
  const refresh=action==="refresh-statuses"&&request.method==="POST";
  if(!overview&&!refresh)return NextResponse.json({detail:"Not found"},{status:404,headers:headersOut});
  const backend=backendOrigin();
  if(!backend)return NextResponse.json({detail:"API not configured"},{status:503,headers:headersOut});
  if(refresh){
    const host=request.headers.get("host"),origin=request.headers.get("origin");
    try{
      const parsed=new URL(origin??"");
      if(!host||parsed.host!==host||!["https:","http:"].includes(parsed.protocol)||
         (process.env.APP_PUBLIC_ORIGIN&&parsed.origin!==process.env.APP_PUBLIC_ORIGIN))
        throw Error("Origin mismatch");
    }catch{
      return NextResponse.json({detail:"Origin verification failed"},{status:403,headers:headersOut});
    }
  }
  const query=new URLSearchParams();
  if(overview)for(const [key,value] of request.nextUrl.searchParams){
    if(!["month","limit","offset"].includes(key)||value.length>50||query.has(key))
      return NextResponse.json({detail:"Invalid query"},{status:400,headers:headersOut});
    query.set(key,value);
  }
  const incoming=new Headers();
  const token=request.cookies.get("sas_session")?.value;
  if(token)incoming.set("Cookie","sas_session="+encodeURIComponent(token));
  if(refresh){
    const csrf=request.headers.get("X-CSRF-Token");
    if(csrf&&csrf.length<=128)incoming.set("X-CSRF-Token",csrf);
  }
  try{
    const upstream=await fetch(
      backend+"/v1/accounting/"+action+(query.toString()?"?"+query.toString():""),{
        method:request.method,headers:incoming,cache:"no-store",
        redirect:"manual",signal:AbortSignal.timeout(10000),
      }
    );
    return new NextResponse(await upstream.text(),{status:upstream.status,headers:headersOut});
  }catch{
    return NextResponse.json({detail:"Service temporarily unavailable"},{status:503,headers:headersOut});
  }
}
export const GET=handle;
export const POST=handle;
