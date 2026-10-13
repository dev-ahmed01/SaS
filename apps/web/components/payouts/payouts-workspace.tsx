"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type Plan = {
  id:string; payee_name:string; purpose:string; notes:string|null;
  cadence:"recurring"|"one_time"; amount_paise:number;
  start_month:string; scheduled_on:string|null;
  status:"active"|"paused"|"closed"|"scheduled"|"paid"|"overdue";
  next_status:"active"|"paused"|"closed"|null;
  current_month_due_paise:number;current_month_paid_paise:number;payment_count:number;
};
type PlanPage = {items:Plan[];total:number;limit:number;offset:number;period_month:string};
type Payment = {
  id:string;plan_id:string;payee_name:string;amount_paise:number;
  period_month:string;paid_on:string;payment_method:string;reference_mask:string;
};
type PaymentPage={items:Payment[];total:number;limit:number;offset:number};
type Kind="recurring"|"one_time";
type PaymentMethod="upi"|"bank_transfer"|"cash"|"cheque";
const money=(paise:number)=>(paise/100).toLocaleString("en-IN",{style:"currency",currency:"INR"});
const dateIST=()=>new Intl.DateTimeFormat("en-CA",{
  timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit",
}).format(new Date());
const amountPaise=(value:string):number|null=>{
  if(!/^\d{1,8}(?:\.\d{1,2})?$/.test(value.trim()))return null;
  const [whole,fraction=""]=value.trim().split(".");
  const paise=Number(whole)*100+Number(fraction.padEnd(2,"0"));
  return Number.isSafeInteger(paise)&&paise>0&&paise<=1_000_000_000?paise:null;
};
async function securedPost(path:string,body:unknown):Promise<Response>{
  const auth=await fetch("/api/admin/session",{cache:"no-store"});
  if(!auth.ok)throw Error("Please sign in again to complete this action.");
  const {csrf_token}=await auth.json();
  return fetch(path,{
    method:"POST",credentials:"same-origin",
    headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
    body:JSON.stringify(body),
  });
}

export function PayoutAdd(){
  const router=useRouter();
  const [payee,setPayee]=useState("");
  const [purpose,setPurpose]=useState("");
  const [notes,setNotes]=useState("");
  const [kind,setKind]=useState<Kind>("recurring");
  const [value,setValue]=useState("");
  const [start,setStart]=useState(()=>dateIST().slice(0,7));
  const [scheduled,setScheduled]=useState(dateIST);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const request=useRef<string|null>(null);
  function change(){request.current=null;setError("");setNotice("");}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving)return;
    const amount=amountPaise(value);
    if(!amount){setError("Enter a positive amount in rupees (up to two decimal places).");return;}
    setSaving(true);setError("");setNotice("");
    if(!request.current)request.current=crypto.randomUUID();
    try{
      const response=await securedPost("/api/admin/payouts/plans",{
        request_id:request.current,payee_name:payee,purpose,notes:notes||null,
        cadence:kind,amount_paise:amount,
        start_month:(kind==="recurring"?start:scheduled.slice(0,7))+"-01",
        scheduled_on:kind==="one_time"?scheduled:null,
      });
      if(!response.ok){
        if(response.status===409)throw Error("The plan may already exist. Check All Payouts before retrying.");
        if(response.status===422)throw Error("Check the payee, amount and scheduled dates.");
        throw Error("The payout plan was not confirmed. Please check All Payouts.");
      }
      const result:Plan=await response.json();
      setNotice("Saved "+(result.cadence==="recurring"?"recurring":"one-time")+
        " payout commitment of "+money(result.amount_paise)+
        ". No money has been transferred.");
      setPayee("");setPurpose("");setValue("");setNotes("");request.current=null;
      // Remain on the approved Add screen so Admin can enter another plan.
    }catch(e){setError(e instanceof Error?e.message:"Unable to save payout plan.");}
    finally{setSaving(false);}
  }
  return <section className="content-panel payouts-form" aria-label="Add payout plan">
    <div className="payout-panel-heading">
      <div><h2>Add payout</h2><p className="panel-description">Record a planned outgoing commitment. This does not send money.</p></div>
      <button type="button" className="text-action" onClick={()=>router.push("/payouts/all")}>All payouts →</button>
    </div>
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field form-cell full"><span className="field-label">Payee name *</span>
          <input required aria-label="Payee name" maxLength={160} minLength={2}
            value={payee} placeholder="Enter recipient or organization"
            onChange={e=>{setPayee(e.target.value);change();}}/></label>
        <label className="field"><span className="field-label">Payout type *</span>
          <select aria-label="Payout type" value={kind} onChange={e=>{setKind(e.target.value as Kind);change();}}>
            <option value="recurring">Recurring monthly</option>
            <option value="one_time">One-time</option>
          </select></label>
        <label className="field"><span className="field-label">Amount (₹) *</span>
          <input required aria-label="Payout amount (₹)" inputMode="decimal" value={value}
            placeholder="5000.00" onChange={e=>{setValue(e.target.value);change();}}/></label>
        <label className="field form-cell full"><span className="field-label">Purpose *</span>
          <input required aria-label="Payout purpose" minLength={3} maxLength={240}
            value={purpose} placeholder="e.g. Facility support"
            onChange={e=>{setPurpose(e.target.value);change();}}/></label>
        {kind==="recurring"
          ?<label className="field"><span className="field-label">First payment month (IST) *</span>
            <input required type="month" aria-label="First payment month (IST)" value={start}
              onChange={e=>{setStart(e.target.value);change();}}/></label>
          :<label className="field"><span className="field-label">Scheduled payment date (IST) *</span>
            <input required type="date" aria-label="Scheduled payment date (IST)" value={scheduled}
              onChange={e=>{setScheduled(e.target.value);change();}}/></label>}
        <label className="field form-cell full"><span className="field-label">Notes (optional)</span>
          <textarea rows={3} aria-label="Payout notes" maxLength={800} value={notes}
            onChange={e=>{setNotes(e.target.value);change();}}/></label>
      </div>
      {error&&<p role="alert" className="form-error">{error}</p>}
      {notice&&<p role="status" className="form-success">{notice}</p>}
      <div className="form-actions"><button className="btn btn-primary" type="submit" disabled={saving}>
        {saving?"Saving…":"Save payout plan"}</button></div>
    </form>
    <p className="accounting-footnote">The plan only creates an obligation. Actual disbursement is separately confirmed in All Payouts with a unique payment reference.</p>
  </section>;
}

