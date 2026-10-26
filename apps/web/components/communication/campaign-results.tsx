"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiWrite, istDisplay } from "./types";

type Status="not_approved"|"approved"|"cancelled"|"completed";
type Summary={
  campaign_id:string;run_status:Status;planned:number;
  submitted_unverified:number;rejected:number;unknown:number;
  queued:number;claimed:number;suppressed_after_approval:number;
  excluded_in_review:number;
  delivered:number|null;read:number|null;
};
type Recipient={
  recipient_kind:"prospect"|"promoter";recipient_id:string;
  name:string;phone:string;status:string;reason:string|null;
  finished_at:string|null;
};
type CampaignDetails={
  campaign_id:string;title:string;audience:string;segment:string;category:string;
  channel:string;planned_for:string|null;created_at:string;
  summary:Summary;latest_review_at:string|null;
  eligible_in_review:number;excluded_in_review:number;
  excluded_reasons:Record<string,number>;
  recipients:Recipient[];eligible_recipients:Recipient[];
  excluded_recipients:Recipient[];
  delivery_notice:string;
};
type Review={
  id:string;eligible_count:number;suppressed_count:number;
  evaluated_at:string;exclusion_reasons?:Record<string,number>;
};
type DeliveryRun={
  id:string;status:Status;queued:number;eligible_count:number;
  accepted_unverified:number;rejected:number;unknown:number;suppressed_after_approval:number;
};
type Provider={
  delivery_enabled:boolean;local_test_mode?:boolean;
  activation_cutoff?:string|null;
};
type Readiness={
  ready:boolean;code:string;message:string;eligible_count:number;
  local_test_mode:boolean;permitted_phone:string|null;
};
const reasons:Record<string,string>={
  no_general_consent:"General-message permission not recorded",
  no_whatsapp_consent:"WhatsApp permission not recorded",
  no_email_consent:"No documented email permission",
  missing_address:"No contact number",
  opted_out:"Contact opted out",
  inactive_reminder:"Inactive contact cannot receive reminders",
  duplicate_address:"Duplicate contact number",
  campaign_cancelled:"Campaign cancelled before submission",
  consent_or_status_changed:"Consent, status or phone changed before sending",
  rejected:"Saasyto rejected the submission",
  unknown:"Sending result unverified",
  provider_rejected:"Saasyto rejected the request",
  provider_http_error:"Saasyto returned an HTTP error",
  unverified_provider_reply:"Saasyto response did not confirm acceptance",
  network_error:"Could not verify Saasyto response",
  provider_timeout:"Saasyto did not answer in time",
};
const statuses:Record<string,string>={
  queued:"Queued — not submitted",
  claimed:"Claimed — outcome pending/uncertain",
  accepted_unverified:"Accepted by Saasyto · delivery unconfirmed",
  rejected:"Rejected by Saasyto",
  unknown:"Outcome unverified",
  suppressed:"Not sent",
  excluded:"Not eligible at recipient check",
  eligible_in_review:"Eligible · not yet sent",
};
function Metric({name,value,help}:{
  name:string;value:number|string;help?:string;
}){
  return <div className="crm-summary-tile">
    <span className="crm-muted">{name}</span>
    <strong>{value}</strong>
    {help&&<small className="comm-muted">{help}</small>}
  </div>;
}
function RecipientTable({title,rows}:{
  title:string;rows:Recipient[];
}){
  return <section className="comm-recipient-review comm-result-people"
    role="region" aria-label={title}>
    <div className="comm-review-heading"><h3>{title}</h3>
      <span className="comm-muted">{rows.length} contacts</span></div>
    {rows.length===0?<p className="comm-muted">No contacts yet.</p>:
      <ul className="comm-result-list">{rows.map(row=>
        <li key={row.recipient_kind+row.recipient_id} className="comm-result-person">
          <div className="comm-result-person-main">
            <Link href={row.recipient_kind==="prospect"
              ?"/prospects/"+row.recipient_id:"/promoters/"+row.recipient_id}>
              {row.name}</Link>
            <small>{row.phone}</small>
          </div>
          <div className="comm-result-person-outcome">
            <strong>{statuses[row.status]??row.status}</strong>
            {(row.reason||row.finished_at)&&<small>{
              row.reason?(reasons[row.reason]??row.reason.replaceAll("_"," ")):
              row.finished_at?istDisplay(row.finished_at):""}</small>}
          </div>
        </li>)}</ul>}
  </section>;
}

