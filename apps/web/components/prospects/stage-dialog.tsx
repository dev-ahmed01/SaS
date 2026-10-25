"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Prospect } from "./prospects-types";
import { reasonLabel, stageReasons } from "./prospects-types";

type Challenge={challenge_id:string;expires_at:string;status:string};
type OtpStatus={delivery_enabled:boolean;verified:boolean;verified_at:string|null};

function confirmationStatus(value:string):string {
  switch(value){
    case "accepted_unverified":return "Activation confirmed. WhatsApp acknowledgement accepted by Saasyto; delivery is not verified.";
    case "suppressed_no_general_consent":return "Activated. No WhatsApp acknowledgement: communication permission is missing or withdrawn.";
    case "suppressed_local_test_number":return "Activated. No WhatsApp acknowledgement: number is outside the authorized local test.";
    case "before_sender_activation":return "Activated. WhatsApp acknowledgement is not enabled before the sender activation date.";
    case "rejected":return "Activated. WhatsApp acknowledgement was rejected by Saasyto.";
    case "unknown":return "Activated. WhatsApp acknowledgement outcome is unknown; no automatic retry will occur.";
    default:return "Activated. WhatsApp acknowledgement is disabled.";
  }
}

async function csrf():Promise<string>{
  const response=await fetch("/api/admin/session",{cache:"no-store"});
  if(!response.ok)throw Error("Admin session expired. Sign in again.");
  return (await response.json()).csrf_token as string;
}

async function post<T>(path:string, body?:Record<string,unknown>):Promise<T>{
  const token=await csrf();
  const response=await fetch("/api/admin/prospects/"+path,{
    method:"POST",credentials:"same-origin",
    headers:{"X-CSRF-Token":token,...(body?{"Content-Type":"application/json"}:{})},
    ...(body?{body:JSON.stringify(body)}:{}),
  });
  if(!response.ok){
    const problem=await response.json().catch(()=>null) as {detail?:unknown}|null;
    throw Error(typeof problem?.detail==="string"?problem.detail:
      response.status===409?"The prospect changed. Reload and retry.":
      "Could not complete this action.");
  }
  return response.json() as Promise<T>;
}

