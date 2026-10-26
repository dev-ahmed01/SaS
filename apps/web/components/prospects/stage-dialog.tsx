"use client";

import { FormEvent, KeyboardEvent, ClipboardEvent, useEffect, useRef, useState } from "react";
import type { Prospect } from "./prospects-types";
import { reasonLabel, stageReasons } from "./prospects-types";

type Challenge={challenge_id:string;expires_at:string;status?:string};
type OtpStatus={
  delivery_enabled:boolean;verified:boolean;verified_at:string|null;
  challenge_id:string|null;expires_at:string|null;
};
const EMPTY=["","","",""];
const fieldClasses="sas-otp-digit";

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

async function post<T>(path:string,body?:Record<string,unknown>):Promise<T>{
  const token=await csrf();
  const response=await fetch("/api/admin/prospects/"+path,{
    method:"POST",credentials:"same-origin",
    headers:{"X-CSRF-Token":token,...(body?{"Content-Type":"application/json"}:{})},
    ...(body?{body:JSON.stringify(body)}:{}),
  });
  if(!response.ok){
    const problem=await response.json().catch(()=>null) as {detail?:unknown}|null;
    throw Error(response.status===404?
      "OTP activation is unavailable. Refresh and try again.":
      typeof problem?.detail==="string"?problem.detail:
      response.status===409?"The prospect changed. Reload and retry.":
      "Could not complete this action.");
  }
  return response.json() as Promise<T>;
}

function countdown(ms:number):string{
  const seconds=Math.max(0,Math.ceil(ms/1000));
  return String(Math.floor(seconds/60)).padStart(2,"0")+":"+
    String(seconds%60).padStart(2,"0");
}

