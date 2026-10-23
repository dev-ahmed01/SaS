"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { FollowUpLog } from "./followup-log";
import { formatCRMDate } from "../../lib/crm-dates";
import { ProspectEditor } from "./prospect-editor";
import { ProspectStageControl } from "./prospect-stage-control";
import { StageDialog } from "./stage-dialog";
import type { Prospect } from "./prospects-types";

type Activity={id:string;kind:string;title:string;detail:string;occurred_at:string};
const money=(p:number)=>(p/100).toLocaleString("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:0});
function Tile({label,children}:{label:string;children:React.ReactNode}){
  return <div className="crm-summary-tile"><span className="crm-muted">{label}</span>
    <strong>{children}</strong></div>;
}
export function ProspectDetails({id}:{id:string}){
  const [record,setRecord]=useState<Prospect|null>(null);
  const [activity,setActivity]=useState<Activity[]>([]);
  const [filter,setFilter]=useState("all");
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [stageOpen,setStageOpen]=useState(false);
  const [archiveOpen,setArchiveOpen]=useState(false);
  const [busy,setBusy]=useState(false);
  const [revision,setRevision]=useState(0);
  const refresh=()=>setRevision(v=>v+1);
  const load=useCallback(async(signal?:AbortSignal)=>{
    const response=await fetch("/api/admin/prospects/"+id,{cache:"no-store",signal});
    if(!response.ok)throw Error(response.status===404?"Prospect not found.":"Could not load prospect details.");
    return await response.json() as Prospect;
  },[id]);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    Promise.all([
      load(controller.signal),
      fetch("/api/admin/prospects/"+id+"/activity",{cache:"no-store",signal:controller.signal})
        .then(async r=>{if(!r.ok)throw Error("Activity timeline unavailable.");return r.json() as Promise<Activity[]>;}),
    ]).then(([person,events])=>{
      if(!controller.signal.aborted){setRecord(person);setActivity(events);}
    }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not load details.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[load,revision]);
  async function archive(){
    if(!record||busy)return;
    setBusy(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired. Sign in again.");
      const {csrf_token}=await session.json();
      const restore=Boolean(record.archived_at);
      const response=await fetch("/api/admin/prospects/"+id+(restore?"/restore":""),{
        method:restore?"POST":"DELETE",credentials:"same-origin",
        headers:{"X-CSRF-Token":csrf_token,"If-Match":String(record.version)},
      });
      if(!response.ok)throw Error(response.status===409?"Prospect changed elsewhere. Reload and retry.":"Could not update prospect.");
      setArchiveOpen(false);refresh();
    }catch(e){setError(e instanceof Error?e.message:"Could not update prospect.");}
    finally{setBusy(false);}
  }
  const entries=filter==="all"?activity:activity.filter(item=>item.kind===filter);
  return <AppShell><div className="crm-details crm-redesign">
    <Link href="/prospects" className="back-link"><Icon name="arrow-left" size={17}/> All prospects</Link>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {loading?<p role="status">Loading prospect…</p>:record&&<>
      <div className="crm-details-header">
        <div><div className="crm-title-line">
          <h2>{record.full_name}</h2>
          <span className={"status-pill "+record.crm_stage}>
            {record.archived_at?"Archived":record.crm_stage==="active"?"Active":"Inactive"}
          </span></div>
          <p>Created {formatCRMDate(record.created_at)}</p>
        </div>
      </div>
      {editing&&<ProspectEditor initial={record}
        onCancel={()=>setEditing(false)} onSaved={()=>{setEditing(false);refresh();}}/>}
      <div className="crm-summary-strip">
        <Tile label="Assigned promoter">{record.assigned_promoter_name??"Unassigned"}</Tile>
        <Tile label="Monthly sponsorship">{money(record.monthly_contribution_paise)}
          <small>{record.monthly_contribution_paise/25000} × ₹250</small></Tile>
        <Tile label="Start month">{formatCRMDate(record.start_month)}</Tile>
        <Tile label="Payment status">{record.lifecycle_status==="new"?"Never paid":record.lifecycle_status}</Tile>
      </div>
      <div className="crm-redesign-columns">
        <section className="crm-detail-card">
          <h2>Overview</h2>
          <div className="crm-overview-grid">
            <Tile label="Full name">{record.full_name}</Tile>
            <Tile label="City">{record.area_city||"—"}</Tile>
            <Tile label="Contact"><span>{record.mobile_number}</span>
              {record.email&&<small>{record.email}</small>}</Tile>
            {record.occupation&&<Tile label="Occupation">{record.occupation}</Tile>}
            <Tile label="Sponsorship">{money(record.monthly_contribution_paise)} / month
              <small>{record.monthly_contribution_paise/25000} tokens · Starts {formatCRMDate(record.start_month)}</small></Tile>
            <Tile label="Last contribution">{formatCRMDate(record.last_verified_payment_at)}</Tile>
          </div>
          <ProspectStageControl prospect={record} onChanged={refresh}/>
        </section>
        <section className="crm-detail-card">
          <div className="crm-panel-heading"><h2>Activity timeline</h2>
            <select aria-label="Filter activity" value={filter} onChange={e=>setFilter(e.target.value)}>
              <option value="all">All activity</option>
              <option value="payment">Collections</option>
              <option value="status">Status</option>
              <option value="assignment">Assignments</option>
              <option value="followup">Follow-ups</option>
              <option value="updated">Updates</option>
            </select></div>
          <ol className="crm-activity-timeline" aria-label="Prospect activity">
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
      <section className="crm-detail-card crm-followup-wide">
        <FollowUpLog prospect={record} onSaved={refresh}/>
      </section>
      <div className="crm-redesign-actions" aria-label="Prospect actions">
        <button type="button" className="btn btn-secondary" disabled={Boolean(record.archived_at)}
          onClick={()=>setEditing(v=>!v)}><Icon name="file" size={17}/> Edit</button>
        <button type="button" className="btn btn-secondary crm-danger-btn" onClick={()=>setArchiveOpen(true)}>
          <Icon name="trash" size={17}/> {record.archived_at?"Restore":"Delete"}</button>
        <button type="button" className="btn btn-primary" disabled={Boolean(record.archived_at)}
          onClick={()=>setStageOpen(true)}>{record.crm_stage==="active"?"Mark Inactive":"Mark Active"}</button>
      </div>
    </>}
    {stageOpen&&record&&<StageDialog prospect={record} onClose={()=>setStageOpen(false)}
      onChanged={()=>{setStageOpen(false);refresh();}}/>}
    {archiveOpen&&record&&<div className="crm-dialog-scrim">
      <section className="crm-dialog" role="dialog" aria-modal="true" aria-label="Confirm prospect archive">
        <h2>{record.archived_at?"Restore prospect?":"Archive this prospect?"}</h2>
        <p>{record.archived_at?"This returns the prospect to normal lists.":
          "The prospect will be hidden without deleting collections or activity history."}</p>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" disabled={busy}
            onClick={()=>setArchiveOpen(false)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy}
            onClick={archive}>{busy?"Saving…":record.archived_at?"Restore prospect":"Archive prospect"}</button>
        </div>
      </section>
    </div>}
  </div></AppShell>;
}
