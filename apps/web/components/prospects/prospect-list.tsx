"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { Icon } from "../ui/icon";
import { StageDialog } from "./stage-dialog";
import { formatCRMDate } from "../../lib/crm-dates";
import type { Prospect,ProspectPage } from "./prospects-types";
import { reasonLabel } from "./prospects-types";

const money=(paise:number)=>(paise/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",maximumFractionDigits:0,
});
const displayDate=formatCRMDate;
const displayMonth=(date:string|null)=>date
  ?new Date(date.slice(0,7)+"-01T00:00:00Z").toLocaleDateString("en-IN",{month:"short",year:"numeric",timeZone:"UTC"})
  :"—";

export function ProspectList({view}:{view:"all"|"active"|"inactive"}){
  const router=useRouter();
  const [search,setSearch]=useState("");
  const [q,setQ]=useState("");
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [page,setPage]=useState<ProspectPage|null>(()=>recentSnapshot<ProspectPage>("/api/admin/prospects?"+new URLSearchParams({limit:"20",offset:"0",q:"",...(view!=="all"?{crm_stage:view}:{})})));
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [stageProspect,setStageProspect]=useState<Prospect|null>(null);
  useEffect(()=>{
    const timer=setTimeout(()=>{setQ(search);setOffset(0);},250);
    return ()=>clearTimeout(timer);
  },[search]);
  useEffect(()=>setOffset(0),[view]);
  const load=useCallback(async(signal:AbortSignal)=>{
    const params=new URLSearchParams({limit:"20",offset:String(offset),q});
    if(view!=="all")params.set("crm_stage",view);
    const r=await fetch("/api/admin/prospects?"+params,{cache:"no-store",signal});
    if(!r.ok)throw Error(r.status===401?"Your session expired. Sign in again.":"Could not load prospects.");
    return await r.json() as ProspectPage;
  },[offset,q,view]);
  useEffect(()=>{
    const controller=new AbortController();
    const params=new URLSearchParams({limit:"20",offset:String(offset),q});
    if(view!=="all")params.set("crm_stage",view);
    const key="/api/admin/prospects?"+params;
    const cached=recentSnapshot<ProspectPage>(key);
    setPage(cached);setLoading(!cached);setError("");
    load(controller.signal).then(result=>{if(!controller.signal.aborted){rememberSnapshot(key,result);setPage(result);}})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[load,revision]);
  const title=view==="all"?"All Prospects":view==="active"?"Active Prospects":"Inactive Prospects";

  return <section className="crm-list" aria-label={title}>
    <div className="crm-list-tools">
      <label className="search-control"><Icon name="search" size={18}/><span className="sr-only">Search prospects</span>
        <input type="text" value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="Search names, WhatsApp, city, email…"/></label>

    </div>
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="table-scroll crm-table-scroll">
      <table className="data-table prospects-table crm-table">
        <thead><tr>
          {["Created","Full Name","Mobile","City","Sponsorship","Start","Promoter","Stage",...(view==="all"?[]:["Status"]),"Action"].map(name=>
            <th key={name} scope="col">{name}</th>)}
        </tr></thead>
        <tbody>
          {loading&&!page?<tr><td colSpan={view==="all"?9:10}><p role="status" className="crm-list-empty">Loading prospects…</p></td></tr>
          :!page||page.items.length===0?<tr><td colSpan={view==="all"?9:10}>
            <div className="crm-list-empty"><Icon name="users" size={29}/>
              <h2>{view==="inactive"?"No inactive prospects":view==="active"?"No active prospects":"No prospects yet"}</h2>
              <p>{q?"Try another search.":view==="all"?"Add a prospect to begin.":"Stage changes will appear here."}</p>
              {view==="all"&&<Link href="/prospects/add" className="btn btn-primary">Add Prospect</Link>}
            </div>
          </td></tr>
          :page.items.map(p=><tr key={p.id} className={p.archived_at?"is-archived":""}>
            <td>{displayDate(p.created_at)}</td>
            <td><Link className="crm-person-link" href={"/prospects/"+p.id}>{p.full_name}</Link>
              {p.archived_at&&<span className="table-subtitle">Archived</span>}</td>
            <td>{p.mobile_number}</td>
            <td>{p.area_city||"—"}</td>
            <td className="crm-money">{money(p.monthly_contribution_paise)}</td>
            <td>{displayMonth(p.start_month)}</td>
            <td>{p.assigned_promoter_name||"Unassigned"}</td>
            <td title={p.pipeline_stage_name??"Unassigned"}>
              <span className="crm-pipeline-label">
                <span className="pipeline-stage-dot"
                  style={{backgroundColor:p.pipeline_stage_color??"#94a3b8"}}/>
                <span className="crm-ellipsis">{p.pipeline_stage_name??"Unassigned"}</span>
              </span>
            </td>
            {view!=="all"&&<td><div className="crm-stage-cell">
              <span className={"status-pill "+p.crm_stage}>
                {p.crm_stage==="active"?"Active":"Inactive"}</span>
              {p.crm_stage==="inactive"&&<span className="crm-stage-muted"
                title={reasonLabel(p.crm_inactive_reason)}>
                {p.days_inactive??0} days</span>}
            </div></td>}
            <td className="crm-action-cell">
              <select className="crm-row-actions" value="" aria-label={"Actions for "+p.full_name}
                onChange={e=>{
                  const action=e.target.value;
                  if(action==="status")setStageProspect(p);
                  if(action==="details")router.push("/prospects/"+p.id);
                }}>
                <option value="">Actions ▾</option>
                <option value="status">{p.crm_stage==="active"?"Mark Inactive":"Mark Active"}</option>
                <option value="details">View details</option>
              </select>
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{page?"Showing "+(page.total?offset+1:0)+"–"+Math.min(offset+20,page.total)+" of "+page.total:"Loading…"}</span>
      <div className="paging-actions">
        <button type="button" className="btn btn-secondary" disabled={loading||offset===0}
          onClick={()=>setOffset(n=>Math.max(0,n-20))}>Previous</button>
        <button type="button" className="btn btn-secondary" disabled={loading||!page||offset+20>=page.total}
          onClick={()=>setOffset(n=>n+20)}>Next</button>
      </div>
    </div>
    {stageProspect&&<StageDialog prospect={stageProspect} onClose={()=>setStageProspect(null)}
      onChanged={()=>{setStageProspect(null);setRevision(n=>n+1);}}/>}
  </section>;
}
