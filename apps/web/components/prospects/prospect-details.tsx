"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { FollowUpLog } from "./followup-log";
import { formatCRMDate } from "../../lib/crm-dates";
import { ProspectEditor } from "./prospect-editor";
import { StageDialog } from "./stage-dialog";
import type { Prospect } from "./prospects-types";
import { reasonLabel } from "./prospects-types";

const money=(p:number)=>(p/100).toLocaleString("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:0});
const dateFmt=formatCRMDate;
const monthFmt=(v:string|null)=>formatCRMDate(v);

function Info({label,value}:{label:string;value:React.ReactNode}){
  return <div className="crm-detail-field"><dt>{label}</dt><dd>{value??"—"}</dd></div>;
}
function Card({title,children}:{title:string;children:React.ReactNode}){
  return <section className="crm-detail-card"><h2>{title}</h2><dl className="crm-detail-grid">{children}</dl></section>;
}

export function ProspectDetails({id}:{id:string}){
  const [record,setRecord]=useState<Prospect|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [stageOpen,setStageOpen]=useState(false);
  const [archiveOpen,setArchiveOpen]=useState(false);
  const [busy,setBusy]=useState(false);
  const [revision,setRevision]=useState(0);
  const load=useCallback(async(signal?:AbortSignal)=>{
    const result=await fetch("/api/admin/prospects/"+id,{cache:"no-store",signal});
    if(!result.ok)throw Error(result.status===404?"This prospect could not be found.":"Could not load prospect details.");
    return await result.json() as Prospect;
  },[id]);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    load(controller.signal).then(item=>{if(!controller.signal.aborted)setRecord(item);})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
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
      if(!response.ok)throw Error(response.status===409
        ?"This prospect was changed elsewhere. Reload and try again."
        :"Could not update the record.");
      setArchiveOpen(false);setRevision(v=>v+1);
    }catch(e){setError(e instanceof Error?e.message:"Could not update the record.");}
    finally{setBusy(false);}
  }

  return <AppShell>
    <div className="crm-details">
      <Link href="/prospects" className="back-link"><Icon name="arrow-left" size={17}/> All prospects</Link>
      {error&&<p className="form-error" role="alert">{error}</p>}
      {loading?<p role="status">Loading prospect…</p>:record&&<>
        <div className="crm-details-header">
          <div><h2>{record.full_name}</h2><p>Created {dateFmt(record.created_at)}</p></div>
          <span className={"status-pill "+record.crm_stage}>{record.archived_at?"Archived":record.crm_stage==="active"?"Active":"Inactive"}</span>
        </div>
        {editing&&<ProspectEditor initial={record}
          onCancel={()=>setEditing(false)} onSaved={()=>{setEditing(false);setRevision(v=>v+1);}}/>}
        <div className="crm-detail-cards">
          <Card title="Personal information">
            <Info label="First name" value={record.first_name??record.full_name.split(" ")[0]}/>
            <Info label="Last name" value={record.last_name??(record.full_name.split(" ").slice(1).join(" ")||"—")}/>
            <Info label="City" value={record.area_city||"—"}/>
            <Info label="Occupation" value={record.occupation||"—"}/>
          </Card>
          <Card title="Contact">
            <Info label="WhatsApp / Mobile" value={record.mobile_number}/>
            <Info label="Email" value={record.email||"—"}/>
            <Info label="WhatsApp consent" value={record.whatsapp_opt_in?"Recorded":"Not recorded"}/>
          </Card>

          <Card title="Sponsorship">
            <Info label="Monthly sponsorship" value={money(record.monthly_contribution_paise)}/>
            <Info label="Tokens" value={String(record.monthly_contribution_paise/25000)+" × ₹250"}/>
            <Info label="Start month" value={monthFmt(record.start_month)}/>
            <Info label="Payment status" value={record.lifecycle_status==="new"?"Never paid":record.lifecycle_status}/>
            <Info label="Last verified contribution" value={dateFmt(record.last_verified_payment_at)}/>
          </Card>
          <Card title="Promoter & CRM">
            <Info label="Assigned promoter" value={record.assigned_promoter_name||"Unassigned"}/>
            <Info label="Prospect stage" value={record.pipeline_stage_name||"Unassigned"}/>
            <Info label="CRM status" value={record.crm_stage==="active"?"Active":"Inactive"}/>
            <Info label="Reason for inactivity" value={record.crm_stage==="inactive"?reasonLabel(record.crm_inactive_reason):"—"}/>
            <Info label="Inactive since" value={record.crm_stage==="inactive"?dateFmt(record.crm_stage_changed_at):"—"}/>
            <Info label="Days inactive" value={record.days_inactive!==null?String(record.days_inactive):"—"}/>
            <Info label="Last change" value={dateFmt(record.updated_at)}/>
          </Card>

          <section className="crm-detail-card">
            <FollowUpLog prospect={record} onSaved={()=>setRevision(v=>v+1)}/>
          </section>
          <section className="crm-detail-card">
            <h2>Stage history</h2>
            {record.stage_history.length===0?<p className="crm-muted">No manual stage changes yet.</p>
              :<ol className="crm-stage-history">
                {[...record.stage_history].reverse().map((event,i)=><li key={event.changed_at+i}>
                  <strong>{event.to_stage==="active"?"Moved to Active":"Moved to Inactive"}</strong>
                  <span>{dateFmt(event.changed_at)}{event.reason?" · "+reasonLabel(event.reason):""}</span>
                  {event.note&&<p>{event.note}</p>}
                </li>)}
              </ol>}
          </section>
        </div>
        <div className="crm-detail-actions" aria-label="Prospect actions">
          <button type="button" className="crm-action-card" disabled={Boolean(record.archived_at)}
            onClick={()=>setStageOpen(true)}>
            <Icon name="users" size={22}/>
            <span><strong>{record.crm_stage==="active"?"Mark Inactive":"Mark Active"}</strong>
              <small>Log the reason for changing CRM eligibility</small></span>
          </button>
          <button type="button" className="crm-action-card" disabled={Boolean(record.archived_at)}
            onClick={()=>setEditing(v=>!v)}>
            <Icon name="file" size={22}/>
            <span><strong>Edit</strong><small>Update contact and sponsorship</small></span>
          </button>
          <button type="button" className="crm-action-card danger" onClick={()=>setArchiveOpen(true)}>
            <Icon name="file" size={22}/>
            <span><strong>{record.archived_at?"Restore":"Delete"}</strong>
              <small>{record.archived_at?"Return to CRM":"Archive without deleting payment history"}</small></span>
          </button>
        </div>
      </>}
      {stageOpen&&record&&<StageDialog prospect={record} onClose={()=>setStageOpen(false)}
        onChanged={()=>{setStageOpen(false);setRevision(v=>v+1);}}/>}
      {archiveOpen&&record&&<div className="crm-dialog-scrim" role="presentation">
        <section className="crm-dialog" role="dialog" aria-modal="true" aria-label="Confirm prospect archive">
          <h2>{record.archived_at?"Restore prospect?":"Archive this prospect?"}</h2>
          <p>{record.archived_at?"This will return the prospect to normal lists.":"This hides the prospect from normal lists without deleting financial records, receipts, or activity history."}</p>
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={()=>setArchiveOpen(false)}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={archive}>
              {busy?"Saving…":record.archived_at?"Restore prospect":"Archive prospect"}
            </button>
          </div>
        </section>
      </div>}
    </div>
  </AppShell>;
}