export function StageDialog({prospect,onClose,onChanged}:{
  prospect:Prospect;onClose:()=>void;onChanged:(notice?:string)=>void;
}){
  const markInactive=prospect.crm_stage==="active";
  const reactivation=!markInactive&&prospect.stage_history.some(x=>x.to_stage==="active");
  const [reason,setReason]=useState("");
  const [note,setNote]=useState("");
  const [code,setCode]=useState("");
  const [challenge,setChallenge]=useState<Challenge|null>(null);
  const [otpReady,setOtpReady]=useState<boolean|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const closeButton=useRef<HTMLButtonElement>(null);

  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    closeButton.current?.focus();
    function onKey(e:KeyboardEvent){
      if(e.key==="Escape"){e.preventDefault();onClose();}
    }
    window.addEventListener("keydown",onKey);
    return ()=>{window.removeEventListener("keydown",onKey);previous?.focus();};
  },[onClose]);

  useEffect(()=>{
    if(markInactive)return;
    const controller=new AbortController();
    fetch("/api/admin/prospects/"+prospect.id+"/otp/status",{
      cache:"no-store",signal:controller.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("OTP status could not be checked.");
      return response.json() as Promise<OtpStatus>;
    }).then(status=>{if(!controller.signal.aborted)setOtpReady(status.delivery_enabled);})
      .catch(()=>{if(!controller.signal.aborted)setError("OTP service is unavailable.");});
    return ()=>controller.abort();
  },[markInactive,prospect.id]);

  async function requestCode(){
    if(busy||otpReady!==true)return;
    setBusy(true);setError("");setNotice("");
    try{
      const response=await post<Challenge>(prospect.id+"/otp/request");
      setChallenge(response);
      setNotice("Code requested. Ask the sponsor for the six-digit code sent to their WhatsApp.");
    }catch(e){setError(e instanceof Error?e.message:"Could not request OTP.");}
    finally{setBusy(false);}
  }

  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(busy)return;
    if(markInactive&&!reason){setError("Select a reason for deactivation.");return;}
    if(!markInactive&&(!challenge||!/^[0-9]{6}$/.test(code))){
      setError("Request and enter the six-digit OTP first.");return;
    }
    if(reactivation&&note.trim().length<3){
      setError("Explain why this sponsor is being reactivated.");return;
    }
    setBusy(true);setError("");setNotice("");
    try{
      let confirmation:string|undefined;
      if(markInactive){
        await post(prospect.id+"/stage",{
          version:prospect.version,stage:"inactive",reason,note:note.trim()||null,
        });
      }else{
        const result=await post<{activation_notice:string}>(prospect.id+"/otp/activate",{
          version:prospect.version,challenge_id:challenge!.challenge_id,code,
          reactivation_reason:reactivation?note.trim():null,
        });
        confirmation=confirmationStatus(result.activation_notice);
      }
      onChanged(confirmation);
    }catch(e){setError(e instanceof Error?e.message:"Could not change active status.");}
    finally{setBusy(false);}
  }

  return <div className="crm-dialog-scrim" role="presentation"
    onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
    <section className="crm-dialog" role="dialog" aria-modal="true"
      aria-label={markInactive?"Mark prospect inactive":reactivation?"Reactivate prospect":"Activate prospect"}>
      <div className="crm-dialog-head">
        <div><h2>{markInactive?"Mark inactive":reactivation?"Reactivate prospect":"Verify and activate"}</h2>
          <p>{prospect.full_name}</p></div>
        <button ref={closeButton} type="button" className="text-action"
          onClick={onClose} aria-label="Close stage dialog">Close</button>
      </div>
      <form onSubmit={submit}>
        {markInactive?<>
          <label className="field"><span className="field-label">Reason for leaving *</span>
            <select required value={reason} onChange={e=>setReason(e.target.value)}>
              <option value="">Choose a reason</option>
              {stageReasons.map(x=><option key={x.value} value={x.value}>{x.label}</option>)}
            </select></label>
          <label className="field"><span className="field-label">Additional context (optional)</span>
            <textarea maxLength={500} rows={3} value={note} onChange={e=>setNote(e.target.value)}
              placeholder="Brief context to help understand attrition"/></label>
          <p className="crm-dialog-help">Reminders pause while inactive. Payments and history remain unchanged.</p>
        </>:<>
          {reactivation&&<>
            <p className="crm-dialog-help">Previous reason: {reasonLabel(prospect.crm_inactive_reason)}</p>
            <label className="field">
              <span className="field-label">Why are they returning? *</span>
              <textarea required minLength={3} maxLength={500} rows={3} value={note}
                onChange={e=>setNote(e.target.value)}
                placeholder="Reason for reactivation"/>
            </label>
          </>}
          <p className="crm-dialog-help">A new WhatsApp OTP is required before activation.
            This verifies the sponsor&apos;s number; existing communication permissions stay unchanged.</p>
          {otpReady===null?<p className="crm-muted">Checking OTP service…</p>:
            otpReady===false?
              <p role="alert" className="form-error">WhatsApp OTP is not configured.
                Activation is unavailable until an approved OTP provider is connected.</p>:
              !challenge?
                <button type="button" className="btn btn-secondary" disabled={busy}
                  onClick={requestCode}>{busy?"Requesting…":"Send WhatsApp OTP"}</button>:
                <label className="field">
                  <span className="field-label">Six-digit WhatsApp OTP *</span>
                  <input required inputMode="numeric" autoComplete="one-time-code"
                    pattern="[0-9]{6}" maxLength={6} placeholder="000000"
                    value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,""))}/>
                </label>}
          {challenge&&<p className="crm-muted">Code valid for 10 minutes. A new code is required for every activation.</p>}
        </>}
        {notice&&<p role="status" className="crm-muted">{notice}</p>}
        {error&&<p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}
            disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary"
            disabled={busy||(markInactive?!reason:!challenge||code.length!==6||
              (reactivation&&note.trim().length<3))}>
            {busy?"Checking…":markInactive?"Confirm Inactive":"Verify OTP & Activate"}
          </button>
        </div>
      </form>
    </section>
  </div>;
}
