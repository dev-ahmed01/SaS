"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiGet, apiWrite, istDisplay } from "./types";
import type { Channel } from "./types";

type Kind="prospect"|"promoter";
type ConsentEvent={
  id:string;recipient_kind:Kind;recipient_id:string;channel:Channel;
  decision:"opted_in"|"opted_out";source:string;recorded_at:string;
};

export function ContactConsent({
  recipientKind,recipientId,legacyWhatsAppOptIn=false,allowGrant=true,onChanged,
}:{
  recipientKind:Kind;recipientId:string;legacyWhatsAppOptIn?:boolean;allowGrant?:boolean;
  onChanged?:()=>void;
}){
  const [events,setEvents]=useState<ConsentEvent[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [editing,setEditing]=useState<Channel|null>(null);
  const [decision,setDecision]=useState<"opted_in"|"opted_out">("opted_out");
  const [source,setSource]=useState("");
  const [proof,setProof]=useState("");
  const [verified,setVerified]=useState(false);
  const [saving,setSaving]=useState(false);
  const [revision,setRevision]=useState(0);

  useEffect(()=>{
    let active=true;
    setLoading(true);setError("");setEvents([]);
    const query=new URLSearchParams({
      recipient_kind:recipientKind,recipient_id:recipientId,
    });
    apiGet<ConsentEvent[]>("/consent-events?"+query)
      .then(rows=>{if(active)setEvents(rows);})
      .catch(()=>{if(active)setError("Consent status could not be loaded.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[recipientId,recipientKind,revision]);

  function open(channel:Channel){
    setEditing(channel);setDecision("opted_out");
    setSource("");setProof("");setVerified(false);setNotice("");setError("");
  }
  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!editing||saving||loading||(!allowGrant&&decision==="opted_in"))return;
    if(decision==="opted_in"&&(!proof.trim()||!verified)){
      setError("Confirm documented permission and provide its evidence reference.");return;
    }
    setSaving(true);setError("");setNotice("");
    try{
      await apiWrite<ConsentEvent>("/consent-events","POST",{
        recipient_kind:recipientKind,recipient_id:recipientId,
        channel:editing,decision,source:source.trim(),
        evidence_reference:decision==="opted_in"?proof.trim():null,
      });
      setNotice(decision==="opted_out"
        ?"Opt-out recorded. This channel will be suppressed."
        :"Documented permission recorded. No message was sent; review recipients in Communication before sending.");
      setEditing(null);setRevision(v=>v+1);onChanged?.();
    }catch(e){
      setError(e instanceof Error?e.message:"Could not record consent.");
    }finally{setSaving(false);}
  }
  function status(channel:Channel){
    const latest=events.find(event=>event.channel===channel);
    if(latest)return latest.decision==="opted_out"?"Opted out":"Admin-attested opt-in";
    if(channel==="whatsapp"&&legacyWhatsAppOptIn)return "Reminder checkbox only";
    return "No documented permission";
  }

  return <section className="crm-detail-card comm-consent-card" aria-label="Communication consent">
    <h2>Communication consent</h2>
    <div className="comm-consent-list">
      {(["whatsapp","email"] as Channel[]).map(channel=>{
        const latest=events.find(row=>row.channel===channel);
        return <div className="comm-consent-row" key={channel}>
          <div><strong>{channel==="whatsapp"?"WhatsApp":"Email"}</strong>
            <span>{loading?"Checking…":error&&!events.length?"Unavailable":status(channel)}</span>
            {latest&&<small>{istDisplay(latest.recorded_at)}</small>}
          </div>
          <button type="button" className="btn btn-secondary"
            disabled={loading||Boolean(error)||saving}
            onClick={()=>open(channel)}>
            Update
          </button>
        </div>;
      })}
    </div>
    {editing&&!loading&&<form className="comm-consent-form" onSubmit={save}>
      <h3>{editing==="whatsapp"?"WhatsApp":"Email"} permission</h3>
      <label className="field">
        <span className="field-label">Decision *</span>
        <select aria-label="Consent decision" value={decision} onChange={event=>{
          setDecision(event.target.value as "opted_in"|"opted_out");setVerified(false);
        }}>
          <option value="opted_out">Record opt-out</option>
          {allowGrant&&<option value="opted_in">Record documented opt-in</option>}
        </select>
      </label>
      <label className="field"><span className="field-label">Source *</span>
        <input aria-label="Consent source" required minLength={3} maxLength={80}
          value={source} onChange={event=>setSource(event.target.value)}
          placeholder="Recipient request or signed form"/>
      </label>
      {decision==="opted_in"&&<>
        <label className="field"><span className="field-label">Evidence reference *</span>
          <input aria-label="Consent evidence reference" required maxLength={160}
            value={proof} onChange={event=>setProof(event.target.value)}
            placeholder="Record or consent log identifier"/>
        </label>
        <label className="checkbox-field"><input type="checkbox" checked={verified}
          onChange={event=>setVerified(event.target.checked)}/>
          <span>I checked the recipient&apos;s explicit permission.</span>
        </label>
      </>}
      <div className="comm-consent-actions">
        <button type="button" className="btn btn-secondary" disabled={saving}
          onClick={()=>{setEditing(null);setError("");}}>Cancel</button>
        <button type="submit" className="btn btn-primary"
          disabled={saving||(decision==="opted_in"&&!verified)}>
          {saving?"Saving…":decision==="opted_out"?"Record opt-out":"Record opt-in"}
        </button>
      </div>
    </form>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
  </section>;
}
