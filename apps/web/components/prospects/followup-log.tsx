"use client";

import { FormEvent, useEffect, useState } from "react";
import type { Prospect } from "./prospects-types";
import { dateInputFromISO, dateInputToISO, formatCRMDate, todayISTISO } from "../../lib/crm-dates";

type FollowUp={id:string;occurred_on:string;outcome:string;notes:string;
  next_followup_on:string|null;created_at:string};
const outcomes=[
  ["contacted","Contacted"],["no_answer","No answer"],["interested","Interested"],
  ["not_interested","Not interested"],["callback","Callback requested"],
];

export function FollowUpLog({prospect,onSaved}:{prospect:Prospect;onSaved:()=>void}){
  const [items,setItems]=useState<FollowUp[]>([]);
  const [occurred,setOccurred]=useState(()=>dateInputFromISO(todayISTISO()));
  const [next,setNext]=useState("");
  const [outcome,setOutcome]=useState("contacted");
  const [notes,setNotes]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/admin/prospects/"+prospect.id+"/followups",{signal:controller.signal,cache:"no-store"})
      .then(r=>{if(!r.ok)throw Error("Follow-up history unavailable");return r.json();})
      .then(v=>{if(!controller.signal.aborted)setItems(v as FollowUp[]);})
      .catch(e=>{if(!controller.signal.aborted)setError(String(e.message));});
    return ()=>controller.abort();
  },[prospect.id]);
  async function submit(event:FormEvent){
    event.preventDefault();
    const date=dateInputToISO(occurred);
    const nextDate=next.trim()?dateInputToISO(next):null;
    if(!date||date>todayISTISO()||(next.trim()&&(!nextDate||nextDate<todayISTISO()))){
      setError("Dates must use DD/MM/YY; the next follow-up cannot be in the past.");return;
    }
    if(notes.trim().length<3){setError("Record the follow-up outcome.");return;}
    setSaving(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const {csrf_token}=await session.json();
      const response=await fetch("/api/admin/prospects/"+prospect.id+"/followups",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({
          version:prospect.version,occurred_on:date,
          outcome,notes:notes.trim(),next_followup_on:nextDate,
        }),
      });
      if(!response.ok)throw Error(response.status===409
        ?"Prospect was changed. Refresh before adding activity.":"Could not record follow-up.");
      setNotes("");setNext("");onSaved();
    }catch(e){setError(e instanceof Error?e.message:"Could not record follow-up.");}
    finally{setSaving(false);}
  }
  return <>
    <h2>Follow-up activity</h2>
    <form onSubmit={submit} className="crm-followup-form">
      <div className="crm-followup-fields">
        <label className="field"><span className="field-label">Contact date (DD/MM/YY) *</span>
          <input required value={occurred} pattern="[0-9]{2}/[0-9]{2}/[0-9]{2}"
            onChange={e=>setOccurred(e.target.value)} placeholder="DD/MM/YY"/></label>
        <label className="field"><span className="field-label">Outcome *</span>
          <select value={outcome} onChange={e=>setOutcome(e.target.value)}>
            {outcomes.map(([value,label])=><option key={value} value={value}>{label}</option>)}
          </select></label>
        <label className="field"><span className="field-label">Next follow-up (DD/MM/YY)</span>
          <input value={next} pattern="[0-9]{2}/[0-9]{2}/[0-9]{2}"
            onChange={e=>setNext(e.target.value)} placeholder="DD/MM/YY"/></label>
      </div>
      <label className="field"><span className="field-label">Activity notes *</span>
        <textarea required rows={2} minLength={3} maxLength={500}
          value={notes} onChange={e=>setNotes(e.target.value)}
          placeholder="What was discussed and what happens next?"/></label>
      <button type="submit" className="btn btn-secondary" disabled={saving}>
        {saving?"Saving…":"Log follow-up"}</button>
    </form>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {items.length===0?<p className="crm-muted">No follow-ups logged yet.</p>:
      <ol className="crm-stage-history">{items.map(item=><li key={item.id}>
        <strong>{outcomes.find(o=>o[0]===item.outcome)?.[1]??item.outcome}</strong>
        <span>{formatCRMDate(item.occurred_on)}
          {item.next_followup_on?" · Next: "+formatCRMDate(item.next_followup_on):""}</span>
        <p>{item.notes}</p>
      </li>)}</ol>}
  </>;
}
