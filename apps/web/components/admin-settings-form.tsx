"use client";
import { FormEvent, useEffect, useState } from "react";

type Values = {
  currency_code:string; timezone:string; default_contribution_paise:number;
  sponsor_reminder_day:number; promoter_reminder_day:number;
  inactivity_months:number; automation_enabled:boolean;
};
type Editable = {
  monthly_amount_rupees:string; sponsor_day:string; promoter_day:string; inactivity_months:string;
};

function toForm(settings:Values): Editable {
  return {
    monthly_amount_rupees:(settings.default_contribution_paise/100).toString(),
    sponsor_day:settings.sponsor_reminder_day.toString(),
    promoter_day:settings.promoter_reminder_day.toString(),
    inactivity_months:settings.inactivity_months.toString()
  };
}

export function AdminSettingsForm(){
  const [current,setCurrent]=useState<Values|null>(null);
  const [form,setForm]=useState<Editable|null>(null);
  const [csrf,setCsrf]=useState("");
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [providerEnabled,setProviderEnabled]=useState(false);
  const [automationConfirmation,setAutomationConfirmation]=useState("");
  const [automationSaving,setAutomationSaving]=useState(false);
  useEffect(()=>{
    let mounted=true;
    Promise.all([
      fetch("/api/admin/session",{cache:"no-store"}),
      fetch("/api/admin/settings",{cache:"no-store"}),
      fetch("/api/admin/messaging/status",{cache:"no-store"})
    ]).then(async ([session,config,messaging])=>{
      if(!session.ok||!config.ok)throw Error("Settings are unavailable.");
      const identity=await session.json();
      const settings:Values=await config.json();
      const availability=messaging.ok?await messaging.json():null;
      if(mounted){
        setCsrf(identity.csrf_token);setCurrent(settings);setForm(toForm(settings));
        setProviderEnabled(Boolean(availability?.delivery_enabled));
      }
    }).catch(()=>{if(mounted)setError("Unable to load settings. Check your connection and try again.");})
      .finally(()=>{if(mounted)setLoading(false);});
    return ()=>{mounted=false;};
  },[]);
  function update(name:keyof Editable,value:string){
    setForm(old=>old?{...old,[name]:value}:old);setError("");setMessage("");
  }
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!form||!current||!csrf||saving)return;
    const rupees=Number(form.monthly_amount_rupees);
    const paise=Math.round(rupees*100);
    const sponsor_day=Number(form.sponsor_day),promoter_day=Number(form.promoter_day),months=2;
    if(!Number.isFinite(rupees)||!Number.isSafeInteger(paise)||(paise!==current.default_contribution_paise&&(paise<25000||paise%25000!==0))||
      Math.abs(rupees*100-paise)>0.001||![sponsor_day,promoter_day,months].every(Number.isInteger)||
      sponsor_day<1||sponsor_day>28||promoter_day<1||promoter_day>28||months!==2){
      setError("Use a positive monthly commitment in ₹250 increments, reminder days 1–28, and the fixed two-month inactivity rule.");
      return;
    }
    setSaving(true);setMessage("");setError("");
    try{
      const res=await fetch("/api/admin/settings",{
        method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},credentials:"same-origin",
        body:JSON.stringify({
          ...(paise!==current.default_contribution_paise?{default_contribution_paise:paise}:{}),
          sponsor_reminder_day:sponsor_day,promoter_reminder_day:promoter_day,inactivity_months:2,
        })
      });
      if(!res.ok){setError(res.status===403?"Your session could not be verified. Sign in again.":"Settings could not be saved. Please check the values.");return;}
      const saved:Values=await res.json();
      setCurrent(saved);setForm(toForm(saved));setMessage("Settings saved. Changes were recorded in the audit history.");
    } catch {setError("Connection problem. Your settings have not been confirmed.");}
    finally{setSaving(false);}
  }
  async function changeAutomation(){
    if(!current||!csrf||automationSaving)return;
    const enabled=!current.automation_enabled;
    if(automationConfirmation!==(enabled?"ENABLE WHATSAPP":"DISABLE WHATSAPP"))return;
    setAutomationSaving(true);setMessage("");setError("");
    try{
      const response=await fetch("/api/admin/automation",{
        method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        credentials:"same-origin",
        body:JSON.stringify({enabled,confirmation:automationConfirmation}),
      });
      if(!response.ok){
        setError(response.status===409
          ?"Approved production WhatsApp sender and activation controls are required."
          :"Unable to change WhatsApp automation. Check the session and confirmation.");
        return;
      }
      const updated:Values=await response.json();
      setCurrent(updated);setAutomationConfirmation("");
      setMessage(enabled?"Automation enabled for the approved sender.":"WhatsApp automation disabled immediately.");
    }catch{setError("Unable to confirm the automation change. Verify status before retrying.");}
    finally{setAutomationSaving(false);}
  }
  return <section className="content-panel" aria-label="Organization configuration">
    <h2>Organisation Settings</h2>
    {loading&&<p role="status">Loading settings…</p>}
    {!loading&&!form&&<p role="alert">{error||"Settings unavailable."}</p>}
    {form&&current&&<form onSubmit={submit}>
      <div className="form-grid">
        <label className="field"><span className="field-label">Default monthly contribution (₹)</span><input type="number" min={current.default_contribution_paise<25000?"0.01":"250"}
          step={current.default_contribution_paise%25000!==0?"any":"250"}
          required value={form.monthly_amount_rupees} onChange={e=>update("monthly_amount_rupees",e.target.value)}/></label>
        <label className="field"><span className="field-label">Sponsor reminder day of month</span><input type="number" min="1" max="28" step="1" required value={form.sponsor_day} onChange={e=>update("sponsor_day",e.target.value)}/></label>
        <label className="field"><span className="field-label">Promoter follow-up day of month</span><input type="number" min="1" max="28" step="1" required value={form.promoter_day} onChange={e=>update("promoter_day",e.target.value)}/></label>
        <label className="field"><span className="field-label">Inactive after (months)</span><input type="number" min="2" max="2" readOnly value="2"/></label>
      </div>
      <div className="readonly-settings"><div><strong>Accounting currency</strong><span>{current.currency_code}</span></div><div><strong>Accounting timezone</strong><span>{current.timezone}</span></div><div><strong>Automatic WhatsApp sending</strong><span>{current.automation_enabled?"Enabled for approved sender":"Disabled"}</span></div></div>
      <details className="optional-details settings-advanced">
        <summary>WhatsApp automation</summary>
        <div className="field">
        <label htmlFor="automation-confirmation" className="field-label">
          WhatsApp safety control — type {current.automation_enabled?"DISABLE WHATSAPP":"ENABLE WHATSAPP"} to confirm
        </label>
        <input id="automation-confirmation" type="text" autoComplete="off"
          aria-label="WhatsApp automation confirmation" value={automationConfirmation}
          onChange={event=>setAutomationConfirmation(event.target.value)} />
        <button className="btn btn-secondary" type="button"
          onClick={changeAutomation}
          disabled={automationSaving||saving||
            (!current.automation_enabled&&!providerEnabled)||
            automationConfirmation!==(current.automation_enabled?"DISABLE WHATSAPP":"ENABLE WHATSAPP")}>
          {automationSaving?"Updating…":current.automation_enabled?"Disable WhatsApp automation":"Enable WhatsApp automation"}
        </button>
        </div>
      </details>
      {message&&<p role="status" className="form-success">{message}</p>}
      {error&&<p role="alert" className="form-error">{error}</p>}
      <div className="form-actions"><button className="btn btn-secondary" type="button" disabled={saving} onClick={()=>{setForm(toForm(current));setError("");setMessage("");}}>Reset</button><button className="btn btn-primary" type="submit" disabled={saving}>{saving?"Saving…":"Save Changes"}</button></div>
    </form>}
  </section>;
}
