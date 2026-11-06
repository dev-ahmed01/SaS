import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../../lib/admin-backend";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const headersOut={
  "Cache-Control":"no-store",
  "X-Content-Type-Options":"nosniff",
  "Content-Type":"application/json",
};

function suffixFor(segments:string[],method:string):string|null{
  if(segments.length===0 && ["GET","POST"].includes(method))return "";
  if(segments.length===1&&segments[0]==="reorder"&&method==="POST")return "/reorder";
  if(segments.length===1&&UUID.test(segments[0])&&method==="PATCH")
    return "/"+segments[0];
  return null;
}

async function handle(
  request:NextRequest,
  context:{params:Promise<{segments?:string[]}>},
){
  const {segments=[]}=await context.params;
  const suffix=suffixFor(segments,request.method);
  if(suffix===null)return NextResponse.json(
    {detail:"Not found"},{status:404,headers:headersOut});
  const origin=backendOrigin();
  if(!origin)return NextResponse.json(
    {detail:"API unavailable"},{status:503,headers:headersOut});
  const write=request.method!=="GET";
  if(write){
    try{
      const submitted=new URL(request.headers.get("origin")??"");
      const host=request.headers.get("host");
      if(!host||submitted.host!==host||!["http:","https:"].includes(submitted.protocol)||
         (process.env.APP_PUBLIC_ORIGIN&&submitted.origin!==process.env.APP_PUBLIC_ORIGIN)){
        throw Error("untrusted origin");
      }
    }catch{
      return NextResponse.json({detail:"Origin verification failed"},
        {status:403,headers:headersOut});
    }
    if(!(request.headers.get("content-type")??"").startsWith("application/json")){
      return NextResponse.json({detail:"JSON required"},{status:415,headers:headersOut});
    }
  }
  const params=new URLSearchParams();
  if(!write){
    const allowed=new Set(["field_key","include_inactive"]);
    for(const [name,value] of request.nextUrl.searchParams){
      if(!allowed.has(name)||params.has(name)||value.length>32)
        return NextResponse.json({detail:"Unsupported query"},
          {status:400,headers:headersOut});
      params.set(name,value);
    }
  }
  const headers=new Headers();
  const cookie=request.cookies.get("sas_session")?.value;
  if(cookie)headers.set("cookie","sas_session="+encodeURIComponent(cookie));
  const csrf=request.headers.get("x-csrf-token");
  if(csrf&&csrf.length<=128)headers.set("x-csrf-token",csrf);
  let body:string|undefined;
  if(write){
    const len=Number(request.headers.get("content-length")??0);
    if(!Number.isFinite(len)||len>8192)
      return NextResponse.json({detail:"Request too large"},{status:413,headers:headersOut});
    body=await request.text();
    if(body.length>8192)
      return NextResponse.json({detail:"Request too large"},{status:413,headers:headersOut});
    headers.set("content-type","application/json");
  }
  try{
    const result=await fetch(origin+"/v1/settings/field-options"+suffix+
      (params.size?"?"+params.toString():""),{
      method:request.method,headers,body,
      cache:"no-store",redirect:"manual",signal:AbortSignal.timeout(10000),
    });
    return new NextResponse(await result.text(),{
      status:result.status,headers:headersOut,
    });
  }catch{
    return NextResponse.json({detail:"Service temporarily unavailable"},
      {status:503,headers:headersOut});
  }
}
export const GET=handle;
export const POST=handle;
export const PATCH=handle;
