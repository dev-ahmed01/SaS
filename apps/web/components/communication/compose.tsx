"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  apiGet, apiWrite, audienceOptions, categoryOptions, istLocalInput, segmentOptions,
} from "./types";
import type { Audience, Campaign, Category, Channel, Preview, Segment, Template } from "./types";

function renderPreview(body:string,name:string){
  return body.replaceAll("{{name}}",name||"Sponsor name")
    .replaceAll("{{month}}",new Intl.DateTimeFormat("en-IN",{
      month:"long",year:"numeric",timeZone:"Asia/Kolkata",
    }).format(new Date()))
    .replaceAll("{{amount}}","₹250");
}

export function CommunicationCompose({onSaved}:{onSaved:()=>void}){
  const [title,setTitle]=useState("");
  const [channel,setChannel]=useState<Channel>("whatsapp");
  const [audience,setAudience]=useState<Audience>("prospects");
  const [segment,setSegment]=useState<Segment>("active");
  const [category,setCategory]=useState<Category>("update");
  const [selectedTemplate,setSelectedTemplate]=useState("");
  const [templates,setTemplates]=useState<Template[]>([]);
  const [subject,setSubject]=useState("");
  const [body,setBody]=useState("");
  const [providerTemplate,setProviderTemplate]=useState("");
  const [timing,setTiming]=useState<"draft"|"planned">("draft");
  const [plannedFor,setPlannedFor]=useState(()=>istLocalInput(new Date(Date.now()+3600000)));
  const [preview,setPreview]=useState<Preview|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [saving,setSaving]=useState(false);
  const requestId=useRef<string|null>(null);

  useEffect(()=>{
    apiGet<Template[]>("/templates").then(setTemplates).catch(()=>{
      setError("Saved templates could not be loaded.");
    });
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setPreview(null);
    const query=new URLSearchParams({audience,segment,channel,category});
    fetch("/api/admin/communication/audience?"+query.toString(),{
      cache:"no-store",signal:controller.signal,
    }).then(async res=>{
      if(!res.ok)throw Error("Preview unavailable");
      return await res.json() as Preview;
    }).then(data=>{if(!controller.signal.aborted)setPreview(data);})
      .catch(()=>{if(!controller.signal.aborted)setPreview(null);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[audience,segment,channel,category,refresh]);

  function invalidate(){requestId.current=null;setError("");setNotice("");}
  function chooseTemplate(id:string){
    setSelectedTemplate(id);invalidate();
    const template=templates.find(x=>x.id===id);
    if(template){
      setCategory(template.category);
      setBody(template.body);setSubject(template.subject??"");
      setProviderTemplate(template.provider_template_id??"");
    }
  }
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(saving)return;
    if(!title.trim()||body.trim().length<3){
      setError("Enter a title and message body.");return;
    }
    if(category==="reminder"&&segment==="inactive"){
      setError("Inactive contacts cannot receive reminders.");return;
    }
    if(timing==="planned"&&!plannedFor){
      setError("Choose a date and time in IST.");return;
    }
    setSaving(true);setError("");setNotice("");
    if(!requestId.current)requestId.current=crypto.randomUUID();
    try{
      const schedule=timing==="planned"?new Date(plannedFor+":00+05:30").toISOString():null;
      const campaign=await apiWrite<Campaign>("/campaigns","POST",{
        request_id:requestId.current,title:title.trim(),template_id:selectedTemplate||null,
        channel,audience,segment,category,
        subject:channel==="email"?subject.trim():null,body:body.trim(),
        provider_template_id:providerTemplate.trim()||null,planned_for:schedule,
      });
      requestId.current=null;
      setNotice((campaign.status==="scheduled"?"Scheduled plan":"Draft")+" saved. "
        +"No message has been sent or queued for delivery.");
      setRefresh(x=>x+1);
      onSaved();
    }catch(e){setError(e instanceof Error?e.message:"Unable to save message.");}
    finally{setSaving(false);}
  }
  const selectedName=preview?.sample_names[0]||"Recipient";
  return <div className="communication-compose-layout">
    <section className="comm-panel" aria-label="Compose message">
      <div className="comm-panel-header">
        <div><h2>New message</h2><p>Choose who, what, and when.</p></div>
        <span className="comm-channel-tag">Draft workspace</span>
      </div>
      <form onSubmit={submit}>
        <div className="comm-form-section">
          <h3>Audience</h3>
          <div className="comm-channel-switch" role="group" aria-label="Message channel">
            <button type="button" className={channel==="whatsapp"?"selected":""}
              aria-pressed={channel==="whatsapp"}
              onClick={()=>{setChannel("whatsapp");setSelectedTemplate("");setSubject("");invalidate();}}>
              WhatsApp</button>
            <button type="button" className={channel==="email"?"selected":""}
              aria-pressed={channel==="email"}
              onClick={()=>{setChannel("email");setSelectedTemplate("");invalidate();}}>
              Email</button>
          </div>
          <div className="comm-form-grid">
            <label className="field"><span className="field-label">Recipients *</span>
              <select aria-label="Recipients" value={audience}
                onChange={e=>{setAudience(e.target.value as Audience);invalidate();}}>
                {audienceOptions.map(([value,label])=>
                  <option value={value} key={value}>{label}</option>)}
              </select></label>
            <label className="field"><span className="field-label">Segment *</span>
              <select aria-label="Segment" value={segment}
                onChange={e=>{setSegment(e.target.value as Segment);invalidate();}}>
                {segmentOptions.map(([value,label])=>
                  <option value={value} key={value}>{label}</option>)}
              </select></label>
          </div>
        </div>
        <div className="comm-form-section">
          <h3>Message</h3>
          <div className="comm-form-grid">
            <label className="field"><span className="field-label">Campaign name *</span>
              <input aria-label="Campaign name" required maxLength={120}
                placeholder="October community update" value={title}
                onChange={e=>{setTitle(e.target.value);invalidate();}}/></label>
            <label className="field"><span className="field-label">Message type *</span>
              <select aria-label="Message type" value={category}
                onChange={e=>{setCategory(e.target.value as Category);invalidate();}}>
                {categoryOptions.map(([value,label])=>
                  <option key={value} value={value}>{label}</option>)}
              </select></label>
            <label className="field comm-full"><span className="field-label">Use template</span>
              <select aria-label="Use template" value={selectedTemplate}
                onChange={e=>chooseTemplate(e.target.value)}>
                <option value="">Write a new message</option>
                {templates.filter(x=>x.channel===channel).map(template=>
                  <option key={template.id} value={template.id}>{template.name}</option>)}
              </select></label>
            {channel==="email"&&<label className="field comm-full">
              <span className="field-label">Email subject *</span>
              <input required aria-label="Email subject" maxLength={160}
                value={subject} onChange={e=>{setSubject(e.target.value);invalidate();}}
                placeholder="A message from Emlen Foundation"/></label>}
            <label className="field comm-full"><span className="field-label">Message *</span>
              <textarea aria-label="Message body" required rows={7} maxLength={1200}
                value={body} onChange={e=>{setBody(e.target.value);invalidate();}}
                placeholder={"Assalamu Alaikum {{name}},\n\nWe have an update to share with you."}/>
              <span className="comm-muted">Use {"{{name}}"} or {"{{month}}"} for a preview.</span>
            </label>
            {channel==="whatsapp"&&<label className="field comm-full">
              <span className="field-label">Approved WhatsApp template ID</span>
              <input aria-label="Approved WhatsApp template ID"
                maxLength={160} value={providerTemplate}
                onChange={e=>{setProviderTemplate(e.target.value);invalidate();}}
                placeholder="Provider-approved template reference"/>
            </label>}
          </div>
        </div>
        <div className="comm-form-section">
          <h3>Timing</h3>
          <div className="comm-radio-options">
            <label><input type="radio" name="timing" checked={timing==="draft"}
              onChange={()=>{setTiming("draft");invalidate();}}/> Save draft</label>
            <label><input type="radio" name="timing" checked={timing==="planned"}
              onChange={()=>{setTiming("planned");invalidate();}}/> Plan for later</label>
          </div>
          {timing==="planned"&&<label className="field comm-scheduled-at">
            <span className="field-label">Planned date and time (IST) *</span>
            <input required type="datetime-local" aria-label="Planned date and time (IST)"
              min={istLocalInput(new Date())} value={plannedFor}
              onChange={e=>{setPlannedFor(e.target.value);invalidate();}}/>
          </label>}
        </div>
        {error&&<p className="form-error" role="alert">{error}</p>}
        {notice&&<p className="form-success" role="status">{notice}</p>}
        <div className="comm-actions">
          <span className="comm-muted">Saving does not send messages.</span>
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving?"Saving…":timing==="planned"?"Save scheduled plan":"Save draft"}
          </button>
        </div>
      </form>
    </section>

    <aside className="comm-preview-column" aria-label="Message review">
      <section className="comm-panel comm-preview-audience">
        <div className="comm-panel-header"><h2>Audience preview</h2>
          <button type="button" className="comm-text-button"
            onClick={()=>setRefresh(x=>x+1)}>Refresh</button></div>
        <div className="comm-audience-metrics">
          <div><span>Matching</span><strong>{loading?"—":preview?.candidate_count??"—"}</strong></div>
          <div><span>Consent-ready</span><strong>{loading?"—":preview?.eligible_count??"—"}</strong></div>
          <div><span>Excluded</span><strong>{loading?"—":preview?.suppressed_count??"—"}</strong></div>
        </div>
        <p className="comm-muted">{preview?.notice??"Loading current audience…"}</p>
        {!!preview?.sample_names.length&&<div className="comm-sample">
          <span>Sample recipients</span>
          {preview.sample_names.map(name=><p key={name}>{name}</p>)}
        </div>}
      </section>
      <section className="comm-panel">
        <div className="comm-panel-header"><h2>Message preview</h2>
          <span className="comm-channel-tag">{channel==="whatsapp"?"WhatsApp":"Email"}</span>
        </div>
        {channel==="email"&&subject&&<strong className="comm-subject-preview">{subject}</strong>}
        <div className="comm-message-preview">
          {body?<p>{renderPreview(body,selectedName)}</p>
            :<p className="comm-placeholder">Your message preview will appear here.</p>}
        </div>
        <p className="comm-muted">Preview only · Delivery not activated.</p>
      </section>
    </aside>
  </div>;
}
