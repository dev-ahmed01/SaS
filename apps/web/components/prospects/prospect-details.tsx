"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { FollowUpLog } from "./followup-log";
import { formatCRMDate } from "../../lib/crm-dates";
import { ProspectEditor } from "./prospect-editor";
import { StageDialog } from "./stage-dialog";
import type { Prospect } from "./prospects-types";

type Activity={id:string;kind:string;title:string;detail:string;occurred_at:string};
type NoticeStatus={status:string;attempted_at:string|null};
const noticeLabels:Record<string,string>={
  accepted_unverified:"Accepted by Saasyto · delivery not verified",
  rejected:"Rejected by provider",
  unknown:"Provider outcome unknown · no automatic retry",
  unconfirmed:"Submission unresolved · no automatic retry",
  suppressed_no_general_consent:"Not sent · WhatsApp update permission missing",
  suppressed_local_test_number:"Not sent · outside approved test recipients",
  before_sender_activation:"Not sent · sender activation date not reached",
  disabled:"Not enabled for this activation",
};
const money=(p:number)=>(p/100).toLocaleString("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:0});
function Tile({label,children}:{label:string;children:React.ReactNode}){
  return <div className="crm-summary-tile"><span className="crm-muted">{label}</span>
    <strong>{children}</strong></div>;
}
export function ProspectDetails({id}:{id:string}){
  const [record,setRecord]=useState<Prospect|null>(null);
  const loadedId=useRef<string|null>(null);
  const [activity,setActivity]=useState<Activity[]>([]);
  const [filter,setFilter]=useState("all");
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [activationNotice,setActivationNotice]=useState("");
  const [noticeRecord,setNoticeRecord]=useState<NoticeStatus|null>(null);
  const [editing,setEditing]=useState(false);
  const [stageOpen,setStageOpen]=useState(false);
  const [deleteOpen,setDeleteOpen]=useState(false);
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
    // Keep the same person's view mounted while refreshing after edits.
    // Switching to a different person still hides stale private data.
    if(loadedId.current!==id){setLoading(true);setRecord(null);setNoticeRecord(null);}
    setError("");
    Promise.all([
      load(controller.signal),
      fetch("/api/admin/prospects/"+id+"/activity",{cache:"no-store",signal:controller.signal})
        .then(async r=>{if(!r.ok)throw Error("Activity timeline unavailable.");return r.json() as Promise<Activity[]>;}),
      fetch("/api/admin/prospects/"+id+"/otp/notice-status",{
        cache:"no-store",signal:controller.signal,
      }).then(async r=>r.ok?await r.json() as NoticeStatus:null).catch(()=>null),
    ]).then(([person,events,notice])=>{
      if(!controller.signal.aborted){
        loadedId.current=id;
        setRecord(person);setActivity(events);setNoticeRecord(notice);
      }
    }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not load details.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[load,revision,id]);
  async function permanentlyDelete(){
    if(!record||busy)return;
    setBusy(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired. Sign in again.");
      const {csrf_token}=await session.json();
      const response=await fetch("/api/admin/prospects/"+id+"/permanent-delete",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({version:record.version,confirmation:"DELETE"}),
      });
      if(!response.ok){
        const payload=await response.json().catch(()=>null);
        throw Error(response.status===409
          ?(typeof payload?.detail==="string"?payload.detail:
            "This prospect has linked history and cannot be permanently deleted.")
          :"Could not permanently delete this prospect.");
      }
      window.location.assign("/prospects");
    }catch(e){setError(e instanceof Error?e.message:"Could not delete prospect.");}
    finally{setBusy(false);setDeleteOpen(false);}
  }
  const entries=filter==="all"?activity:activity.filter(item=>item.kind===filter);
  const initials=record?.full_name.split(/\s+/).filter(Boolean)
    .map(part=>part[0]).slice(0,2).join("").toUpperCase()??"";
  return <AppShell><div className="crm-details crm-redesign">
    <Link href="/prospects" className="back-link"><Icon name="arrow-left" size={17}/> All prospects</Link>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {activationNotice&&<p role="status" className="form-success">{activationNotice}</p>}
    {loading?<p role="status">Loading prospect…</p>:record&&<>
      <header className="prospect-hero">
        <span className="prospect-hero-avatar" aria-hidden="true">{initials}</span>
        <div className="prospect-hero-copy">
          <div className="crm-title-line">
            <h2>{record.full_name}</h2>
            <span className={"status-pill "+record.crm_stage}>
              {record.archived_at?"Archived":record.crm_stage==="active"?"Active":"Inactive"}
            </span>
          </div>
          <div className="prospect-hero-meta">
            <span><Icon name="message" size={15}/>{record.mobile_number}</span>
            <span><Icon name="calendar" size={15}/> Created {formatCRMDate(record.created_at)}</span>
          </div>
          {record.crm_stage==="active"&&noticeRecord&&noticeLabels[noticeRecord.status]&&
            <p className="crm-muted prospect-hero-notice" role="status">
              WhatsApp acknowledgement: {noticeLabels[noticeRecord.status]}
              {noticeRecord.attempted_at&&
                <span> · {formatCRMDate(noticeRecord.attempted_at)}</span>}
            </p>}
        </div>
        <div className="prospect-hero-actions">
          {!record.archived_at&&<button type="button" className="btn btn-secondary"
            onClick={()=>setEditing(v=>!v)} aria-expanded={editing}>
            <Icon name="pencil" size={16}/> {editing?"Close edit":"Edit details"}
          </button>}
          <button type="button" className={"btn "+(record.crm_stage==="active"?
            "btn-secondary crm-danger-btn":"btn-primary")}
            disabled={Boolean(record.archived_at)}
            onClick={()=>setStageOpen(true)}>
            {record.crm_stage==="active"?"Mark Inactive":"Mark Active"}
          </button>
        </div>
      </header>
      <div className="prospect-overview-metrics" aria-label="Prospect overview">
        <div className="prospect-overview-metric is-primary">
          <span className="prospect-overview-icon"><Icon name="wallet" size={21}/></span>
          <div><span>Total contribution</span>
            <strong>{money(record.total_contribution_paise)}</strong>
            <small>Verified contributions to date</small></div>
        </div>
        <div className="prospect-overview-metric">
          <span className="prospect-overview-icon"><Icon name="receipt" size={21}/></span>
          <div><span>Monthly sponsorship</span>
            <strong>{money(record.monthly_contribution_paise)}</strong>
            <small>{record.monthly_contribution_paise/25000} × ₹250</small></div>
        </div>
        <div className="prospect-overview-metric">
          <span className="prospect-overview-icon"><Icon name="users" size={21}/></span>
          <div><span>Assigned promoter</span>
            <strong className="prospect-overview-name">{record.assigned_promoter_name??"Unassigned"}</strong>
            <small>{record.assigned_promoter_name?"Current assignment":"Not assigned"}</small></div>
        </div>
        <div className="prospect-overview-metric">
          <span className="prospect-overview-icon"><Icon name="calendar" size={21}/></span>
          <div><span>Next follow-up</span>
            <strong className="prospect-overview-name">{record.next_followup_on?
              formatCRMDate(record.next_followup_on):"Not scheduled"}</strong>
            <small>Based on saved CRM follow-ups</small></div>
        </div>
      </div>
      <section className="crm-detail-card crm-followup-wide">
        <FollowUpLog prospect={record} onSaved={refresh}/>
      </section>
      <div className="crm-redesign-columns">
        <section className="crm-detail-card">
          <div className="crm-panel-heading"><h2><Icon name="users" size={20}/> Personal details</h2></div>
          {editing?<ProspectEditor initial={record}
            onCancel={()=>setEditing(false)} onSaved={()=>{setEditing(false);refresh();}}/>:
            <div className="crm-overview-grid">
              <Tile label="Full name">{record.full_name}</Tile>
              <Tile label="Mobile (WhatsApp)">{record.mobile_number}</Tile>
              <Tile label="Email">{record.email||"—"}</Tile>
              <Tile label="City">{record.area_city||"—"}</Tile>
              <Tile label="Start month">{formatCRMDate(record.start_month)}</Tile>
              <Tile label="Payment status">{record.lifecycle_status==="new"?"Never paid":record.lifecycle_status}</Tile>
              <Tile label="Total contribution">{money(record.total_contribution_paise)}</Tile>
            </div>}
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
      <div className="crm-redesign-actions prospect-danger-footer" aria-label="Additional prospect actions">
        <button type="button" className="btn btn-secondary crm-danger-btn"
          onClick={()=>setDeleteOpen(true)}>
          <Icon name="trash" size={17}/> Delete prospect</button>
      </div>
    </>}
    {stageOpen&&record&&<StageDialog prospect={record} onClose={()=>setStageOpen(false)}
      onChanged={message=>{setStageOpen(false);setActivationNotice(message??"");refresh();}}/>}
    {deleteOpen&&record&&<div className="crm-dialog-scrim">
      <section className="crm-dialog" role="dialog" aria-modal="true"
        aria-label="Confirm permanent prospect deletion">
        <h2>Are you sure you want to delete this prospect?</h2>
        <p>This permanently deletes the record, not archives it. Records with
          payment, communications, follow-up or assignment history cannot be
          permanently deleted; the app will explain any restriction.</p>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" disabled={busy}
            onClick={()=>setDeleteOpen(false)}>Cancel</button>
          <button type="button" className="btn btn-danger" disabled={busy}
            onClick={()=>void permanentlyDelete()}>
            {busy?"Deleting…":"Yes, delete permanently"}
          </button>
        </div>
      </section>
    </div>}
  </div></AppShell>;
}
