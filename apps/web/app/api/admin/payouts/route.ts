import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../lib/admin-backend";

const meta = {"Cache-Control":"no-store","Content-Type":"application/json",
  "X-Content-Type-Options":"nosniff"};

async function handle(request:NextRequest){
  const write=request.method==="POST";
  if(write){
    try{
      const origin=new URL(request.headers.get("origin")??"");
      const host=request.headers.get("host");
      if(!host||origin.host!==host||!["http:","https:"].includes(origin.protocol)||
        (process.env.APP_PUBLIC_ORIGIN&&origin.origin!==process.env.APP_PUBLIC_ORIGIN))
        throw Error("Untrusted origin");
    }catch{
      return NextResponse.json({detail:"Origin rejected"},{status:403,headers:meta});
    }
    if(!(request.headers.get("content-type")??"").startsWith("application/json"))
      return NextResponse.json({detail:"JSON required"},{status:415,headers:meta});
  }
  const allowed=["limit","offset","active_only"];
  const params=new URLSearchParams();
  if(!write)for(const [key,value] of request.nextUrl.searchParams){
    if(!allowed.includes(key)||params.has(key)||value.length>20)
      return NextResponse.json({detail:"Bad query"},{status:400,headers:meta});
    params.set(key,value);
  }
  const backend=backendOrigin();
  if(!backend)return NextResponse.json({detail:"API unavailable"},{status:503,headers:meta});
  const headers=new Headers();
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  const csrf=request.headers.get("x-csrf-token");
  if(csrf&&csrf.length<=128)headers.set("x-csrf-token",csrf);
  let body:string|undefined;
  if(write){
    const length=Number(request.headers.get("content-length")??0);
    if(length>8192)return NextResponse.json({detail:"Too large"},{status:413,headers:meta});
    body=await request.text();
    if(body.length>8192)return NextResponse.json({detail:"Too large"},{status:413,headers:meta});
    headers.set("content-type","application/json");
  }
  try{
    const result=await fetch(backend+"/v1/payouts"+(params.size?"?"+params:""),{
      method:request.method,headers,body,cache:"no-store",redirect:"manual",
      signal:AbortSignal.timeout(10000),
    });
    return new NextResponse(await result.text(),{status:result.status,headers:meta});
  }catch{
    return NextResponse.json({detail:"Service unavailable"},{status:503,headers:meta});
  }
}
export const GET=handle;
export const POST=handle;
