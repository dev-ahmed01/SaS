"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  apiGet, apiWrite, audienceOptions, categoryOptions, istLocalInput, segmentOptions,
} from "./types";
import type { Audience, Campaign, Category, Channel, Preview, Segment, Template } from "./types";
import { PersonalizationTokens } from "./personalization";

export function CommunicationCompose({onSaved}:{onSaved:()=>void}){
  const router=useRouter();
  const [title,setTitle]=useState("");
  const [channel,setChannel]=useState<Channel>("whatsapp");
  const [audience,setAudience]=useState<Audience>("prospects");
  const [segment,setSegment]=useState<Segment>("active");
  const [category,setCategory]=useState<Category>("update");
  const [selectedTemplate,setSelectedTemplate]=useState("");
  const [templates,setTemplates]=useState<Template[]>([]);
  const [audiencePreview,setAudiencePreview]=useState<Preview|null>(null);
  const [subject,setSubject]=useState("");
  const [body,setBody]=useState("");
  const [timing,setTiming]=useState<"now"|"planned">("now");
  const [plannedFor,setPlannedFor]=useState(()=>istLocalInput(new Date(Date.now()+3600000)));
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [saving,setSaving]=useState(false);
  const requestId=useRef<string|null>(null);
  const messageInput=useRef<HTMLTextAreaElement|null>(null);

  useEffect(()=>{
    apiGet<Template[]>("/templates").then(setTemplates).catch(()=>{
      setError("Saved templates could not be loaded.");
    });
  },[]);
  useEffect(()=>{
    let active=true;
    setAudiencePreview(null);
    const params=new URLSearchParams({audience,segment,channel,category});
    apiGet<Preview>("/audience?"+params.toString())
      .then(result=>{if(active)setAudiencePreview(result);})
      .catch(()=>{if(active)setAudiencePreview(null);});
    return()=>{active=false;};
  },[audience,segment,channel,category]);
  function invalidate(){requestId.current=null;setError("");setNotice("");}
  function insertPersonalization(token:string){
    const input=messageInput.current;
    const start=input?.selectionStart??body.length;
    const end=input?.selectionEnd??body.length;
    setBody(body.slice(0,start)+token+body.slice(end));
    invalidate();
    requestAnimationFrame(()=>{
      input?.focus();input?.setSelectionRange(start+token.length,start+token.length);
    });
  }
  function chooseTemplate(id:string){
    setSelectedTemplate(id);invalidate();
    const template=templates.find(x=>x.id===id);
    if(template){
      setCategory(template.category);
      setBody(template.body);setSubject(template.subject??"");
    }
  }
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(saving)return;
    if(!title.trim()||body.trim().length<3){
      setError("Enter a title and message body.");return;
    }
    if(audience!=="prospects"&&
      /{{\s*(sponsorship|sponsorship_amount|sponsorship_units)\s*}}/.test(body)){
      setError("Sponsorship personalization is for Prospects only.");return;
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
        provider_template_id:selectedTemplate
          ?templates.find(item=>item.id===selectedTemplate)?.provider_template_id??null
          :null,planned_for:schedule,
      });
      requestId.current=null;
      onSaved();
      router.push("/communication/campaigns#campaign-"+campaign.id);
    }catch(e){setError(e instanceof Error?e.message:"Unable to save message.");}
    finally{setSaving(false);}
  }
  return <div className="communication-compose-layout">
    <section className="comm-panel" aria-label="Compose message">
      <div className="comm-panel-header">
        <h2>New message</h2>
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
          <div className="comm-audience-count" role="status">
            {audiencePreview
              ? <><strong>{audiencePreview.eligible_count}</strong> eligible recipients</>
              : "Checking recipients…"}
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
              <textarea ref={messageInput} aria-label="Message body" required rows={7} maxLength={1200}
                value={body} onChange={e=>{setBody(e.target.value);invalidate();}}
                placeholder={"Assalamu Alaikum {{name}},\n\nWe have an update to share with you."}/>
              <PersonalizationTokens onInsert={insertPersonalization}
                showSponsorship={audience==="prospects"}/>
            </label>
          </div>
        </div>
        <div className="comm-form-section">
          <h3>Timing</h3>
          <div className="comm-radio-options">
            <label><input type="radio" name="timing" checked={timing==="now"}
              onChange={()=>{setTiming("now");invalidate();}}/> Review & send</label>
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
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving?"Saving…":timing==="planned"?"Plan for later":"Continue to recipient review"}
          </button>
        </div>
      </form>
    </section>

  </div>;
}
