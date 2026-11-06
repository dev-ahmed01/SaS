import {NextRequest,NextResponse} from "next/server";
import {backendOrigin} from "../../../../../lib/admin-backend";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const headersOut={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};

export async function PATCH(request:NextRequest,context:{
  params:Promise<{id:string}>
}){
  const {id}=await context.params;
  if(!UUID.test(id))return NextResponse.json({detail:"Not found"},{status:404,headers:headersOut});
  const backend=backendOrigin();
  if(!backend)return NextResponse.json({detail:"API unavailable"},{status:503,headers:headersOut});
  try{
    const origin=new URL(request.headers.get("origin")??"");
    const host=request.headers.get("host");
    if(!host||origin.host!==host||
      !["http:","https:"].includes(origin.protocol)||
      (process.env.APP_PUBLIC_ORIGIN&&origin.origin!==process.env.APP_PUBLIC_ORIGIN)){
      throw Error("untrusted");
    }
  }catch{
    return NextResponse.json({detail:"Invalid origin"},{status:403,headers:headersOut});
  }
  if(!(request.headers.get("content-type")??"").startsWith("application/json")){
    return NextResponse.json({detail:"JSON required"},{status:415,headers:headersOut});
  }
  const body=await request.text();
  if(body.length>4096)return NextResponse.json({detail:"Too large"},{status:413,headers:headersOut});
  const headers=new Headers({"content-type":"application/json"});
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  const csrf=request.headers.get("x-csrf-token");
  if(csrf&&csrf.length<=128)headers.set("x-csrf-token",csrf);
  try{
    const res=await fetch(backend+"/v1/auth/users/"+id,{
      method:"PATCH",headers,body,redirect:"manual",cache:"no-store",
      signal:AbortSignal.timeout(10000),
    });
    return new NextResponse(await res.text(),{status:res.status,headers:{
      ...headersOut,"Content-Type":"application/json",
    }});
  }catch{
    return NextResponse.json({detail:"Service unavailable"},{status:503,headers:headersOut});
  }
}
