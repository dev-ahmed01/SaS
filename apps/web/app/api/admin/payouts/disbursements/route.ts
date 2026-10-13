import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../lib/admin-backend";
const meta={"Cache-Control":"no-store","Content-Type":"application/json"};
export async function GET(request:NextRequest){
  const params=new URLSearchParams();
  for(const [key,value] of request.nextUrl.searchParams){
    if(!["limit","offset"].includes(key)||params.has(key)||value.length>20)
      return NextResponse.json({detail:"Bad query"},{status:400,headers:meta});
    params.set(key,value);
  }
  const backend=backendOrigin();
  if(!backend)return NextResponse.json({detail:"API unavailable"},{status:503,headers:meta});
  const headers=new Headers();
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  try{
    const result=await fetch(backend+"/v1/payouts/disbursements"+(params.size?"?"+params:""),{
      headers,cache:"no-store",redirect:"manual",signal:AbortSignal.timeout(10000),
    });
    return new NextResponse(await result.text(),{status:result.status,headers:meta});
  }catch{
    return NextResponse.json({detail:"Service unavailable"},{status:503,headers:meta});
  }
}