export function PayoutList({view}:{view:"all"|"active"}){
  const [period,setPeriod]=useState(()=>dateIST().slice(0,7));
  const [offset,setOffset]=useState(0);
  const [refresh,setRefresh]=useState(0);
  const [plans,setPlans]=useState<PlanPage|null>(null);
  const [payments,setPayments]=useState<PaymentPage|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [chosen,setChosen]=useState<Plan|null>(null);
  const [mode,setMode]=useState<"paid"|"pause"|"resume"|"close">("paid");
  const [paymentDate,setPaymentDate]=useState(dateIST);
  const [method,setMethod]=useState<PaymentMethod>("upi");
  const [reference,setReference]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [saving,setSaving]=useState(false);
  const request=useRef<string|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    const params=new URLSearchParams({view,month:period,offset:String(offset),limit:"20"});
    setLoading(true);
    fetch("/api/admin/payouts/plans?"+params,{cache:"no-store",signal:controller.signal})
      .then(async r=>{
        if(!r.ok)throw Error("Unable to load payout plans");
        return await r.json() as PlanPage;
      })
      .then(value=>{if(!controller.signal.aborted){setPlans(value);setError("");}})
      .catch(()=>{if(!controller.signal.aborted)setError("Payout plans could not be loaded.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    if(view==="all"){
      fetch("/api/admin/payouts/payments?limit=30",{
        cache:"no-store",signal:controller.signal,
      }).then(async r=>r.ok?await r.json() as PaymentPage:null)
        .then(value=>{if(!controller.signal.aborted)setPayments(value);})
        .catch(()=>{});
    }
    return ()=>controller.abort();
  },[view,period,offset,refresh]);
  function open(plan:Plan,action:typeof mode){
    setChosen(plan);setMode(action);setPaymentDate(dateIST());setMethod("upi");
    setReference("");setConfirmed(false);setError("");setNotice("");request.current=null;
  }
  function close(){if(!saving){setChosen(null);request.current=null;}}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!chosen||saving)return;
    if(mode==="paid"&&!confirmed){setError("Confirm the money was actually disbursed.");return;}
    setSaving(true);setError("");setNotice("");
    if(!request.current)request.current=crypto.randomUUID();
    const status=mode==="pause"?"paused":mode==="resume"?"active":"closed";
    const path=mode==="paid"
      ?"/api/admin/payouts/plans/"+chosen.id+"/payments"
      :"/api/admin/payouts/plans/"+chosen.id+"/status";
    const payload=mode==="paid"?{
      request_id:request.current,period_month:period+"-01",paid_on:paymentDate,
      payment_method:method,payment_reference:reference,funds_disbursed:true,
    }:{
      request_id:request.current,new_status:status,
    };
    try{
      const response=await securedPost(path,payload);
      if(!response.ok){
        if(response.status===409)throw Error(
          "This payout may already be recorded or have a scheduled change. Refresh and review."
        );
        if(response.status===422)throw Error("Check the month, payment date and reference.");
        throw Error("Action was not confirmed. Check payout history before retrying.");
      }
      setNotice(mode==="paid"
        ?"Recorded the actual outgoing payment with Admin evidence. No transfer was initiated."
        :"Status change scheduled for next IST calendar month. Historical commitments are unchanged.");
      setChosen(null);request.current=null;setRefresh(n=>n+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to confirm action.");}
    finally{setSaving(false);}
  }
  return <section className="payouts-workspace" aria-label={view==="active"?"Active payout plans":"All payout plans"}>
    <div className="payout-list-title"><div>
      <h2>{view==="active"?"Active recurring payouts":"All payouts"}</h2>
      <p>Plans are commitments; only Admin-confirmed outgoing payments count as disbursed.</p>
    </div><label className="field payout-month"><span className="field-label">Accounting month (IST)</span>
      <input aria-label="Payout accounting month" type="month" value={period}
        onChange={e=>{setPeriod(e.target.value);setOffset(0);}}/></label></div>
    {notice&&<p className="form-success" role="status">{notice}</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    <div className="table-scroll"><table className="data-table">
      <thead><tr><th scope="col">Payee</th><th scope="col">Purpose</th>
        <th scope="col">Frequency</th><th scope="col">Commitment</th>
        <th scope="col">Paid in month</th><th scope="col">Status</th>
        <th scope="col">Actions</th></tr></thead>
      <tbody>{loading?<tr><td colSpan={7}>Loading payouts…</td></tr>
        :!plans?.items.length?<tr><td colSpan={7}><div className="empty-state">
          <h3>No payout plans</h3><p>Create an outgoing commitment using Add Payout.</p>
        </div></td></tr>
        :plans.items.map(plan=><tr key={plan.id}>
          <td><strong className="table-name">{plan.payee_name}</strong></td>
          <td>{plan.purpose}</td><td>{plan.cadence==="recurring"?"Monthly":"One-time"}</td>
          <td>{money(plan.amount_paise)}</td><td>{money(plan.current_month_paid_paise)}</td>
          <td><span className={"status-pill "+plan.status}>
            {plan.status==="paid"?"Paid":plan.status==="scheduled"?"Scheduled"
              :plan.status==="overdue"?"Overdue":plan.status==="paused"?"Paused"
              :plan.status==="closed"?"Closed":"Active"}</span>
            {plan.next_status&&<small className="payout-future">Next: {plan.next_status}</small>}
          </td>
          <td><div className="payout-actions">
            {plan.current_month_due_paise>0&&plan.current_month_paid_paise===0&&
              period<=dateIST().slice(0,7)&&
              <button type="button" className="text-action" onClick={()=>open(plan,"paid")}>
                Record paid</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&plan.status==="active"&&
              <button type="button" className="text-action" onClick={()=>open(plan,"pause")}>
                Pause</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&plan.status==="paused"&&
              <button type="button" className="text-action" onClick={()=>open(plan,"resume")}>
                Resume</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&
              ["active","paused"].includes(plan.status)&&
              <button type="button" className="text-action" onClick={()=>open(plan,"close")}>
                Close plan</button>}
          </div></td></tr>)}</tbody>
    </table></div>
    <div className="table-footer paging-footer">
      <span>{plans?plans.total+" payout plans":"Waiting for records"}</span>
      <div className="paging-actions">
        <button className="btn btn-secondary" type="button" disabled={loading||offset===0}
          onClick={()=>setOffset(n=>Math.max(0,n-20))}>Previous</button>
        <button className="btn btn-secondary" type="button"
          disabled={loading||!plans||offset+20>=plans.total}
          onClick={()=>setOffset(n=>n+20)}>Next</button>
      </div>
    </div>
    {view==="all"&&<section className="payout-history" aria-label="Recorded payout history">
      <h3>Recorded outgoing payments</h3>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Payee</th><th>Amount</th><th>Paid on</th>
          <th>Month</th><th>Method</th><th>Reference</th></tr></thead>
        <tbody>{!payments?.items.length?<tr><td colSpan={6}>No outgoing payments have been attested.</td></tr>
          :payments.items.map(payment=><tr key={payment.id}>
            <td>{payment.payee_name}</td><td>{money(payment.amount_paise)}</td>
            <td>{payment.paid_on}</td><td>{payment.period_month.slice(0,7)}</td>
            <td>{payment.payment_method.replace("_"," ")}</td><td>{payment.reference_mask}</td>
          </tr>)}</tbody></table></div>
      <p className="accounting-footnote">These entries were recorded by Admin; they are not bank-verified transfers. Corrections to outgoing payment evidence require an audited adjustment workflow before production.</p>
    </section>}
    {chosen&&<div className="modal-scrim" onMouseDown={event=>{
      if(event.target===event.currentTarget)close();
    }}><section className="edit-modal payout-dialog" role="dialog" aria-modal="true"
        aria-labelledby="payout-modal-title">
      <div className="modal-topline"><span>Payout management</span>
        <button type="button" className="text-action" onClick={close} disabled={saving}
          aria-label="Close payout dialog">Close</button></div>
      <div className="content-panel">
        <h2 id="payout-modal-title">{mode==="paid"?"Record paid payout":"Schedule recurring status"}</h2>
        <p className="panel-description">
          {mode==="paid"?"Only record funds that have already left the Foundation's account. No money is transferred from this app."
            :"This status change begins next calendar month in Asia/Kolkata; past obligations remain unchanged."}
        </p>
        <div className="reversal-facts">
          <div><span>Payee</span><strong>{chosen.payee_name}</strong></div>
          <div><span>Amount</span><strong>{money(chosen.amount_paise)}</strong></div>
          <div><span>Purpose</span><strong>{chosen.purpose}</strong></div>
          <div><span>Frequency</span><strong>{chosen.cadence==="one_time"?"One-time":"Monthly"}</strong></div>
        </div>
        <form onSubmit={submit} aria-label="Confirm payout action">
          {mode==="paid"?<>
            <label className="field"><span className="field-label">Date funds left account (IST) *</span>
              <input required type="date" aria-label="Date funds left account (IST)"
                max={dateIST()} value={paymentDate} onChange={e=>{setPaymentDate(e.target.value);request.current=null;}}/>
            </label>
            <label className="field"><span className="field-label">Payment method *</span>
              <select aria-label="Outgoing payment method" value={method}
                onChange={e=>{setMethod(e.target.value as PaymentMethod);request.current=null;}}>
                <option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option>
                <option value="cash">Cash</option><option value="cheque">Cheque</option>
              </select></label>
            <label className="field"><span className="field-label">Unique transaction / receipt reference *</span>
              <input required minLength={6} maxLength={100} aria-label="Outgoing payment reference"
                placeholder="Bank or numbered cash receipt" value={reference}
                onChange={e=>{setReference(e.target.value);request.current=null;}}/>
            </label>
            <label className="checkbox-field"><input type="checkbox" checked={confirmed}
              onChange={e=>setConfirmed(e.target.checked)}/>
              <span>I checked the Foundation's records and confirm the funds were disbursed.</span>
            </label>
          </>:<p className="accounting-footnote">
            The planned change to <strong>{mode==="pause"?"Paused":mode==="resume"?"Active":"Closed"}</strong> takes effect next month.
            Closing a plan is irreversible from this interface.
          </p>}
          {error&&<p className="form-error" role="alert">{error}</p>}
          <div className="form-actions"><button type="button" className="btn btn-secondary"
            onClick={close} disabled={saving}>Cancel</button>
            <button type="submit" className="btn btn-primary"
              disabled={saving||(mode==="paid"&&!confirmed)}>
              {saving?"Saving…":mode==="paid"?"Record payment":"Confirm status change"}
            </button></div>
        </form>
      </div>
    </section></div>}
  </section>;
}
