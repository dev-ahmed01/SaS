"use client";

import { FormEvent, useEffect, useState } from "react";
import type { Prospect } from "./prospects-types";
import { pipelineStages, type PipelineStage } from "./pipeline-types";
import { formatCRMDate, todayISTISO } from "../../lib/crm-dates";

type FollowUp={
  id:string;occurred_on:string;notes:string;created_at:string;
  next_followup_on:string|null;next_followup_at:string|null;
  pipeline_stage_id:string|null;pipeline_stage_name:string|null;
};

function nextLabel(row:FollowUp){
  if(!row.next_followup_at)return row.next_followup_on
    ?" · Next: "+formatCRMDate(row.next_followup_on):"";
  const date=new Date(row.next_followup_at);
  return " · Next: "+formatCRMDate(row.next_followup_at)+" "+
    date.toLocaleTimeString("en-IN",{timeZone:"Asia/Kolkata",hour:"2-digit",minute:"2-digit"})+" IST";
}

export function FollowUpLog({prospect,onSaved}:{prospect:Prospect;onSaved:()=>void}){
  const [items,setItems]=useState<FollowUp[]>([]);
  const [stages,setStages]=useState<PipelineStage[]>([]);
  const [stageId,setStageId]=useState(prospect.pipeline_stage_id??"");
  const [occurred,setOccurred]=useState(()=>todayISTISO());
  const [next,setNext]=useState("");
  const [nextTime,setNextTime]=useState("");
  const [notes,setNotes]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{setStageId(prospect.pipeline_stage_id??"");},[prospect.pipeline_stage_id]);
  useEffect(()=>{
    let active=true;
    pipelineStages().then(values=>{if(active)setStages(values);})
      .catch(()=>{if(active)setError("Could not load prospect stages.");});
    return ()=>{active=false;};
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/admin/prospects/"+prospect.id+"/followups",{signal:controller.signal,cache:"no-store"})
      .then(r=>{if(!r.ok)throw Error("Follow-up history unavailable");return r.json();})
      .then(v=>{if(!controller.signal.aborted)setItems(v as FollowUp[]);})
      .catch(e=>{if(!controller.signal.aborted)setError(String(e.message));});
    return ()=>controller.abort();
  },[prospect.id,prospect.version]);
  async function submit(event:FormEvent){
    event.preventDefault();
    const date=occurred;
    const nextDate=next||null;
    if(!date||date>todayISTISO()||(next.trim()&&(!nextDate||nextDate<todayISTISO()))){
      setError("Choose valid dates in the calendar; the next follow-up cannot be in the past.");return;
    }
    if(!stageId||!stages.some(s=>s.id===stageId)){
      setError("Select an existing prospect stage.");return;
    }
    if(nextDate&&!nextTime){setError("Select a time for the next follow-up.");return;}
    const nextAt=nextDate&&nextTime?nextDate+"T"+nextTime+":00+05:30":null;
    if(nextAt&&Date.parse(nextAt)<=Date.now()){
      setError("Next follow-up must be a future date and time (IST).");return;
    }
    if(notes.trim().length<3){setError("Enter a meaningful follow-up note.");return;}
    setSaving(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const {csrf_token}=await session.json();
      const response=await fetch("/api/admin/prospects/"+prospect.id+"/followups",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({
          version:prospect.version,occurred_on:date,notes:notes.trim(),
          pipeline_stage_id:stageId,next_followup_at:nextAt,
        }),
      });
      if(!response.ok)throw Error(response.status===409
        ?"Prospect was changed. Refresh before adding activity.":"Could not record follow-up.");
      setNotes("");setNext("");setNextTime("");onSaved();
    }catch(e){setError(e instanceof Error?e.message:"Could not record follow-up.");}
    finally{setSaving(false);}
  }
  return <>
    <h2>Follow-up &amp; Activity</h2>
    <form onSubmit={submit} className="crm-followup-form">
      <div className="crm-followup-fields">
        <label className="field"><span className="field-label">Contact date *</span>
          <input type="date" required max={todayISTISO()} value={occurred}
            onChange={e=>setOccurred(e.target.value)}/></label>
        <label className="field"><span className="field-label">Stage *</span>
          <select aria-label="Follow-up stage" value={stageId} required
            onChange={e=>setStageId(e.target.value)}>
            <option value="">Select stage</option>
            {stages.map(stage=><option key={stage.id} value={stage.id}>{stage.name}</option>)}
          </select></label>
        <label className="field"><span className="field-label">Next follow-up</span>
          <input type="date" min={todayISTISO()} value={next}
            onChange={e=>setNext(e.target.value)}/></label>
        <label className="field"><span className="field-label">Time (IST)</span>
          <input aria-label="Next follow-up time (IST)" type="time" value={nextTime}
            required={Boolean(next)} disabled={!next}
            onChange={e=>setNextTime(e.target.value)}/></label>
      </div>
      <label className="field"><span className="field-label">Follow-up Note *</span>
        <textarea required rows={2} minLength={3} maxLength={500}
          value={notes} onChange={e=>setNotes(e.target.value)}
          placeholder="What was discussed and what happens next?"/></label>
      <button type="submit" className="btn btn-secondary" disabled={saving}>
        {saving?"Saving…":"Log follow-up"}</button>
    </form>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {items.length===0?<p className="crm-muted">No follow-ups logged yet.</p>:
      <ol className="crm-stage-history">{items.map(item=><li key={item.id}>
        <strong>{item.pipeline_stage_name??"Follow-up"}</strong>
        <span>{formatCRMDate(item.occurred_on)}{nextLabel(item)}</span>
        <p>{item.notes}</p>
      </li>)}</ol>}
  </>;
}
