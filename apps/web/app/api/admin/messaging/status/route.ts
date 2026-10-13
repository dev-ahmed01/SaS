import {NextRequest,NextResponse} from "next/server";
import {backendOrigin} from "../../../../../lib/admin-backend";

export async function GET(request:NextRequest){
  const headers=new Headers();
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  const backend=backendOrigin();
  const output={"Cache-Control":"no-store","Content-Type":"application/json",
    "X-Content-Type-Options":"nosniff"};
  if(!backend)return NextResponse.json({detail:"API unavailable"},
    {status:503,headers:output});
  try{
    const result=await fetch(backend+"/v1/messaging/status",{
      headers,method:"GET",cache:"no-store",redirect:"manual",
      signal:AbortSignal.timeout(10000),
    });
    return new NextResponse(await result.text(),
      {status:result.status,headers:output});
  }catch{
    return NextResponse.json({detail:"Status unavailable"},
      {status:503,headers:output});
  }
}
