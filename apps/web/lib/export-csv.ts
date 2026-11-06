/** Download every page of an authenticated organization-scoped CRM list.
 * Never report a partial CSV as successful. Admin cookie protection is provided
 * by the existing same-origin read-only Next.js gateway.
 */
export type ExportColumn<T>={
  title:string;
  value:(row:T)=>string|number|boolean|null|undefined;
};
type Paged<T>={items:T[];total:number;limit:number;offset:number};
const MAX_ROWS=50000;
function cell(value:unknown):string{
  const raw=String(value??"");
  const injectionSafe=/^\s*[=+@-]/.test(raw)?"'"+raw:raw;
  return '"'+injectionSafe.replace(/"/g,'""')+'"';
}
export async function exportAllCsv<T>(options:{
  url:string;
  filename:string;
  columns:ExportColumn<T>[];
  onProgress?:(count:number,total:number)=>void;
}):Promise<number>{
  const rows:T[]=[];
  let total:number|null=null;
  for(let offset=0;;){
    const url=new URL(options.url,window.location.origin);
    url.searchParams.set("limit","100");
    url.searchParams.set("offset",String(offset));
    const result=await fetch(url.toString(),{cache:"no-store",credentials:"same-origin"});
    if(!result.ok)throw Error(result.status===401?
      "Your session expired. Sign in again before exporting.":"Export failed. No CSV was downloaded.");
    const page=await result.json() as Paged<T>;
    if(!Array.isArray(page.items)||!Number.isSafeInteger(page.total)||page.total<0){
      throw Error("The export returned an invalid page; no file was created.");
    }
    if(total!==null&&page.total!==total){
      throw Error("Records changed while exporting. Retry for a consistent export.");
    }
    total=page.total;
    if(total>MAX_ROWS)throw Error("Export exceeds 50,000 records. Ask the administrator for a filtered extract.");
    if(rows.length+page.items.length>total){
      throw Error("The export returned inconsistent pagination. Retry.");
    }
    rows.push(...page.items);
    options.onProgress?.(rows.length,total);
    if(rows.length===total)break;
    if(page.items.length===0)throw Error("Export returned an incomplete page; no file was created.");
    offset=rows.length;
  }
  const lines=[options.columns.map(c=>cell(c.title)).join(","),
    ...rows.map(row=>options.columns.map(c=>cell(c.value(row))).join(","))];
  const blob=new Blob(["\uFEFF"+lines.join("\r\n")],{type:"text/csv;charset=utf-8"});
  const address=URL.createObjectURL(blob);
  const link=document.createElement("a");
  link.href=address;link.download=options.filename;document.body.appendChild(link);
  link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(address),1000);
  return rows.length;
}