export function StageDialog({prospect,onClose,onChanged}:{
  prospect:Prospect;onClose:()=>void;onChanged:(notice?:string)=>void;
}){
  const markInactive=prospect.crm_stage==="active";
  const reactivation=!markInactive&&prospect.stage_history.some(x=>x.to_stage==="active");
  const number=prospect.whatsapp_number||prospect.mobile_number;
  const [reason,setReason]=useState("");
  const [note,setNote]=useState("");
  const [digits,setDigits]=useState<string[]>(EMPTY);
  const [challenge,setChallenge]=useState<Challenge|null>(null);
  const [otpReady,setOtpReady]=useState<boolean|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [now,setNow]=useState(()=>Date.now());
  const closeButton=useRef<HTMLButtonElement>(null);
  const digitRefs=useRef<(HTMLInputElement|null)[]>([]);
  // Avoid duplicate messages under React Strict Mode / rerenders.
  const started=useRef(false);
  const mounted=useRef(true);
  const expiry=challenge?Date.parse(challenge.expires_at):0;
  const expired=Boolean(challenge && (Number.isNaN(expiry)||now>=expiry));
  const code=digits.join("");

  useEffect(()=>{
    mounted.current=true;
    const previous=document.activeElement as HTMLElement|null;
    closeButton.current?.focus();
    function onKey(e:globalThis.KeyboardEvent){
      if(e.key==="Escape"){e.preventDefault();onClose();}
    }
    window.addEventListener("keydown",onKey);
    return ()=>{mounted.current=false;window.removeEventListener("keydown",onKey);previous?.focus();};
  },[onClose]);

  useEffect(()=>{
    if(markInactive)return;
    const interval=setInterval(()=>setNow(Date.now()),500);
    return ()=>clearInterval(interval);
  },[markInactive]);

  useEffect(()=>{
    if(!challenge||expired)return;
    digitRefs.current[0]?.focus();
  },[challenge?.challenge_id,expired]);

  useEffect(()=>{
    if(markInactive||started.current)return;
    started.current=true;
    let active=true;
    // Resume an existing unexpired challenge when a dialog is reopened.
    // Otherwise request exactly once upon the administrator clicking Mark Active.
    (async()=>{
      try{
        const res=await fetch("/api/admin/prospects/"+prospect.id+"/otp/status",{
          cache:"no-store",
        });
        if(!res.ok)throw Error("Could not check WhatsApp OTP availability.");
        const status=await res.json() as OtpStatus;
        if(!active)return;
        setOtpReady(status.delivery_enabled);
        if(!status.delivery_enabled){
          setError("WhatsApp OTP delivery is not configured.");return;
        }
        if(status.challenge_id&&status.expires_at&&
          Date.parse(status.expires_at)>Date.now()){
          setChallenge({challenge_id:status.challenge_id,expires_at:status.expires_at});
          return;
        }
        setBusy(true);
        const issued=await post<Challenge>(prospect.id+"/otp/request");
        if(active){
          setChallenge(issued);
          setNow(Date.now());
        }
      }catch(e){
        if(active){setError(e instanceof Error?e.message:"Could not request OTP.");setOtpReady(old=>old??false);}
      }finally{if(active)setBusy(false);}
    })();
    // Strict Mode re-runs effects during development. The first fetch is ignored
    // after cleanup, while the next setup is allowed to request exactly once.
    return ()=>{active=false;started.current=false;};
  },[markInactive,prospect.id]);

  async function requestCode(){
    if(busy||otpReady!==true||(challenge&&!expired))return;
    setBusy(true);setError("");
    try{
      const response=await post<Challenge>(prospect.id+"/otp/request");
      if(!mounted.current)return;
      setChallenge(response);setDigits(EMPTY);setNow(Date.now());
    }catch(e){if(mounted.current)setError(e instanceof Error?e.message:"Could not request OTP.");}
    finally{if(mounted.current)setBusy(false);}
  }

  function applyDigits(index:number,raw:string){
    const incoming=raw.replace(/\D/g,"");
    if(!incoming)return;
    const next=[...digits];
    for(let i=0;i<incoming.length&&index+i<4;i++)next[index+i]=incoming[i];
    setDigits(next);
    digitRefs.current[Math.min(3,index+incoming.length)]?.focus();
  }

  function keyDown(event:KeyboardEvent<HTMLInputElement>,index:number){
    if(event.key==="Backspace"){
      event.preventDefault();
      const next=[...digits];
      const target=next[index]?index:Math.max(0,index-1);
      next[target]="";setDigits(next);digitRefs.current[target]?.focus();
    }else if(event.key==="ArrowLeft"&&index>0){
      event.preventDefault();digitRefs.current[index-1]?.focus();
    }else if(event.key==="ArrowRight"&&index<3){
      event.preventDefault();digitRefs.current[index+1]?.focus();
    }
  }

  function paste(event:ClipboardEvent<HTMLInputElement>){
    event.preventDefault();
    const pasted=event.clipboardData.getData("text").replace(/\D/g,"").slice(0,4);
    if(pasted){
      setDigits([...pasted.split(""),...EMPTY].slice(0,4));
      digitRefs.current[Math.min(3,pasted.length)]?.focus();
    }
  }

  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(busy)return;
    if(markInactive&&!reason){setError("Select a reason for deactivation.");return;}
    if(!markInactive&&(!challenge||expired||!/^\d{4}$/.test(code))){
      setError(expired?"This OTP expired. Request a new code.":"Enter all four OTP digits.");
      return;
    }
    if(reactivation&&note.trim().length<3){
      setError("Explain why this sponsor is being reactivated.");return;
    }
    setBusy(true);setError("");
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
    finally{if(mounted.current)setBusy(false);}
  }

  return <div className="crm-dialog-scrim" role="presentation"
    onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
    <section className={"crm-dialog"+(markInactive?"":" sas-otp-dialog")}
      role="dialog" aria-modal="true"
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
          <div className="sas-otp-summary">
            <span className="crm-muted">{challenge&&!expired?"Code requested for":"WhatsApp number"}</span>
            <strong>{number}</strong>
          </div>
          {otpReady===null?<p className="crm-muted">Preparing WhatsApp verification…</p>:
            otpReady===false?
              <p role="alert" className="form-error">WhatsApp OTP delivery is not configured.
                Activation is unavailable until a provider is connected.</p>:
            challenge&&!expired?
              <div className="sas-otp-entry">
                <div className="field-label" id="sas-otp-label">4-digit OTP</div>
                <div className="sas-otp-inputs" role="group" aria-labelledby="sas-otp-label">
                  {digits.map((digit,index)=><input key={index} ref={el=>{digitRefs.current[index]=el;}}
                    className={fieldClasses} type="text" inputMode="numeric"
                    autoComplete={index===0?"one-time-code":"off"} maxLength={4}
                    aria-label={"OTP digit "+(index+1)}
                    value={digit} disabled={busy} onPaste={paste}
                    onFocus={e=>e.currentTarget.select()}
                    onKeyDown={e=>keyDown(e,index)}
                    onChange={e=>{
                      const raw=e.target.value.replace(/\D/g,"");
                      if(!raw){setDigits(old=>old.map((v,i)=>i===index?"":v));return;}
                      const corrected=raw.length===2&&digit&&raw[0]===digit
                        ?raw[1]:raw;
                      applyDigits(index,corrected);
                    }}/>)}
                </div>
                <p className="sas-otp-timer" role="timer" aria-live="off">
                  Expires in <strong>{countdown(expiry-now)}</strong>
                </p>
              </div>:
              <div className="sas-otp-entry">
                <p role="status" className="crm-dialog-help">
                  {expired?"This OTP has expired. Request a new code.":
                  busy?"Requesting the verification code…":
                  "No active verification code. Request a new one."}
                </p>
                <button type="button" className="btn btn-secondary" disabled={busy}
                  onClick={()=>void requestCode()}>{busy?"Requesting…":"Send new OTP"}</button>
              </div>}
        </>}
        {error&&<p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}
            disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary"
            disabled={busy||(markInactive?!reason:!challenge||expired||code.length!==4||
              (reactivation&&note.trim().length<3))}>
            {busy?"Checking…":markInactive?"Confirm Inactive":"Verify OTP & Activate"}
          </button>
        </div>
      </form>
    </section>
  </div>;
}
