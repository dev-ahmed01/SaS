"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  apiGet, apiWrite, audienceOptions, segmentOptions, triggerOptions,
} from "./types";
import type { Audience, Rule, Segment, Template } from "./types";
import { OtpCopyEditor } from "./otp-copy-editor";

export function CommunicationAutomations({revision=0}:{revision?:number}){
  const [templates,setTemplates]=useState<Template[]>([]);
  const [rules,setRules]=useState<Rule[]>([]);
  const [name,setName]=useState("");
  const [trigger,setTrigger]=useState("payment_received");
  const [audience,setAudience]=useState<Audience>("prospects");
  const [segment,setSegment]=useState<Segment>("active");
  const [templateId,setTemplateId]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [refresh,setRefresh]=useState(0);

  useEffect(()=>{
    Promise.all([apiGet<Template[]>("/templates"),apiGet<Rule[]>("/rules")])
      .then(([ts,rs])=>{setTemplates(ts);setRules(rs);})
      .catch(()=>setError("Could not load automation configuration."));
  },[refresh,revision]);
  function selectTrigger(value:string){
    setTrigger(value);setError("");
    if(value==="monthly_sponsor"){setAudience("prospects");setSegment("unpaid");}
    if(value==="monthly_promoter"){setAudience("promoters");setSegment("unpaid");}
  }
  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(saving)return;
    setSaving(true);setError("");setNotice("");
    try{
      await apiWrite("/rules","POST",{
        name:name.trim(),trigger_kind:trigger,audience,segment,template_id:templateId,
      });
      setName("");setTemplateId("");setRefresh(x=>x+1);
      setNotice("Trigger definition saved. It is inactive until approved delivery is connected.");
    }catch(e){setError(e instanceof Error?e.message:"Could not save automation.");}
    finally{setSaving(false);}
  }
  async function remove(rule:Rule){
    if(!window.confirm("Remove automation definition "+rule.name+"?"))return;
    setError("");setNotice("");
    try{
      await apiWrite("/rules/"+rule.id,"DELETE");
      setRefresh(x=>x+1);setNotice("Automation definition removed.");
    }catch(e){setError(e instanceof Error?e.message:"Could not delete automation.");}
  }
  const requiredAudience=trigger==="monthly_sponsor"||trigger==="monthly_promoter";
  return <div className="comm-two-column">
    <section className="comm-panel">
      <div className="comm-panel-header"><div><h2>New automation</h2>
        <p>Build a reusable trigger from a saved template.</p></div></div>
      <form className="comm-template-form" onSubmit={save}>
        <label className="field"><span className="field-label">Workflow name *</span>
          <input required minLength={2} maxLength={100} value={name}
            onChange={e=>setName(e.target.value)}
            placeholder="Monthly unpaid sponsor follow-up"/></label>
        <label className="field"><span className="field-label">Trigger *</span>
          <select aria-label="Automation trigger" value={trigger}
            onChange={e=>selectTrigger(e.target.value)}>
            {triggerOptions.map(([value,label])=>
              <option key={value} value={value}>{label}</option>)}
          </select></label>
        <div className="comm-form-grid">
          <label className="field"><span className="field-label">Recipients *</span>
            <select aria-label="Automation audience" value={audience}
              disabled={requiredAudience}
              onChange={e=>setAudience(e.target.value as Audience)}>
              {audienceOptions.map(([value,label])=>
                <option value={value} key={value}>{label}</option>)}
            </select></label>
          <label className="field"><span className="field-label">Segment *</span>
            <select aria-label="Automation segment" value={segment}
              disabled={requiredAudience}
              onChange={e=>setSegment(e.target.value as Segment)}>
              {segmentOptions.map(([value,label])=>
                <option value={value} key={value}>{label}</option>)}
            </select></label>
        </div>
        <label className="field"><span className="field-label">Message template *</span>
          <select required aria-label="Automation template" value={templateId}
            onChange={e=>setTemplateId(e.target.value)}>
            <option value="">Select saved template</option>
            {templates.map(t=><option key={t.id} value={t.id}>
              {t.name} · {t.channel==="whatsapp"?"WhatsApp":"Email"}
            </option>)}
          </select></label>
        {!templates.length&&<p className="comm-muted">
          Save a template first, then return here to configure its trigger.</p>}
        {error&&<p role="alert" className="form-error">{error}</p>}
        {notice&&<p role="status" className="form-success">{notice}</p>}
        <div className="comm-actions">
          <span className="comm-muted">Definitions are saved inactive.</span>
          <button type="submit" className="btn btn-primary" disabled={saving||!templateId}>
            {saving?"Saving…":"Save automation"}
          </button>
        </div>
      </form>
    </section>
    <section className="comm-panel">
      <div className="comm-panel-header"><h2>Saved workflows</h2>
        <span className="comm-muted">{rules.length+1} workflows</span></div>
      <div className="comm-stack">
        <OtpCopyEditor/>
        {!rules.length&&<p className="comm-muted">
          No additional workflows yet. Configure a trigger to add one.</p>}
        {rules.map(r=><article className="comm-list-card" key={r.id}>
            <div className="comm-list-card-text"><strong>{r.name}</strong>
              <span>{triggerOptions.find(x=>x[0]===r.trigger_kind)?.[1]??r.trigger_kind}</span>
              <p>{r.audience} · {r.segment}</p>
              <span className="comm-inactive-tag">Inactive · delivery not connected</span>
            </div>
            <button type="button" className="comm-text-button"
              onClick={()=>remove(r)}>Remove</button>
          </article>)}
      </div>
      <p className="comm-muted comm-history-footnote">
        Monthly sponsor and promoter reminders are queued through Saasyto
        on the configured 5th/20th IST dates only when both the Foundation
        automation switch and the approved Saasyto worker are enabled.
        Saved custom trigger definitions remain inactive until separately reviewed.
      </p>
    </section>
  </div>;
}
