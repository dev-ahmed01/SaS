"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { PromoterEditor } from "./promoter-editor";
import { PromoterSponsors } from "./promoter-sponsors";
import { PromoterStatusDialog } from "./promoter-status-dialog";
import type { Promoter } from "./promoter-types";
import { formatCRMDate } from "../../lib/crm-dates";

type Activity={id:string;kind:string;title:string;detail:string;occurred_at:string};
function Tile({label,children}:{label:string;children:React.ReactNode}){
  return <div className="crm-summary-tile"><span className="crm-muted">{label}</span><strong>{children}</strong></div>;
}
export function PromoterDetails({id}:{id:string}){
  const [record,setRecord]=useState<Promoter|null>(null);
  const [activity,setActivity]=useState<Activity[]>([]);
  const [filter,setFilter]=useState("all");
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [confirm,setConfirm]=useState(false);
  const [revision,setRevision]=useState(0);
  const refresh=()=>setRevision(x=>x+1);
  const load=useCallback(async(signal?:AbortSignal)=>{
    const response=await fetch("/api/admin/promoters/"+id,{cache:"no-store",signal});
    if(!response.ok)throw Error("Could not load promoter details.");
    return await response.json() as Promoter;
  },[id]);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    Promise.all([
      load(controller.signal),
      fetch("/api/admin/promoters/"+id+"/activity",{cache:"no-store",signal:controller.signal})
        .then(async r=>{if(!r.ok)throw Error("Activity timeline unavailable.");return r.json() as Promise<Activity[]>;}),
    ]).then(([person,events])=>{
      if(!controller.signal.aborted){setRecord(person);setActivity(events);}
    }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not load promoter.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[load,revision]);
  const entries=filter==="all"?activity:activity.filter(entry=>entry.kind===filter);
  return <AppShell><div className="crm-details crm-redesign">
    <Link href="/promoters" className="back-link"><Icon name="arrow-left" size={17}/> All promoters</Link>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {loading?<p role="status">Loading promoter…</p>:record&&<>
      <div className="crm-details-header">
        <div><div className="crm-title-line">
          <h2>{record.full_name}</h2><span className={"status-pill "+(record.is_active?"active":"inactive")}>
            {record.is_active?"Active":"Inactive"}</span>
          </div><p>Created {formatCRMDate(record.created_at)}</p></div>
      </div>
      {editing&&<PromoterEditor initial={record} onCancel={()=>setEditing(false)}
        onSaved={()=>{setEditing(false);refresh();}}/>}
      <div className="crm-summary-strip">
        <Tile label="Assigned people">{record.sponsor_count}</Tile>
        <Tile label="City">{record.area_city||"—"}</Tile>
        <Tile label="Contact">{record.mobile_number}</Tile>
        <Tile label="Last updated">{formatCRMDate(record.updated_at)}</Tile>
      </div>
      <div className="crm-redesign-columns">
        <section className="crm-detail-card">
          <h2>Overview</h2>
          <div className="crm-overview-grid">
            <Tile label="Full name">{record.full_name}</Tile>
            <Tile label="City">{record.area_city||"—"}</Tile>
            <Tile label="Contact">{record.mobile_number}
              {record.email&&<small>{record.email}</small>}</Tile>
            {record.occupation&&<Tile label="Occupation">{record.occupation}</Tile>}
            <Tile label="Status">{record.is_active?"Active":"Inactive"}</Tile>
            <Tile label="Assigned people">{record.sponsor_count}</Tile>
          </div>
        </section>
        <section className="crm-detail-card">
          <div className="crm-panel-heading"><h2>Activity timeline</h2>
            <select aria-label="Filter promoter activity" value={filter} onChange={e=>setFilter(e.target.value)}>
              <option value="all">All activity</option>
              <option value="assignment">Assignments</option>
              <option value="updated">Updates</option>
            </select></div>
          <ol className="crm-activity-timeline">
            {entries.map(item=><li key={item.id}>
              <span className={"crm-activity-dot "+item.kind} aria-hidden="true"/>
              <div><strong>{item.title}</strong><p>{item.detail}</p>
                <small>{formatCRMDate(item.occurred_at)} · {new Date(item.occurred_at).toLocaleTimeString("en-IN",{timeZone:"Asia/Kolkata",hour:"2-digit",minute:"2-digit"})} IST</small>
              </div>
            </li>)}
          </ol>
          {entries.length===0&&<p className="crm-muted">No recorded activity of this type.</p>}
        </section>
      </div>
      <div className="crm-redesign-columns crm-assignment-panels">
        <section className="crm-detail-card crm-assignment-card">
          <PromoterSponsors promoter={record} kind="sponsors" onChanged={refresh}/>
        </section>
        <section className="crm-detail-card crm-assignment-card">
          <PromoterSponsors promoter={record} kind="prospects" onChanged={refresh}/>
        </section>
      </div>
      <div className="crm-redesign-actions" aria-label="Promoter actions">
        <button type="button" className="btn btn-secondary" onClick={()=>setEditing(v=>!v)}>
          <Icon name="file" size={17}/> Edit</button>
        <button type="button" className={"btn "+(record.is_active?"btn-secondary crm-danger-btn":"btn-primary")}
          onClick={()=>setConfirm(true)}>
          {record.is_active?"Deactivate":"Reactivate"}
        </button>
      </div>
    </>}
    {confirm&&record&&<PromoterStatusDialog promoter={record} onClose={()=>setConfirm(false)}
      onChanged={()=>{setConfirm(false);refresh();}}/>}
  </div></AppShell>;
}
