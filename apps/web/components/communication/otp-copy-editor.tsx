"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { apiGet, apiWrite } from "./types";

type OtpCopy={body:string;version:number};
const defaultPreview={
  "{{name}}":"Example Sponsor",
  "{{code}}":"••••",
  "{{sponsorship}}":"₹500 per month",
  "{{sponsorship_amount}}":"₹500",
  "{{sponsorship_units}}":"2",
};
function sample(body:string){
  return body.replace(/{{\s*(name|code|sponsorship|sponsorship_amount|sponsorship_units)\s*}}/g,
    value=>defaultPreview[value.replace(/\s/g,"") as keyof typeof defaultPreview]??value);
}

export function OtpCopyEditor(){
  const [body,setBody]=useState("");
  const [version,setVersion]=useState(0);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [preview,setPreview]=useState(false);
  const [expanded,setExpanded]=useState(false);
  const field=useRef<HTMLTextAreaElement|null>(null);

  useEffect(()=>{
    apiGet<OtpCopy>("/otp-template").then(data=>{
      setBody(data.body);setVersion(data.version);
    }).catch(()=>setError("Could not load activation message."))
      .finally(()=>setLoading(false));
  },[]);
  function insert(token:string){
    const input=field.current;
    const start=input?.selectionStart??body.length;
    const end=input?.selectionEnd??body.length;
    setBody(body.slice(0,start)+token+body.slice(end));
    setError("");setNotice("");
    requestAnimationFrame(()=>{
      input?.focus();input?.setSelectionRange(start+token.length,start+token.length);
    });
  }
  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(saving)return;
    if(!/{{\s*code\s*}}/.test(body)||!/{{\s*name\s*}}/.test(body)||
      !/{{\s*(sponsorship|sponsorship_amount)\s*}}/.test(body)){
      setError("Include Name, Sponsorship or Amount, and Code.");return;
    }
    setSaving(true);setError("");setNotice("");
    try{
      const result=await apiWrite<OtpCopy>("/otp-template","POST",{body,version});
      setBody(result.body);setVersion(result.version);
      setNotice("Activation message saved.");
    }catch(e){setError(e instanceof Error?e.message:"Could not save activation message.");}
    finally{setSaving(false);}
  }
  return <article className="comm-list-card comm-activation-workflow"
    aria-label="Sponsorship activation workflow">
    <div className="comm-list-card-text">
      <strong>Sponsorship activation</strong>
      <span>WhatsApp · Admin-requested verification</span>
      <p>Authentication message sent when an Admin verifies a new sponsor.</p>
    </div>
    <div className="comm-card-actions">
      <button type="button" className="btn btn-secondary"
        aria-expanded={expanded} onClick={()=>{
          setExpanded(value=>!value);setPreview(false);
        }}>{expanded?"Close":"Edit message"}</button>
    </div>
    {expanded&&<div className="comm-activation-editor">
      <div className="comm-activation-editor-heading">
        <span className="comm-muted">This message is separate from bulk campaigns.</span>
        <button type="button" className="btn btn-secondary"
          aria-pressed={preview} onClick={()=>setPreview(value=>!value)}>
          {preview?"Back to editor":"Preview"}
        </button>
      </div>
      {loading?<p role="status">Loading message…</p>:<form onSubmit={save}>
        {preview?<div className="comm-otp-copy-preview" aria-label="Example activation message">
          {sample(body)}
        </div>:<>
          <label className="field">
            <span className="field-label">WhatsApp activation message *</span>
            <textarea ref={field} required rows={8} minLength={30} maxLength={1200}
              value={body} onChange={e=>{setBody(e.target.value);setNotice("");}}
              aria-label="WhatsApp activation message"/>
          </label>
          <div className="comm-personalization" aria-label="Activation message variables">
            <span className="comm-personalization-label">Insert details</span>
            <div className="comm-personalization-actions">
              {([
                ["Name","{{name}}"],["Sponsorship","{{sponsorship}}"],
                ["Amount","{{sponsorship_amount}}"],
                ["Verification code","{{code}}"],
              ] as const).map(([label,token])=>
                <button key={token} type="button" className="comm-personalization-chip"
                  onClick={()=>insert(token)}>{label}</button>
              )}
            </div>
          </div>
        </>}
        {error&&<p className="form-error" role="alert">{error}</p>}
        {notice&&<p className="form-success" role="status">{notice}</p>}
        <div className="comm-actions">
          <button className="btn btn-primary" type="submit" disabled={saving||preview}>
            {saving?"Saving…":"Save activation message"}
          </button>
        </div>
      </form>}
    </div>}
  </article>;
}
