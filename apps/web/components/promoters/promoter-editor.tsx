"use client";

import { FormEvent, useState } from "react";
import type { Promoter } from "./promoter-types";
import { csrfToken } from "./promoter-types";

const countryCodes=[
  ["India","+91"],["UAE","+971"],["Saudi Arabia","+966"],["USA / Canada","+1"],
  ["United Kingdom","+44"],["Australia","+61"],["Singapore","+65"],["Qatar","+974"],
  ["Oman","+968"],["Bahrain","+973"],["Kuwait","+965"],["Nepal","+977"],
  ["Bangladesh","+880"],["Pakistan","+92"],
];
type Values={
  first:string;last:string;code:string;mobile:string;email:string;
  city:string;occupation:string;whatsapp_opt_in:boolean;
};
function starting(initial?:Promoter):Values{
  const number=initial?.mobile_number??"";
  const code=countryCodes.slice().sort((a,b)=>b[1].length-a[1].length)
    .find(item=>number.startsWith(item[1]))?.[1]??"+91";
  const first=initial?.first_name??initial?.full_name.split(" ")[0]??"";
  const last=initial?.last_name??initial?.full_name.split(" ").slice(1).join(" ")??"";
  return {
    first,last,code,mobile:number?number.slice(code.length):"",email:initial?.email??"",
    city:initial?.area_city??"",occupation:initial?.occupation??"",
    whatsapp_opt_in:initial?.whatsapp_opt_in??false,
  };
}
export function PromoterEditor({initial,onSaved,onCancel}:{
  initial?:Promoter;onSaved:(saved:Promoter)=>void;onCancel?:()=>void;
}){
  const [form,setForm]=useState<Values>(()=>starting(initial));
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const edit=Boolean(initial);
  function set<K extends keyof Values>(key:K,value:Values[K]){
    setForm(old=>({...old,[key]:value}));setError("");
  }
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving)return;
    const first=form.first.trim(),last=form.last.trim();
    const mobile=form.code+form.mobile.replace(/[\s()-]/g,"");
    if(first.length<2){setError("Enter a first name with at least two characters.");return;}
    if(!/^\+[1-9]\d{7,14}$/.test(mobile)){
      setError("Enter a valid mobile number and country code.");return;
    }
    setSaving(true);setError("");
    try{
      const csrf=await csrfToken();
      const payload={
        full_name:[first,last].filter(Boolean).join(" "),
        first_name:first,last_name:last||null,
        mobile_number:mobile,whatsapp_number:mobile,
        email:form.email.trim()||null,
        area_city:form.city.trim(),occupation:form.occupation.trim()||null,
        whatsapp_opt_in:form.whatsapp_opt_in,
        ...(initial?{version:initial.version}:{}),
      };
      const res=await fetch("/api/admin/promoters"+(initial?"/"+initial.id:""),{
        method:initial?"PATCH":"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify(payload),
      });
      if(!res.ok){
        setError(res.status===409?"Mobile number exists or promoter was updated elsewhere."
          :res.status===422?"Review the name, phone and email fields."
          :"Promoter could not be saved.");
        return;
      }
      const updated=await res.json() as Promoter;
      onSaved(updated);
    }catch{setError("Connection problem. Save could not be confirmed.");}
    finally{setSaving(false);}
  }
  return <section className="prospect-form-panel promoter-form-panel"
    aria-label={edit?"Edit personal details":"Add Promoter"}>
    <div className="prospect-form-intro">
      <h2>{edit?"Edit personal details":"New promoter"}</h2>
      <p>Promoter contact information</p>
    </div>
    <form onSubmit={submit}>
      <div className="prospect-form-rows">
        <div className="prospect-field-row two">
          <label className="field"><span className="field-label">First Name *</span>
            <input required minLength={2} maxLength={80} autoComplete="given-name"
              placeholder="First name" value={form.first}
              onChange={e=>set("first",e.target.value)}/></label>
          <label className="field"><span className="field-label">Last Name</span>
            <input maxLength={80} autoComplete="family-name" placeholder="Last name"
              value={form.last} onChange={e=>set("last",e.target.value)}/></label>
        </div>
        <div className="prospect-field-row contact">
          <label className="field"><span className="field-label">Country Code</span>
            <select aria-label="Country Code" value={form.code}
              onChange={e=>set("code",e.target.value)}>
              {countryCodes.map(([country,code])=>
                <option key={code} value={code}>{code} · {country}</option>)}
            </select></label>
          <label className="field"><span className="field-label">Mobile (WhatsApp) *</span>
            <input type="tel" required inputMode="tel" autoComplete="tel-national"
              value={form.mobile} onChange={e=>set("mobile",e.target.value)}
              placeholder="98765 43210"/></label>
          <label className="field"><span className="field-label">Email</span>
            <input type="email" maxLength={320} autoComplete="email"
              value={form.email} onChange={e=>set("email",e.target.value)}
              placeholder="name@example.com"/></label>
        </div>
        <div className="prospect-field-row two">
          <label className="field"><span className="field-label">City</span>
            <input maxLength={120} autoComplete="address-level2" value={form.city}
              onChange={e=>set("city",e.target.value)} placeholder="City"/></label>
          <label className="field"><span className="field-label">Occupation</span>
            <input maxLength={120} value={form.occupation}
              onChange={e=>set("occupation",e.target.value)} placeholder="Occupation"/></label>
        </div>
        {!edit&&<label className="prospect-consent"><input type="checkbox"
          checked={form.whatsapp_opt_in}
          onChange={e=>set("whatsapp_opt_in",e.target.checked)}/>
          <span>WhatsApp communication consent recorded</span>
        </label>}
      </div>
      {error&&<p role="alert" className="form-error">{error}</p>}
      <div className="form-actions prospect-form-actions">
        {onCancel&&<button type="button" className="btn btn-secondary"
          onClick={onCancel} disabled={saving}>Cancel</button>}
        {!edit&&<button type="button" className="btn btn-secondary"
          onClick={()=>setForm(starting())} disabled={saving}>Clear</button>}
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving?"Saving…":edit?"Save Changes":"Add Promoter"}
        </button>
      </div>
    </form>
  </section>;
}
