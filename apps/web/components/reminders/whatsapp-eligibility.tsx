"use client";

import { useEffect,useRef,useState } from "react";
import { MessageDeliveryStatus } from "./message-delivery-status";
import { formatCRMDate } from "../../lib/crm-dates";

type Kind="sponsor"|"promoter";
type Unpaid={prospect_id:string;full_name:string;outstanding_paise:number};
type Recipient={
  recipient_id:string;recipient_name:string;
  sponsor_count:number;outstanding_paise:number;unpaid_sponsors:Unpaid[];
};
type Preview={
  kind:Kind;period_month:string;today_ist:string;scheduled_on:string;
  is_due_today:boolean;eligible_recipients:number;unpaid_sponsors:number;
  total_outstanding_paise:number;recipients:Recipient[];notice:string;
};
type Batch={
  id:string;kind:Kind;period_month:string;scheduled_on:string;
  recipient_count:number;status:"prepared"|"partially_delivered"|"delivered";delivered_count:number;
};
type BatchPage={items:Batch[];total:number};
const money=(value:number)=>(value/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",
});

export function WhatsAppEligibility(){
  const [kind,setKind]=useState<Kind>("sponsor");
  const [preview,setPreview]=useState<Preview|null>(null);
  const [history,setHistory]=useState<BatchPage|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [ack,setAck]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const request=useRef<string|null>(null);

  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);
    setError("");
    fetch("/api/admin/reminders/preview?kind="+kind,{
      cache:"no-store",signal:controller.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("Eligibility unavailable");
      return await response.json() as Preview;
    }).then(data=>{if(!controller.signal.aborted)setPreview(data);})
      .catch(()=>{if(!controller.signal.aborted){
        setPreview(null);
        setError("Could not load verified reminder eligibility.");
      }})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[kind,revision]);
  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/admin/reminders/batches?limit=20",{
      cache:"no-store",signal:controller.signal,
    }).then(async res=>{
      if(!res.ok)throw Error("History unavailable");
      return await res.json() as BatchPage;
    }).then(data=>{if(!controller.signal.aborted)setHistory(data);})
      .catch(()=>{if(!controller.signal.aborted)setHistory(null);});
    return ()=>controller.abort();
  },[revision]);

  async function prepare(){
    if(!preview?.is_due_today||saving||!ack)return;
    setSaving(true);setError("");setMessage("");
    if(!request.current)request.current=crypto.randomUUID();
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Sign in again to prepare a reminder batch.");
      const {csrf_token}=await session.json();
      const result=await fetch("/api/admin/reminders/prepare",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({kind,request_id:request.current}),
      });
      if(!result.ok){
        if(result.status===409){
          throw Error("This month's batch may already exist or the reminder day has passed.");
        }
        throw Error("Preparation was not confirmed. Check history before retrying.");
      }
      const batch:Batch=await result.json();
      setMessage("Prepared "+batch.recipient_count+" "+kind+" recipient intents for "+
        formatCRMDate(batch.period_month)+". No messages were sent.");
      request.current=null;setAck(false);setRevision(n=>n+1);
    }catch(err){
      setError(err instanceof Error?err.message:"Unable to confirm reminder preparation.");
    }finally{setSaving(false);}
  }

  const isAlreadyPrepared=history?.items.some(batch=>batch.kind===kind&&
    batch.period_month===preview?.period_month);
  return <div className="reminder-workspace">
    <MessageDeliveryStatus/>
    <section className="reminder-intro">
      <div>
        <h2>WhatsApp eligibility</h2>
      </div>
      <div className="reminder-kind" role="group" aria-label="Reminder audience">
        <button type="button" aria-pressed={kind==="sponsor"}
          className={kind==="sponsor"?"selected":""}
          onClick={()=>{setKind("sponsor");setAck(false);setMessage("");
            request.current=null;}}>
          Sponsors
        </button>
        <button type="button" aria-pressed={kind==="promoter"}
          className={kind==="promoter"?"selected":""}
          onClick={()=>{setKind("promoter");setAck(false);setMessage("");
            request.current=null;}}>
          Promoters
        </button>
      </div>
    </section>

    <p className="reminder-no-send" role="status">WhatsApp sending: off.</p>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {message&&<p role="status" className="form-success">{message}</p>}
    <div className="accounting-metrics">
      {[
        ["Scheduled IST date",formatCRMDate(preview?.scheduled_on)],
        ["Eligible recipients",String(preview?.eligible_recipients??"—")],
        ["Unpaid sponsors",String(preview?.unpaid_sponsors??"—")],
        ["Outstanding",preview?money(preview.total_outstanding_paise):"—"],
      ].map(([label,value])=><div className="accounting-metric" key={label}>
        <span>{label}</span><strong>{value}</strong>
      </div>)}
    </div>
    <section className="reminder-review" aria-label="Eligible reminder recipients">
      <div className="review-heading"><div>
        <h3>{kind==="sponsor"?"Unpaid sponsor reminders":"Consolidated promoter follow-ups"}</h3>
      </div></div>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th scope="col">{kind==="sponsor"?"Sponsor":"Promoter"}</th>
          <th scope="col">Unpaid sponsors</th><th scope="col">Outstanding</th>
          <th scope="col">Follow-up details</th></tr></thead>
        <tbody>{loading?<tr><td colSpan={4}>Calculating eligibility…</td></tr>
          :!preview?.recipients.length?<tr><td colSpan={4}>
            No eligible {kind} recipients. No message will be prepared.</td></tr>
          :preview.recipients.map(person=><tr key={person.recipient_id}>
            <td><strong className="table-name">{person.recipient_name}</strong></td>
            <td>{person.sponsor_count}</td>
            <td>{money(person.outstanding_paise)}</td>
            <td><span className="reminder-sponsor-list">
              {person.unpaid_sponsors.map(x=>x.full_name).join(", ")}
            </span></td>
          </tr>)}</tbody>
      </table></div>
      <div className="reminder-prepare">
        <label className="checkbox-field">
          <input type="checkbox" checked={ack}
            onChange={event=>setAck(event.target.checked)}/>
          <span>I understand this prepares a record only and sends no WhatsApp messages.</span>
        </label>
        <button type="button" className="btn btn-primary"
          disabled={loading||saving||!preview?.is_due_today||!ack||Boolean(isAlreadyPrepared)}
          onClick={prepare}>
          {saving?"Preparing…":"Prepare batch (do not send)"}
        </button>

         <p className="accounting-footnote">{isAlreadyPrepared?"Already prepared this month.":preview?.is_due_today?"Ready to prepare.":"Available on the scheduled reminder day."}</p>
      </div>
    </section>
    <section className="reminder-review" aria-label="Reminder preparation history">
      <h3>Preparation history</h3>
      <div className="table-scroll"><table className="data-table"><thead><tr>
        <th scope="col">Month</th><th scope="col">Audience</th>
        <th scope="col">Recipients</th><th scope="col">Status</th>
      </tr></thead><tbody>{!history?.items.length?<tr><td colSpan={4}>
        No prepared batches yet.</td></tr>
      :history.items.map(batch=><tr key={batch.id}>
        <td>{formatCRMDate(batch.period_month)}</td>
        <td>{batch.kind==="sponsor"?"Sponsors":"Promoters"}</td>
        <td>{batch.recipient_count}</td>
        <td><span className={"status-pill "+(batch.status==="delivered"?"active":"scheduled")}>
           {batch.status==="delivered"
             ?"Delivered · "+batch.delivered_count+"/"+batch.recipient_count
             :batch.status==="partially_delivered"
               ?"Partially delivered · "+batch.delivered_count+"/"+batch.recipient_count
               :"Prepared, not confirmed sent"}
         </span></td>
      </tr>)}</tbody></table></div>
    </section>
  </div>;
}
