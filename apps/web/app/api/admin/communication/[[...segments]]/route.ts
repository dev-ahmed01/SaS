import { NextRequest, NextResponse } from "next/server";
import { backendOrigin } from "../../../../../lib/admin-backend";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const output={
  "Cache-Control":"no-store",
  "Content-Type":"application/json",
  "X-Content-Type-Options":"nosniff",
};

function allowed(parts:string[],method:string):string|null{
  const [name,id,action]=parts;
  if(parts.length===1&&name==="clock"&&method==="GET")return "/clock";
  if(parts.length===2&&name==="provider"&&id==="saasyto"&&method==="GET")
    return "/provider/saasyto";
  if(parts.length===1&&name==="audience"&&method==="GET")return "/audience";
  if(parts.length===1&&name==="consent-events"&&["GET","POST"].includes(method))return "/consent-events";
  if(parts.length===1&&name==="active-consent-review"&&
    ["GET","POST"].includes(method))return "/active-consent-review";
  if(parts.length===1&&["templates","campaigns","rules"].includes(name)&&
    ["GET","POST"].includes(method))return "/"+name;
  if(parts.length===2&&name==="campaigns"&&id==="results"&&method==="GET")
    return "/campaigns/results";
  if(parts.length===3&&name==="campaigns"&&UUID.test(id)&&
    action==="results"&&method==="GET")
    return "/campaigns/"+id+"/results";
  if(parts.length===2&&name==="templates"&&UUID.test(id)&&
    ["PATCH","DELETE"].includes(method))return "/templates/"+id;
  if(parts.length===2&&name==="rules"&&UUID.test(id)&&method==="DELETE")
    return "/rules/"+id;
  if(parts.length===3&&name==="campaigns"&&UUID.test(id)&&
    action==="saasyto"&&["GET","POST"].includes(method))
    return "/campaigns/"+id+"/saasyto";
  if(parts.length===4&&name==="campaigns"&&UUID.test(id)&&
    action==="saasyto"&&parts[3]==="send-now"&&method==="POST")
    return "/campaigns/"+id+"/saasyto/send-now";
  if(parts.length===4&&name==="campaigns"&&UUID.test(id)&&
    action==="saasyto"&&parts[3]==="cancel"&&method==="POST")
    return "/campaigns/"+id+"/saasyto/cancel";
  if(parts.length===3&&name==="campaigns"&&UUID.test(id)&&
    action==="cancel"&&method==="POST")return "/campaigns/"+id+"/cancel";
  if(parts.length===3&&name==="campaigns"&&UUID.test(id)&&
    action==="preparations"&&["GET","POST"].includes(method))
    return "/campaigns/"+id+"/preparations";
  return null;
}

async function handle(
  request:NextRequest,context:{params:Promise<{segments?:string[]}>},
){
  const {segments=[]}=await context.params;
  const path=allowed(segments,request.method);
  if(!path)return NextResponse.json({detail:"Unknown operation"},{
    status:404,headers:output,
  });
  const write=request.method!=="GET";
  if(write){
    try{
      const origin=new URL(request.headers.get("origin")??"");
      const host=request.headers.get("host");
      if(!host||origin.host!==host||!["http:","https:"].includes(origin.protocol)||
        (process.env.APP_PUBLIC_ORIGIN&&origin.origin!==process.env.APP_PUBLIC_ORIGIN)){
        throw Error("Origin mismatch");
      }
    }catch{
      return NextResponse.json({detail:"Origin verification failed"},{
        status:403,headers:output,
      });
    }
  }
  const query=new URLSearchParams();
  const accepted=path==="/audience"
    ?new Set(["audience","segment","channel","category"])
    :path==="/consent-events"&&request.method==="GET"
      ?new Set(["recipient_kind","recipient_id"])
    :path.startsWith("/templates/")&&request.method==="DELETE"
      ?new Set(["version"]):new Set<string>();
  for(const [key,value] of request.nextUrl.searchParams){
    if(!accepted.has(key)||query.has(key)||value.length>64){
      return NextResponse.json({detail:"Invalid query"},{
        status:400,headers:output,
      });
    }
    query.set(key,value);
  }
  const backend=backendOrigin();
  if(!backend)return NextResponse.json({detail:"Backend unavailable"},{
    status:503,headers:output,
  });
  const headers=new Headers();
  const session=request.cookies.get("sas_session")?.value;
  if(session)headers.set("cookie","sas_session="+encodeURIComponent(session));
  const csrf=request.headers.get("x-csrf-token");
  if(csrf&&csrf.length<=128)headers.set("x-csrf-token",csrf);
  let body:string|undefined;
  if(write){
    const size=Number(request.headers.get("content-length")??0);
    if(!Number.isFinite(size)||size>8192){
      return NextResponse.json({detail:"Body too large"},{
        status:413,headers:output,
      });
    }
    if(request.method==="POST"||request.method==="PATCH"){
      if(!(request.headers.get("content-type")??"").startsWith("application/json")){
        return NextResponse.json({detail:"JSON required"},{
          status:415,headers:output,
        });
      }
      body=await request.text();
      if(body.length>8192){
        return NextResponse.json({detail:"Body too large"},{
          status:413,headers:output,
        });
      }
      headers.set("content-type","application/json");
    }
  }
  try{
    const response=await fetch(
      backend+"/v1/communication"+path+(query.size?"?"+query:""),{
        method:request.method,headers,body,
        redirect:"manual",cache:"no-store",signal:AbortSignal.timeout(15000),
      },
    );
    return new NextResponse(response.status===204?null:await response.text(),{
      status:response.status,
      headers:response.status===204?{"Cache-Control":"no-store"}:output,
    });
  }catch{
    return NextResponse.json({detail:"Communication service unavailable"},{
      status:503,headers:output,
    });
  }
}
export const GET=handle;
export const POST=handle;
export const PATCH=handle;
export const DELETE=handle;
export const PUT=handle;
