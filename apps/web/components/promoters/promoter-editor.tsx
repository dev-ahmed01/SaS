"use client";

import { FormEvent, useState } from "react";
import type { Promoter } from "./promoter-types";
import { csrfToken, normalizedPhone } from "./promoter-types";

type FormValues = {
  full_name:string; mobile_number:string; whatsapp_number:string;
  whatsapp_opt_in:boolean;
};
const blank:FormValues={
  full_name:"",mobile_number:"",whatsapp_number:"",whatsapp_opt_in:false,
};
export function PromoterEditor({
  initial,onSaved,onCancel,
}:{
  initial?:Promoter;onSaved:()=>void;onCancel?:()=>void;
}){
  const [form,setForm]=useState<FormValues>(initial?{
    full_name:initial.full_name,mobile_number:initial.mobile_number,
    whatsapp_number:initial.whatsapp_number??"",whatsapp_opt_in:initial.whatsapp_opt_in,
  }:blank);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  function set<K extends keyof FormValues>(key:K,val:FormValues[K]){
    setForm(prev=>({...prev,[key]:val}));setError("");
  }
  async function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    if(saving)return;
    const mobile=normalizedPhone(form.mobile_number);
    const whatsapp=normalizedPhone(form.whatsapp_number);
    if(!mobile||(form.whatsapp_number.trim()&&!whatsapp)){
      setError("Enter a valid 10-digit Indian or international mobile number.");
      return;
    }
    setSaving(true);setError("");
    try{
      const csrf=await csrfToken();
      const payload={
        full_name:form.full_name.trim(),mobile_number:mobile,
        whatsapp_number:whatsapp,whatsapp_opt_in:form.whatsapp_opt_in,
        ...(initial?{version:initial.version}:{})
      };
      const response=await fetch(
        initial?"/api/admin/promoters/"+initial.id:"/api/admin/promoters",{
          method:initial?"PATCH":"POST",
          credentials:"same-origin",
          headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
          body:JSON.stringify(payload),
        }
      );
      if(!response.ok){
        setError(response.status===409
          ?"This phone is already registered, or the record changed. Refresh before retrying."
          :response.status===422
            ?"Please check the name and phone number."
            :"Unable to save. No change has been confirmed.");
        return;
      }
      if(!initial)setForm(blank);
      onSaved();
    }catch{setError("Connection problem. The save was not confirmed.");}
    finally{setSaving(false);}
  }
  return <section className="content-panel prospect-form-panel" aria-label={initial?"Edit Promoter":"Add Promoter"}>
    <h2>{initial?"Edit Promoter":"Add Promoter"}</h2>
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field"><span className="field-label">Full name <span className="required">*</span></span><input required maxLength={160} minLength={2} placeholder="Enter full name" value={form.full_name} onChange={e=>set("full_name",e.target.value)}/></label>
        <label className="field"><span className="field-label">Phone number <span className="required">*</span></span><input required type="tel" placeholder="+91 98765 43210" value={form.mobile_number} onChange={e=>set("mobile_number",e.target.value)}/></label>
        <details className="optional-details">
          <summary>More details (optional)</summary>
          <div className="optional-fields">
            <label className="field"><span className="field-label">WhatsApp number</span><input type="tel" placeholder="Same as mobile if empty" value={form.whatsapp_number} onChange={e=>set("whatsapp_number",e.target.value)}/></label>
            <label className="checkbox-field full"><input type="checkbox" checked={form.whatsapp_opt_in} onChange={e=>set("whatsapp_opt_in",e.target.checked)}/><span>WhatsApp communication consent recorded</span></label>
          </div>
        </details>
      </div>
      {error&&<p role="alert" className="form-error">{error}</p>}
      <div className="form-actions">
        {onCancel&&<button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>Cancel</button>}
        {!initial&&<button type="button" className="btn btn-secondary" disabled={saving} onClick={()=>setForm(blank)}>Clear</button>}
        <button type="submit" className="btn btn-primary" disabled={saving}>{saving?"Saving…":initial?"Save Changes":"Add Promoter"}</button>
      </div>
    </form>
  </section>;
}
