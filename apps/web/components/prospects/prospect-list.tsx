"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { Icon } from "../ui/icon";
import { formatCRMDate } from "../../lib/crm-dates";
import type { Prospect,ProspectPage } from "./prospects-types";
import { reasonLabel } from "./prospects-types";

const money=(paise:number)=>(paise/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",maximumFractionDigits:0,
});
const displayDate=formatCRMDate;
const safeCsv=(value:string|number|null|undefined)=>{
  const cell=String(value??"");
  const safe=/^\s*[=+@-]/.test(cell)?"'"+cell:cell;
  return '"'+safe.replace(/"/g,'""')+'"';
};

export function ProspectList({view}:{view:"all"|"active"|"inactive"}){
  const [search,setSearch]=useState("");
  const [q,setQ]=useState("");
  const [offset,setOffset]=useState(0);
  const [page,setPage]=useState<ProspectPage|null>(()=>recentSnapshot<ProspectPage>("/api/admin/prospects?"+new URLSearchParams({limit:"20",offset:"0",q:"",...(view!=="all"?{crm_stage:view}:{})})));
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [selected,setSelected]=useState<Record<string,Prospect>>({});
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
  },[load]);
  const title=view==="all"?"All Prospects":view==="active"?"Active Prospects":"Inactive Prospects";
  const selectedIds=Object.keys(selected);
  const visible=page?.items??[];
  const allVisibleSelected=visible.length>0&&visible.every(p=>Boolean(selected[p.id]));
  function toggle(p:Prospect,checked:boolean){
    setSelected(current=>{
      const next={...current};
      if(checked)next[p.id]=p;else delete next[p.id];
      return next;
    });
  }
  function exportSelected(){
    const rows=Object.values(selected);
    if(!rows.length)return;
    const header=["Name","Mobile","City","Monthly sponsorship (INR)","Total contribution (INR)",
      "Active date","Recent follow-up","Next follow-up","Promoter","Stage"];
    const csv=[header,...rows.map(p=>[
      p.full_name,p.mobile_number,p.area_city,p.monthly_contribution_paise/100,
      p.total_contribution_paise/100,p.crm_stage==="active"?formatCRMDate(p.crm_stage_changed_at):"",
      formatCRMDate(p.last_contact_on),formatCRMDate(p.next_followup_on),
      p.assigned_promoter_name??"",p.pipeline_stage_name??""
    ])].map(fields=>fields.map(safeCsv).join(",")).join("\r\n");
    const url=URL.createObjectURL(new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"}));
    const link=document.createElement("a");
    link.href=url;link.download="sas-prospects-selected.csv";
    document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
  }

  return <section className="crm-list" aria-label={title}>
    <div className="crm-list-tools">
      <label className="search-control"><Icon name="search" size={18}/><span className="sr-only">Search prospects</span>
        <input type="text" value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="Search names, WhatsApp, city, email…"/></label>
      <button type="button" className="btn btn-secondary"
        disabled={selectedIds.length===0} onClick={exportSelected}>
        Export selected ({selectedIds.length}) CSV
      </button>
    </div>
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="table-scroll crm-table-scroll">
      <table className={"data-table prospects-table crm-table"+(view==="all"?"":" has-status")}>
        <thead><tr>
          <th scope="col">
            <input type="checkbox" aria-label="Select all prospects on this page"
              checked={allVisibleSelected}
              onChange={e=>setSelected(current=>{
                const next={...current};
                for(const p of visible){if(e.target.checked)next[p.id]=p;else delete next[p.id];}
                return next;
              })}/>
          </th>
          {["Created","Full Name","Mobile","City","Sponsorship","Total contribution","Active date",
            "Recent follow-up","Next follow-up","Promoter","Stage",...(view==="all"?[]:["Status"])].map(name=>
            <th key={name} scope="col">{name}</th>)}
        </tr></thead>
        <tbody>
          {loading&&!page?<tr><td colSpan={view==="all"?12:13}><p role="status" className="crm-list-empty">Loading prospects…</p></td></tr>
          :!page||page.items.length===0?<tr><td colSpan={view==="all"?12:13}>
            <div className="crm-list-empty"><Icon name="users" size={29}/>
              <h2>{view==="inactive"?"No inactive prospects":view==="active"?"No active prospects":"No prospects yet"}</h2>
              <p>{q?"Try another search.":view==="all"?"Add a prospect to begin.":"Stage changes will appear here."}</p>
              {view==="all"&&<Link href="/prospects/add" className="btn btn-primary">Add Prospect</Link>}
            </div>
          </td></tr>
          :page.items.map(p=><tr key={p.id} className={p.archived_at?"is-archived":""}>
            <td><input type="checkbox" aria-label={"Select "+p.full_name}
              checked={Boolean(selected[p.id])} onChange={e=>toggle(p,e.target.checked)}/></td>
            <td>{displayDate(p.created_at)}</td>
            <td><Link className="crm-person-link" href={"/prospects/"+p.id}>{p.full_name}</Link>
              {p.archived_at&&<span className="table-subtitle">Archived</span>}</td>
            <td>{p.mobile_number}</td>
            <td>{p.area_city||"—"}</td>
            <td className="crm-money">{money(p.monthly_contribution_paise)}</td>
            <td className="crm-money">{money(p.total_contribution_paise)}</td>
            <td>{p.crm_stage==="active"?displayDate(p.crm_stage_changed_at):"—"}</td>
            <td>{displayDate(p.last_contact_on)}</td>
            <td>{displayDate(p.next_followup_on)}</td>
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
  </section>;
}
