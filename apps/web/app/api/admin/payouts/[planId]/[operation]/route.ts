import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../../lib/admin-backend";

const meta={"Cache-Control":"no-store","Content-Type":"application/json",
  "X-Content-Type-Options":"nosniff"};
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export async function POST(request:NextRequest,context:{
  params:Promise<{planId:string;operation:string}>
}){
  const {planId,operation}=await context.params;
  if(!UUID.test(planId)||!["status","disbursements"].includes(operation))
    return NextResponse.json({detail:"Not found"},{status:404,headers:meta});
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
  const length=Number(request.headers.get("content-length")??0);
  if(length>8192)return NextResponse.json({detail:"Too large"},{status:413,headers:meta});
  const body=await request.text();
  if(body.length>8192)return NextResponse.json({detail:"Too large"},{status:413,headers:meta});
  const backend=backendOrigin();
  if(!backend)return NextResponse.json({detail:"API unavailable"},{status:503,headers:meta});
  const headers=new Headers({"Content-Type":"application/json"});
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  const csrf=request.headers.get("x-csrf-token");
  if(csrf&&csrf.length<=128)headers.set("x-csrf-token",csrf);
  try{
    const result=await fetch(backend+"/v1/payouts/"+planId+"/"+operation,{
      method:"POST",headers,body,cache:"no-store",redirect:"manual",
      signal:AbortSignal.timeout(10000),
    });
    return new NextResponse(await result.text(),{status:result.status,headers:meta});
  }catch{
    return NextResponse.json({detail:"Service unavailable"},{status:503,headers:meta});
  }
}