export function CampaignResultDetails({id,onBack}:{
  id:string;onBack?:()=>void;
}){
  const [details,setDetails]=useState<CampaignDetails|null>(null);
  const [review,setReview]=useState<Review|null>(null);
  const [run,setRun]=useState<DeliveryRun|null>(null);
  const [provider,setProvider]=useState<Provider|null>(null);
  const [readiness,setReadiness]=useState<Readiness|null>(null);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const refresh=useCallback(async()=>{
    // Results must remain visible even if optional provider/readiness APIs
    // cannot be reached. These read failures never authorize delivery.
    const result=await apiGet<CampaignDetails>("/campaigns/"+id+"/results");
    setDetails(result);
    const [checks,dispatch,availability,approvalCheck]=await Promise.allSettled([
      apiGet<Review[]>("/campaigns/"+id+"/preparations"),
      apiGet<DeliveryRun|null>("/campaigns/"+id+"/saasyto"),
      apiGet<Provider>("/provider/saasyto"),
      apiGet<Readiness>("/campaigns/"+id+"/saasyto/readiness"),
    ]);
    setReview(checks.status==="fulfilled"?(checks.value[0]??null):null);
    setRun(dispatch.status==="fulfilled"?dispatch.value:null);
    setProvider(availability.status==="fulfilled"?availability.value:null);
    setReadiness(approvalCheck.status==="fulfilled"?approvalCheck.value:null);
    if(checks.status==="rejected"||dispatch.status==="rejected"||
      availability.status==="rejected"||approvalCheck.status==="rejected"){
      setNotice("Campaign results loaded, but some delivery settings are unavailable. "+
        "Live approval is disabled until those settings can be verified.");
    }
  },[id]);
  useEffect(()=>{
    let active=true;
    setLoading(true);
    refresh().catch(()=>{if(active)setError("Campaign results could not be loaded.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[refresh]);
  useEffect(()=>{
    // Approved campaigns are processed by a separate private worker.
    // Poll read-only status while queued, without ever initiating a send.
    if(run?.status!=="approved")return;
    const timer=setInterval(()=>{
      if(document.visibilityState==="visible"){
        void refresh().catch(()=>setError("Could not refresh sending results."));
      }
    },15000);
    return ()=>clearInterval(timer);
  },[run?.status,refresh]);

  async function checkRecipients(){
    if(busy)return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/preparations","POST",{
        request_id:crypto.randomUUID(),simulation_only:true,
      });
      await refresh();setNotice("Recipient check updated. No messages were sent.");
    }catch(e){setError(e instanceof Error?e.message:"Could not check recipients.");}
    finally{setBusy(false);}
  }
  const localImmediate=Boolean(provider?.local_test_mode&&!details?.planned_for);
  const futurePlan=Boolean(details?.planned_for&&
    new Date(details.planned_for).getTime()>Date.now());
  async function approve(){
    if(busy||!review||!readiness?.ready||!provider?.delivery_enabled||
      review.eligible_count<1||run)return;
    const immediate=localImmediate;
    if(!window.confirm(immediate
      ? "Send one WhatsApp message now to the authorized test contact? "+
        "The request will reach Saasyto immediately. Gateway acceptance is not delivery."
      : "Approve "+review.eligible_count+
        " eligible recipient(s)? Messages will be queued for the private sender. "+
        "Gateway acceptance does not confirm delivery."))return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/saasyto","POST",{
        preparation_id:review.id,expected_eligible:review.eligible_count,
        confirm_send:true,
      });
      if(immediate){
        try{
          const attempt=await apiWrite<DeliveryRun>(
            "/campaigns/"+id+"/saasyto/send-now","POST",{}
          );
          await refresh();
          setNotice(attempt.accepted_unverified===1
            ? "Saasyto accepted the message. Check the recipient's WhatsApp; delivery is not confirmed."
            : attempt.rejected===1
              ? "Saasyto rejected the message. Review the sending result and sender connection."
              : attempt.unknown===1
                ? "Saasyto result is unknown. Verify on WhatsApp before considering another campaign."
                : attempt.suppressed_after_approval===1
                  ? "Not sent: the recipient no longer meets sending requirements."
                  : "Message attempt recorded. See the result below.");
        }catch{
          await refresh();
          setError("Approved, but immediate submission could not be verified. "+
            "Review results before taking another action. Do not resend this campaign.");
        }
      }else{
        await refresh();
        setNotice("Approved and queued. The private sending worker must be running "+
          "for the message to reach Saasyto when due.");
      }
    }catch(e){setError(e instanceof Error?e.message:"Unable to approve campaign.");}
    finally{setBusy(false);}
  }
  async function sendPendingLocal(){
    if(busy||!provider?.local_test_mode||!provider.delivery_enabled||
      !run||run.status!=="approved"||run.queued!==1||futurePlan)return;
    if(!window.confirm("Submit this single pending WhatsApp message now? "+
      "This cannot be undone and will never be automatically retried."))return;
    setBusy(true);setError("");setNotice("");
    try{
      const attempt=await apiWrite<DeliveryRun>(
        "/campaigns/"+id+"/saasyto/send-now","POST",{}
      );
      await refresh();
      setNotice(attempt.accepted_unverified===1
        ? "Saasyto accepted the message; check WhatsApp for actual receipt."
        : "Sending attempt recorded. See the recipient outcome below.");
    }catch{
      await refresh();
      setError("Could not verify submission. Check the recipient attempt status; "+
        "do not automatically send again.");
    }finally{setBusy(false);}
  }
  async function cancel(){
    if(busy||!run||run.status!=="approved"||
      !window.confirm("Stop not-yet-submitted messages? Already submitted messages cannot be recalled."))
      return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/saasyto/cancel","POST",{});
      await refresh();setNotice("Pending submissions cancelled.");
    }catch(e){setError(e instanceof Error?e.message:"Unable to stop pending sends.");}
    finally{setBusy(false);}
  }
  const older=Boolean(
    provider?.activation_cutoff&&details&&
    new Date(details.created_at).getTime()<new Date(provider.activation_cutoff).getTime()
  );
  const s=details?.summary;
  return <section className="comm-panel" aria-label="Campaign results detail">
      <div className="comm-panel-header">
        <div><Link href="/communication/campaigns" className="back-link"
          onClick={onBack}>
          All campaigns</Link>
          <h2>{details?.title??"Campaign results"}</h2>
          {details&&<p>{details.channel==="whatsapp"?"WhatsApp":"Email"} ·
            {" "+details.audience+" / "+details.segment} ·
            {" Created "+istDisplay(details.created_at)}</p>}
        </div>
        <button type="button" className="btn btn-secondary" disabled={busy||loading}
          onClick={()=>{setError("");void refresh().catch(()=>setError("Could not refresh results."));}}>
          Refresh results</button>
      </div>
      {loading&&<p role="status">Loading campaign results…</p>}
      {error&&<p role="alert" className="form-error">{error}</p>}
      {notice&&<p role="status" className="form-success">{notice}</p>}
      {details&&s&&<>
        <p className="comm-muted">
          {details.planned_for?"Planned "+istDisplay(details.planned_for):"Send after approval"}
          {" · "} {s.run_status==="not_approved"?"Not approved":s.run_status}
        </p>
        <div className="comm-result-stats">
          <Metric name="Accepted by Saasyto" value={s.submitted_unverified}/>
          <Metric name="Excluded / not sent" value={
            s.suppressed_after_approval+s.excluded_in_review}/>
          <Metric name="Failed" value={s.rejected}/>
          <Metric name="Pending / unknown" value={s.queued+s.claimed+s.unknown}/>
        </div>
        <p className="comm-muted" role="status">
          Delivered and read: <strong>Not verified</strong>. Saasyto accepting
          a message does not mean it reached the recipient.
        </p>
        {older&&!run&&<p className="form-error" role="status">
          This campaign predates Saasyto activation. Create a new campaign
          to obtain a valid delivery approval.</p>}
        {provider?.local_test_mode&&!run&&details.eligible_in_review>1&&
          <p className="form-error" role="status">
            Local test allows one authorized recipient. This campaign has
            multiple eligible contacts.
          </p>}
        {run?.status==="approved"&&<p className="comm-muted" role="status">
          {futurePlan
            ? "Scheduled for later. The private dispatcher submits eligible contacts when due."
            : "Approved and queued. The private worker submits eligible contacts in batches."}
          {" "}{s.queued} waiting · {s.claimed} claimed. Results refresh automatically while pending.
          {provider?.local_test_mode
            ? " For one-phone local testing, use Send pending WhatsApp now instead."
            : " Confirm the production worker is running; approval alone does not send."}
        </p>}
        {run?.status==="completed"&&<p className="comm-muted">
          Sending attempt finished. To send a different message, create a new campaign.
        </p>}
        {!provider?.delivery_enabled&&<p className="comm-muted">
          WhatsApp sending is disabled in backend settings. Creating a plan does not send a message.
        </p>}
        {provider?.local_test_mode&&<p className="comm-muted">
          Local testing is limited to one authorized WhatsApp number.
          {readiness?.permitted_phone
            ? " Configured test recipient: "+readiness.permitted_phone+"."
            : ""}
        </p>}
        {!run&&readiness&&!readiness.ready&&
          <p className="form-error" role="alert">
            <strong>Cannot send yet: </strong>{readiness.message}
          </p>}
        {!run&&!readiness&&provider?.delivery_enabled&&
          <p className="form-error" role="alert">
            Approval requirements could not be checked. Refresh results.
          </p>}
        <div className="comm-recipient-review" role="region" aria-label="Recipient approval">
          <div className="comm-review-heading">
            <h3>Recipient review</h3>
            <span className="comm-muted">
              {review?istDisplay(review.evaluated_at):"Not checked yet"}
            </span>
          </div>
          <div className="comm-review-counts">
            <span><strong>{details.eligible_in_review}</strong> Eligible</span>
            <span><strong>{details.excluded_in_review}</strong> Excluded</span>
          </div>

          {Object.keys(details.excluded_reasons).length>0&&
            <p className="comm-muted">Excluded: {Object.entries(
              details.excluded_reasons).map(([key,count])=>
                (reasons[key]??key.replaceAll("_"," "))+" ("+count+")"
              ).join(" · ")}</p>}
          <div className="comm-review-footer">
            <span className="comm-muted">Review only; no messages sent yet.</span>
            {!run&&<button type="button" className="btn btn-secondary"
              disabled={busy} onClick={()=>void checkRecipients()}>
              {busy?"Working…":"Check recipients"}</button>}
            {run?.status==="approved"&&run.queued===1&&provider?.local_test_mode&&
              provider.delivery_enabled&&!futurePlan&&<button type="button"
              className="btn btn-primary" disabled={busy}
              onClick={()=>void sendPendingLocal()}>
                {busy?"Sending…":"Send pending WhatsApp now"}
              </button>}
            {!run&&provider?.delivery_enabled&&<button type="button"
              className="btn btn-primary" disabled={
                busy||older||!review||!readiness?.ready||review.eligible_count===0||
                Boolean(provider.local_test_mode&&review.eligible_count!==1)
              } onClick={()=>void approve()}>
                {busy?"Working…":localImmediate?"Send WhatsApp now":"Approve WhatsApp delivery"}
              </button>}
            {run?.status==="approved"&&<button type="button" className="btn btn-secondary"
              disabled={busy} onClick={()=>void cancel()}>Stop pending sends</button>}
          </div>
        </div>
        <RecipientTable title="Sending results by contact" rows={details.recipients}/>
        {!run&&<RecipientTable title="Eligible contacts (latest recipient check)"
          rows={details.eligible_recipients}/>}
        <RecipientTable title="Excluded before sending (latest review)"
          rows={details.excluded_recipients}/>
      </>}
  </section>;
}
