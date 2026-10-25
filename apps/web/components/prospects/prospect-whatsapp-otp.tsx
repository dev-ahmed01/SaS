"use client";

import { useEffect, useState } from "react";
import type { Prospect } from "./prospects-types";

type OtpStatus={delivery_enabled:boolean;verified:boolean;verified_at:string|null;activation_enabled:boolean};
type Verified={status:string;verified_at:string;crm_stage:string;activation_notice:string};
type Issued={challenge_id:string;expires_at:string;status:string};

export function ProspectWhatsappOtp({prospect,onChanged}:{
  prospect:Prospect;onChanged:()=>void;
}){
  const [status,setStatus]=useState<OtpStatus|null>(null);
  const [challenge,setChallenge]=useState<Issued|null>(null);
  const [code,setCode]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    setStatus(null);setChallenge(null);setCode("");setError("");setNotice("");
    fetch("/api/admin/prospects/"+prospect.id+"/otp/status",{
      cache:"no-store",signal:controller.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("Verification status unavailable.");
      return await response.json() as OtpStatus;
    }).then(data=>{if(!controller.signal.aborted)setStatus(data);})
      .catch(()=>{if(!controller.signal.aborted)setError("Verification status unavailable.");});
    return()=>controller.abort();
  },[prospect.id,prospect.mobile_number,prospect.whatsapp_number]);
  async function csrf(){
    const session=await fetch("/api/admin/session",{cache:"no-store"});
    if(!session.ok)throw Error("Admin session expired.");
    return (await session.json()).csrf_token as string;
  }
  async function request(){
    if(busy)return;setBusy(true);setError("");setNotice("");
    try{
      const token=await csrf();
      const response=await fetch("/api/admin/prospects/"+prospect.id+"/otp/request",{
        method:"POST",credentials:"same-origin",headers:{"X-CSRF-Token":token},
      });
      if(!response.ok)throw Error(response.status===429?
        "Verification limit reached. Try again after the cooldown.":
        "Could not request a WhatsApp code. No delivery was confirmed.");
      setChallenge(await response.json() as Issued);
      setNotice("WhatsApp provider accepted the code request. Ask the sponsor for the six-digit code.");
    }catch(e){setError(e instanceof Error?e.message:"Request failed.");}
    finally{setBusy(false);}
  }
  async function verify(){
    if(!challenge||busy||!/^[0-9]{6}$/.test(code))return;
    setBusy(true);setError("");setNotice("");
    try{
      const token=await csrf();
      const response=await fetch("/api/admin/prospects/"+prospect.id+"/otp/verify",{
        method:"POST",credentials:"same-origin",
        headers:{"X-CSRF-Token":token,"Content-Type":"application/json"},
        body:JSON.stringify({challenge_id:challenge.challenge_id,code}),
      });
      if(!response.ok)throw Error("Invalid, expired, or exhausted verification code.");
      const result=await response.json() as Verified;
      setChallenge(null);setCode("");
      setStatus(previous=>({
        delivery_enabled:true,verified:true,verified_at:result.verified_at,
        activation_enabled:previous?.activation_enabled??false,
      }));
      setNotice(result.crm_stage==="active"
        ? "WhatsApp verified. This prospect is now CRM-Active. "+
          (result.activation_notice==="accepted_unverified"
            ? "Saasyto accepted the activation message; WhatsApp delivery is unverified."
            : result.activation_notice==="skipped_no_permission"
              ? "No activation message was sent because communication permission is missing."
              : result.activation_notice==="disabled"
                ? "The activation message feature is disabled."
                : "Activation message was not confirmed.")
        : "WhatsApp verified. CRM status remains unchanged; OTP activation is not enabled or this is not a new registration.");
      onChanged();
    }catch(e){setError(e instanceof Error?e.message:"Verification failed.");}
    finally{setBusy(false);}
  }
  return <div className="crm-otp-control">
    <h3>WhatsApp number verification</h3>
    {!status?<p className="crm-muted">Checking verification readiness…</p>:
      status.verified?<p role="status">Verified{status.verified_at?
        " · "+new Date(status.verified_at).toLocaleDateString("en-IN",{timeZone:"Asia/Kolkata"}):""}</p>:
      !status.delivery_enabled?
        <p className="crm-muted">Verification will be available when the approved provider is connected. No code will be sent yet.</p>:
        <>
          <p className="crm-muted">Verify the sponsor&apos;s WhatsApp number. This never counts as payment or WhatsApp marketing consent. If onboarding activation is enabled, a verified code makes an eligible new prospect CRM-Active.</p>
          {!challenge?<button type="button" className="btn btn-secondary" disabled={busy}
            onClick={request}>{busy?"Requesting…":"Send verification code"}</button>:
            <div className="crm-otp-verify-form">
              <label className="field"><span className="field-label">Six-digit WhatsApp code</span>
                <input inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                  value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,""))}
                  placeholder="000000"/></label>
              <button type="button" className="btn btn-primary" disabled={busy||code.length!==6}
                onClick={verify}>{busy?"Checking…":"Verify number"}</button>
            </div>}
        </>}
    {notice&&<p role="status" className="crm-muted">{notice}</p>}
    {error&&<p role="alert" className="form-error">{error}</p>}
  </div>;
}
