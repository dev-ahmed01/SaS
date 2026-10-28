"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Prospect } from "./prospects-types";

type Values = {
  first_name:string;last_name:string;country_code:string;phone:string;
  email:string;city:string;tokens:string;start_month:string;
  promoter_id:string;whatsapp_opt_in:boolean;
};
type PromoterOption = {id:string;full_name:string;is_active:boolean};

const codes=[["India","+91"],["UAE","+971"],["Saudi Arabia","+966"],["USA / Canada","+1"],
  ["United Kingdom","+44"],["Australia","+61"],["Singapore","+65"],["Qatar","+974"],
  ["Oman","+968"],["Bahrain","+973"],["Kuwait","+965"],["Pakistan","+92"],
  ["Bangladesh","+880"],["Nepal","+977"]];
const sortedCodes=[...codes].sort((a,b)=>b[1].length-a[1].length);
function parts(value:string):[string,string]{
  const cleaned=value.replace(/[\s-]/g,"");
  const entry=sortedCodes.find(([,code])=>cleaned.startsWith(code));
  return entry?[entry[1],cleaned.slice(entry[1].length)]:["+91",cleaned.replace(/^\+91/,"")];
}
function monthNow():string {
  const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit"})
    .formatToParts(new Date());
  return (parts.find(p=>p.type==="year")?.value??"2026")+"-"+(parts.find(p=>p.type==="month")?.value??"01");
}
function monthOptions(){
  const [year,month]=monthNow().split("-").map(Number);
  return Array.from({length:6},(_,i)=>{
    const date=new Date(Date.UTC(year,month-1+i,1));
    const value=date.toISOString().slice(0,7);
    const label=new Intl.DateTimeFormat("en-IN",{month:"long",year:"numeric",timeZone:"UTC"}).format(date);
    return {value,label};
  });
}
const months=monthOptions();
const tokenChoices=[...Array.from({length:40},(_,index)=>index+1),50,75,100];
const formatRupees=(amount:number)=>amount.toLocaleString("en-IN",{
  style:"currency",currency:"INR",maximumFractionDigits:0,
});
function initialValues(initial?:Prospect):Values {
  const [code,phone]=parts(initial?.mobile_number??"");
  const name=initial?.first_name??initial?.full_name.split(" ")[0]??"";
  const last=initial?.last_name??initial?.full_name.split(" ").slice(1).join(" ")??"";
  return {
    first_name:name,last_name:last,country_code:code,phone,email:initial?.email??"",
    city:initial?.area_city??"",
    tokens:String((initial?.monthly_contribution_paise??25000)/25000),
    start_month:initial?.start_month?.slice(0,7)??monthNow(),
    promoter_id:initial?.assigned_promoter_id??"",
    whatsapp_opt_in:initial?.whatsapp_opt_in??false,
  };
}
async function getCsrf():Promise<string>{
  const response=await fetch("/api/admin/session",{cache:"no-store"});
  if(!response.ok)throw Error("Your session has expired. Sign in again.");
  return (await response.json()).csrf_token;
}

