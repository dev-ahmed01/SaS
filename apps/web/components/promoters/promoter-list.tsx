"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { Icon } from "../ui/icon";
import { exportAllCsv } from "../../lib/export-csv";
import type { Promoter, PromoterPage } from "./promoter-types";
import { PromoterStatusDialog } from "./promoter-status-dialog";
import { formatCRMDate } from "../../lib/crm-dates";

const displayDate=formatCRMDate;

export function PromoterList({view}:{view:"all"|"active"|"inactive"}){
  const [search,setSearch]=useState("");
  const [q,setQ]=useState("");
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [page,setPage]=useState<PromoterPage|null>(()=>recentSnapshot<PromoterPage>("/api/admin/promoters?"+new URLSearchParams({q:"",limit:"20",offset:"0",...(view!=="all"?{active:String(view==="active")}:{})})));
  const [error,setError]=useState("");
  const [exporting,setExporting]=useState(false);
  const [exportProgress,setExportProgress]=useState("");
  const [loading,setLoading]=useState(true);
  const [target,setTarget]=useState<Promoter|null>(null);

  useEffect(()=>{
    const timer=setTimeout(()=>{setQ(search);setOffset(0);},250);
    return ()=>clearTimeout(timer);
  },[search]);
  useEffect(()=>setOffset(0),[view]);
  const fetchPage=useCallback(async(signal:AbortSignal)=>{
    const query=new URLSearchParams({q,limit:"20",offset:String(offset)});
    if(view!=="all")query.set("active",String(view==="active"));
    const response=await fetch("/api/admin/promoters?"+query,{
      cache:"no-store",signal,
    });
    if(!response.ok)throw Error("Unable to load promoters.");
    return await response.json() as PromoterPage;
  },[q,offset,view]);
  useEffect(()=>{
    const abort=new AbortController();
    const query=new URLSearchParams({q,limit:"20",offset:String(offset)});
    if(view!=="all")query.set("active",String(view==="active"));
    const key="/api/admin/promoters?"+query;
    const cached=recentSnapshot<PromoterPage>(key);
    setPage(cached);setLoading(!cached);setError("");
    fetchPage(abort.signal)
      .then(data=>{if(!abort.signal.aborted){rememberSnapshot(key,data);setPage(data);}})
      .catch(e=>{if(!abort.signal.aborted)setError(e.message);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return ()=>abort.abort();
  },[fetchPage,revision]);

  async function exportView(){
    if(exporting)return;
    setExporting(true);setError("");setExportProgress("Preparing promoter export…");
    try{
      const params=new URLSearchParams({q});
      if(view!=="all")params.set("active",String(view==="active"));
      const count=await exportAllCsv<Promoter>({
        url:"/api/admin/promoters?"+params,
        filename:"sas-promoters-"+view+"-all.csv",
        onProgress:(count,total)=>setExportProgress("Exporting "+count+" of "+total+" promoters…"),
        columns:[
          {title:"Name",value:p=>p.full_name},
          {title:"Mobile",value:p=>p.mobile_number},
          {title:"Email",value:p=>p.email},
          {title:"City",value:p=>p.area_city},
          {title:"Sponsors",value:p=>p.sponsor_count},
          {title:"Status",value:p=>p.is_active?"Active":"Inactive"},
          {title:"WhatsApp consent",value:p=>p.whatsapp_opt_in},
          {title:"Created",value:p=>p.created_at}
        ]
      });
      setExportProgress(count+" promoters exported.");
    }catch(e){setExportProgress("");setError(e instanceof Error?e.message:"Export failed.");}
    finally{setExporting(false);}
  }

  const title=view==="all"?"All Promoters":view==="active"?"Active Promoters":"Inactive Promoters";
  return <section className="crm-list crm-directory crm-promoter-directory" aria-label={title}>
    <div className="crm-directory-intro">
      <div>
        <span className="crm-directory-eyebrow">PROMOTER DIRECTORY</span>
        <h2>${title}</h2>
        <p>Find promoters, review their assigned sponsors and manage their status.</p>
      </div>
      <div className="crm-directory-count" role="status" aria-live="polite">
        <strong>${loading&&!page?\"…\":page?.total??0}</strong>
        <span>${q?\"matching results\":\"promoters in this view\"}</span>
      </div>
    </div>
    <div className="crm-list-tools">
      <div className="crm-directory-search">
        <label className="search-control">
          <Icon name="search" size={18}/><span className="sr-only">Search promoters</span>
          <input type="search" value={search} onChange={e=>setSearch(e.target.value)}
            placeholder="Search names, mobile, city or email…"/>
        </label>
        {search&&<button type="button" className="crm-directory-clear"
          onClick={()=>setSearch("")}>Clear search</button>}
      </div>
      <div className="crm-list-actions">
        <button type="button" className="btn btn-secondary" disabled={exporting}
          onClick={()=>void exportView()}>
          <Icon name="download" size={16}/> {exporting?"Exporting…":"Export all results"}
        </button>
      </div>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {exportProgress&&<p className="crm-muted" role="status">{exportProgress}</p>}
    <div className="table-scroll crm-table-scroll">
      <table className="data-table crm-table promoter-crm-table">
        <thead><tr>{["Created","Full Name","Mobile","City","Sponsors","Status"].map(col=>
          <th scope="col" key={col}>{col}</th>)}</tr></thead>
        <tbody>
          {loading&&!page?<tr><td colSpan={6}><p role="status" className="crm-list-empty">Loading promoters…</p></td></tr>
            :!page?.items.length?<tr><td colSpan={6}>
              <div className="crm-list-empty">
                <Icon name="users" size={29}/><h2>No promoters found</h2>
                <p>{q?"Try another search.":"Add your first promoter to begin."}</p>
                {view==="all"&&<Link href="/promoters/add" className="btn btn-primary">Add Promoter</Link>}
              </div></td></tr>
            :page.items.map(item=><tr key={item.id}>
              <td>{displayDate(item.created_at)}</td>
              <td><Link className="crm-person-link" href={"/promoters/"+item.id}>{item.full_name}</Link></td>
              <td>{item.mobile_number}</td>
              <td>{item.area_city||"—"}</td>
              <td>{item.sponsor_count}</td>
              <td><div className="crm-stage-cell">
                <span className={"status-pill "+(item.is_active?"active":"inactive")}>
                  {item.is_active?"Active":"Inactive"}</span>
                <button type="button" className="text-action crm-stage-change"
                  aria-label={(item.is_active?"Deactivate ":"Reactivate ")+item.full_name}
                  onClick={()=>setTarget(item)}>
                  {item.is_active?"Deactivate":"Reactivate"}
                </button>
              </div></td>
            </tr>)}
        </tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{page?"Showing "+(page.total?offset+1:0)+"–"+
        Math.min(offset+20,page.total)+" of "+page.total:"Loading…"}</span>
      <div className="paging-actions">
        <button className="btn btn-secondary" type="button" disabled={loading||offset===0}
          onClick={()=>setOffset(x=>Math.max(0,x-20))}>Previous</button>
        <button className="btn btn-secondary" type="button"
          disabled={loading||!page||offset+20>=page.total}
          onClick={()=>setOffset(x=>x+20)}>Next</button>
      </div>
    </div>
    {target&&<PromoterStatusDialog promoter={target} onClose={()=>setTarget(null)}
      onChanged={()=>{setTarget(null);setRevision(v=>v+1);}}/>}
  </section>;
}
