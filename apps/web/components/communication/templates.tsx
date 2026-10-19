"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiGet, apiWrite, categoryOptions } from "./types";
import type { Category, Channel, Template } from "./types";

export function CommunicationTemplates({onChanged=()=>{}}:{onChanged?:()=>void}){
  const [items,setItems]=useState<Template[]>([]);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  const [edit,setEdit]=useState<Template|null>(null);
  const [name,setName]=useState("");
  const [channel,setChannel]=useState<Channel>("whatsapp");
  const [category,setCategory]=useState<Category>("update");
  const [subject,setSubject]=useState("");
  const [body,setBody]=useState("");
  const [providerId,setProviderId]=useState("");
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [saving,setSaving]=useState(false);

  useEffect(()=>{
    setLoading(true);
    apiGet<Template[]>("/templates").then(setItems)
      .catch(()=>setError("Unable to load templates."))
      .finally(()=>setLoading(false));
  },[revision]);
  function reset(){
    setEdit(null);setName("");setChannel("whatsapp");
    setCategory("update");setSubject("");setBody("");setProviderId("");
    setError("");
  }
  function start(row:Template){
    setEdit(row);setName(row.name);setChannel(row.channel);
    setCategory(row.category);setSubject(row.subject??"");
    setBody(row.body);setProviderId(row.provider_template_id??"");
    setError("");setNotice("");
    document.getElementById("comm-template-name")?.focus();
  }
  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(saving)return;
    setSaving(true);setError("");setNotice("");
    try{
      await apiWrite("/templates"+(edit?"/"+edit.id:""),edit?"PATCH":"POST",{
        ...(edit?{version:edit.version}:{}),name,channel,category,body,
        subject:channel==="email"?subject||null:null,
        provider_template_id:channel==="whatsapp"?providerId||null:null,
      });
      setNotice(edit?"Template updated.":"Template saved.");
      reset();setRevision(x=>x+1);onChanged();
    }catch(e){setError(e instanceof Error?e.message:"Could not save template.");}
    finally{setSaving(false);}
  }
  async function remove(row:Template){
    if(saving)return;
    if(!window.confirm("Archive "+row.name+"? Existing campaign copies remain unchanged."))return;
    setSaving(true);setError("");setNotice("");
    try{
      await apiWrite("/templates/"+row.id+"?version="+row.version,"DELETE");
      if(edit?.id===row.id)reset();
      setRevision(x=>x+1);onChanged();
      setNotice("Template archived.");
    }catch(e){setError(e instanceof Error?e.message:"Could not archive template.");}
    finally{setSaving(false);}
  }
  return <div className="comm-two-column">
    <section className="comm-panel">
      <div className="comm-panel-header"><div><h2>{edit?"Edit template":"New template"}</h2>
        <p>Save once, reuse across campaigns.</p></div></div>
      <form onSubmit={save} className="comm-template-form">
        <label className="field"><span className="field-label">Template name *</span>
          <input id="comm-template-name" required minLength={2} maxLength={100}
            value={name} onChange={e=>setName(e.target.value)}
            placeholder="Monthly Foundation update"/></label>
        <div className="comm-form-grid">
          <label className="field"><span className="field-label">Channel *</span>
            <select aria-label="Template channel" value={channel}
              onChange={e=>setChannel(e.target.value as Channel)}>
              <option value="whatsapp">WhatsApp</option><option value="email">Email</option>
            </select></label>
          <label className="field"><span className="field-label">Type *</span>
            <select aria-label="Template type" value={category}
              onChange={e=>setCategory(e.target.value as Category)}>
              {categoryOptions.map(([val,label])=>
                <option key={val} value={val}>{label}</option>)}
            </select></label>
        </div>
        {channel==="email"&&<label className="field">
          <span className="field-label">Email subject *</span>
          <input required maxLength={160} value={subject}
            onChange={e=>setSubject(e.target.value)}/></label>}
        <label className="field"><span className="field-label">Message *</span>
          <textarea required rows={6} minLength={3} maxLength={1200}
            value={body} onChange={e=>setBody(e.target.value)}
            placeholder={"Assalamu Alaikum {{name}},\n\nYour Foundation update…"}/>
        </label>
        {channel==="whatsapp"&&<label className="field">
          <span className="field-label">Provider-approved template ID</span>
          <input maxLength={160} value={providerId} onChange={e=>setProviderId(e.target.value)}
            placeholder="Approved template identifier"/></label>}
        {error&&<p className="form-error" role="alert">{error}</p>}
        {notice&&<p className="form-success" role="status">{notice}</p>}
        <div className="comm-actions">
          {edit&&<button className="btn btn-secondary" type="button" disabled={saving}
            onClick={reset}>Cancel</button>}
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving?"Saving…":edit?"Save changes":"Save template"}
          </button>
        </div>
      </form>
    </section>
    <section className="comm-panel">
      <div className="comm-panel-header"><h2>Saved templates</h2>
        <span className="comm-muted">{items.length} templates</span></div>
      {loading?<p role="status">Loading…</p>:items.length===0?
        <p className="comm-empty">No templates yet. Create one to reuse it when composing.</p>:
        <div className="comm-stack">
          {items.map(t=><article className="comm-list-card" key={t.id}>
            <div className="comm-list-card-text"><strong>{t.name}</strong>
              <span>{t.channel==="whatsapp"?"WhatsApp":"Email"} · {t.category.replace("_"," ")}</span>
              <p>{t.body}</p>
            </div>
            <div className="comm-card-actions">
              <button type="button" className="btn btn-secondary" onClick={()=>start(t)}>Edit</button>
              <button type="button" className="comm-text-button" disabled={saving}
                onClick={()=>remove(t)}>Archive</button>
            </div>
          </article>)}
        </div>}
    </section>
  </div>;
}