export function ProspectEditor({initial,onSaved,onCancel}:{
  initial?:Prospect;onSaved:(saved:Prospect)=>void;onCancel?:()=>void;
}){
  const [values,setValues]=useState<Values>(()=>initialValues(initial));
  const [ready,setReady]=useState(Boolean(initial));
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [promoters,setPromoters]=useState<PromoterOption[]>([]);
  const [promotersError,setPromotersError]=useState("");
  const [current,setCurrent]=useState<Prospect|undefined>(initial);
  const requestId=useRef<string|null>(null);
  const isEdit=Boolean(initial);

  useEffect(()=>{
    let active=true;
    fetch("/api/admin/promoters?active=true&limit=100",{cache:"no-store"})
      .then(async r=>{if(!r.ok)throw Error();return r.json();})
      .then(data=>{if(active)setPromoters(data.items??[]);})
      .catch(()=>{if(active)setPromotersError("Promoters are unavailable. You can save without one.");});
    return ()=>{active=false;};
  },[]);
  useEffect(()=>{
    if(initial)return;
    let active=true;
    fetch("/api/admin/settings",{cache:"no-store"})
      .then(async r=>{if(!r.ok)throw Error();return r.json();})
      .then(data=>{
        if(!active)return;
        const amount=Number(data.default_contribution_paise);
        if(Number.isInteger(amount)&&amount>=25000&&amount%25000===0)
          setValues(v=>({...v,tokens:String(amount/25000)}));
        setReady(true);
      }).catch(()=>{if(active)setError("Could not load sponsorship defaults. Refresh this page.");});
    return ()=>{active=false;};
  },[initial]);
  function set<K extends keyof Values>(key:K,value:Values[K]){
    setValues(v=>({...v,[key]:value}));setError("");
  }
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving||!ready)return;
    const first=values.first_name.trim(),last=values.last_name.trim();
    const national=values.phone.replace(/[\s()-]/g,"");
    const mobile=values.country_code+national;
    const tokens=Number(values.tokens);
    if(first.length<2){setError("Enter a first name with at least two characters.");return;}
    if(!/^\+[1-9]\d{7,14}$/.test(mobile)){setError("Enter a valid WhatsApp/mobile number.");return;}
    if(!Number.isInteger(tokens)||tokens<1||tokens>40000){setError("Use a whole number of ₹250 sponsorship tokens.");return;}
    const fullName=[first,last].filter(Boolean).join(" ");
    setSaving(true);setError("");
    try{
      const csrf=await getCsrf();
      const body:Record<string,unknown>={
        full_name:fullName,first_name:first,last_name:last||null,
        mobile_number:mobile,whatsapp_number:mobile,
        email:values.email.trim()||null,area_city:values.city.trim(),
        whatsapp_opt_in:values.whatsapp_opt_in,
        monthly_contribution_paise:tokens*25000,
      };
      if(current){body.version=current.version;}
      else{
        requestId.current??=crypto.randomUUID();
        body.request_id=requestId.current;
        body.start_month=values.start_month+"-01";
        body.upi_ids=[];
      }
      const response=await fetch("/api/admin/prospects"+(current?"/"+current.id:""),{
        method:current?"PATCH":"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify(body),
      });
      if(!response.ok){
        const problem=await response.json().catch(()=>null) as {detail?:unknown}|null;
        const duplicate=typeof problem?.detail==="string"&&
          problem.detail.includes("Mobile number already registered");
        const message=duplicate
          ?"That mobile number already belongs to a prospect. Search for the existing record or enter a different number."
          :response.status===409?"The record changed. Reload before editing."
          :response.status===422?"Please check names, contact, tokens and email details."
          :"Could not save this prospect.";
        setError(message);return;
      }
      const saved=await response.json() as Prospect;
      setCurrent(saved);
      const oldId=initial?.assigned_promoter_id??"";
      const chosen=values.promoter_id;
      if(chosen!==oldId){
        const verb=chosen?"PUT":"DELETE";
        const promoterId=chosen||oldId;
        const assigned=await fetch("/api/admin/promoters/"+promoterId+"/sponsors/"+saved.id,{
          method:verb,credentials:"same-origin",
          headers:{"X-CSRF-Token":csrf,"If-Match":String(saved.version)},
        });
        if(!assigned.ok){
          setError("Prospect saved, but promoter assignment failed. Review the promoter and retry.");
          return;
        }
      }
      requestId.current=null;
      onSaved(saved);
    }catch{setError("Connection problem. The save could not be confirmed.");}
    finally{setSaving(false);}
  }


  return <section className="prospect-form-panel" aria-label={isEdit?"Edit personal details":"Add Prospect"}>
    <div className="prospect-form-intro">
      <h2>{isEdit?"Edit personal details":"New prospect"}</h2>
      <p>Contact and sponsorship information</p>
    </div>
    <form onSubmit={submit}>
      <div className="prospect-form-rows">
        <div className="prospect-field-row two">
          <label className="field"><span className="field-label">First Name *</span>
            <input required minLength={2} maxLength={80} autoComplete="given-name"
              value={values.first_name} onChange={e=>set("first_name",e.target.value)} placeholder="First name"/></label>
          <label className="field"><span className="field-label">Last Name</span>
            <input maxLength={80} autoComplete="family-name"
              value={values.last_name} onChange={e=>set("last_name",e.target.value)} placeholder="Last name"/></label>
        </div>
        <div className="prospect-field-row contact">
          <label className="field"><span className="field-label">Country Code</span>
            <select aria-label="Country Code" value={values.country_code} onChange={e=>set("country_code",e.target.value)}>
              {codes.map(([name,code])=><option value={code} key={code}>{code} · {name}</option>)}
            </select></label>
          <label className="field"><span className="field-label">Mobile (WhatsApp) *</span>
            <input required inputMode="tel" autoComplete="tel-national" value={values.phone}
              onChange={e=>set("phone",e.target.value)} placeholder="98765 43210"/></label>
          <label className="field"><span className="field-label">Email</span>
            <input type="email" autoComplete="email" maxLength={320} value={values.email}
              onChange={e=>set("email",e.target.value)} placeholder="name@example.com"/></label>
        </div>
        <div className="prospect-field-row one">
          <label className="field"><span className="field-label">City</span>
            <input maxLength={120} autoComplete="address-level2" value={values.city}
              onChange={e=>set("city",e.target.value)} placeholder="City"/></label>
        </div>
        <div className="prospect-field-row two">
          <label className="field"><span className="field-label">Sponsorship Tokens *</span>
            <select required aria-label="Sponsorship Tokens"
              value={tokenChoices.includes(Number(values.tokens))?values.tokens:"custom"}
              onChange={e=>set("tokens",e.target.value==="custom"?"101":e.target.value)}>
              {tokenChoices.map(count=><option value={count} key={count}>
                {formatRupees(count*250)} · {count} {count===1?"token":"tokens"}
              </option>)}
              <option value="custom">Custom quantity</option>
            </select>
            {!tokenChoices.includes(Number(values.tokens))&&
              <input type="number" min="1" max="40000" step="1" required
                aria-label="Custom sponsorship tokens" value={values.tokens}
                onChange={e=>set("tokens",e.target.value)}
                placeholder="Enter whole ₹250 tokens"/>}
            <span className="field-helper">{Number.isInteger(Number(values.tokens))&&Number(values.tokens)>0
              ?formatRupees(Number(values.tokens)*250)+" / month"
              :"Choose whole ₹250 tokens"}</span></label>
          <label className="field"><span className="field-label">Tentative Start (month)</span>
            <select value={values.start_month} disabled={isEdit}
              onChange={e=>set("start_month",e.target.value)} aria-label="Tentative Start">
              {months.some(m=>m.value===values.start_month)?null:
                <option value={values.start_month}>{values.start_month}</option>}
              {months.map(m=><option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            {isEdit&&<span className="field-helper">Start month is locked once registered to protect accounting history.</span>}</label>
        </div>
        <div className="prospect-field-row two">
          <label className="field"><span className="field-label">Select Promoter</span>
            <select aria-label="Select Promoter" value={values.promoter_id} onChange={e=>set("promoter_id",e.target.value)}>
              <option value="">Unassigned</option>
              {initial?.assigned_promoter_id&&!promoters.some(p=>p.id===initial.assigned_promoter_id)&&
                <option value={initial.assigned_promoter_id}>{initial.assigned_promoter_name??"Existing promoter"}</option>}
              {promoters.map(p=><option value={p.id} key={p.id}>{p.full_name}</option>)}
            </select></label>
        </div>
        {promotersError&&<p className="form-error" role="status">{promotersError}</p>}
        {!isEdit&&<label className="prospect-consent">
          <input type="checkbox" checked={values.whatsapp_opt_in}
            onChange={e=>set("whatsapp_opt_in",e.target.checked)}/>
          <span>I confirm the sponsor has explicitly agreed to receive WhatsApp reminders and updates. Record this permission once.</span>
        </label>}

      </div>
      {error&&<p className="form-error" role="alert">{error}</p>}
      <div className="form-actions prospect-form-actions">
        {onCancel&&<button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>Cancel</button>}
        {!isEdit&&<button type="button" className="btn btn-secondary" disabled={saving}
          onClick={()=>setValues(v=>({...initialValues(),tokens:v.tokens,start_month:v.start_month}))}>Clear</button>}
        <button className="btn btn-primary" type="submit" disabled={!ready||saving}>
          {saving?"Saving…":isEdit?"Save Changes":"Add Prospect"}
        </button>
      </div>
    </form>
  </section>;
}
