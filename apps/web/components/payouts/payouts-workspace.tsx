"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { dateInputFromISO, dateInputToISO, formatCRMDate } from "../../lib/crm-dates";

type Plan = {
  id:string; payee_name:string; purpose:string; notes:string|null;
  cadence:"recurring"|"one_time"; amount_paise:number;
  start_month:string; scheduled_on:string|null;
  status:"active"|"paused"|"closed"|"scheduled"|"paid"|"overdue";
  next_status:"active"|"paused"|"closed"|null;
  current_month_due_paise:number;current_month_paid_paise:number;payment_count:number;
};
type PlanPage = {items:Plan[];total:number;limit:number;offset:number;period_month:string};
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
  const [first,setFirst]=useState("");
  const [last,setLast]=useState("");
  const [purpose,setPurpose]=useState("");
  const [method,setMethod]=useState<PaymentMethod>("upi");
  const [value,setValue]=useState("");
  const [paidOn,setPaidOn]=useState(()=>dateInputFromISO(dateIST()));
  const [utr,setUtr]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const request=useRef<string|null>(null);
  function change(){request.current=null;setError("");setNotice("");}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving)return;
    const paise=amountPaise(value);
    const paid=dateInputToISO(paidOn);
    if(!paise){setError("Enter a valid positive payout amount.");return;}
    if(!paid||paid>dateIST()){setError("Enter the actual payment date in DD/MM/YY, not in the future.");return;}
    if(first.trim().length<2||purpose.trim().length<3||utr.trim().length<6){
      setError("Enter the payee, purpose and UTR/reference number.");return;
    }
    setSaving(true);setError("");setNotice("");
    if(!request.current)request.current=crypto.randomUUID();
    try{
      const response=await securedPost("/api/admin/payouts/quick",{
        request_id:request.current,first_name:first.trim(),last_name:last.trim(),
        purpose:purpose.trim(),amount_paise:paise,paid_on:paid,
        payment_method:method,payment_reference:utr.trim().toUpperCase(),
        funds_disbursed:true,
      });
      if(!response.ok)throw Error(response.status===409
        ?"This payout or UTR was already recorded. Check All Payouts."
        :response.status===422?"Check the date and payment reference.":"Could not record payout.");
      setNotice("Recorded "+money(paise)+" paid to "+[first,last].filter(Boolean).join(" ")+".");
      setFirst("");setLast("");setPurpose("");setValue("");setUtr("");
      request.current=null;
    }catch(e){setError(e instanceof Error?e.message:"Could not record payout.");}
    finally{setSaving(false);}
  }
  return <section className="content-panel payouts-form" aria-label="Record payout">
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field"><span className="field-label">Payee First Name *</span>
          <input required minLength={2} maxLength={80} aria-label="Payee First Name"
            value={first} onChange={e=>{setFirst(e.target.value);change();}}/></label>
        <label className="field"><span className="field-label">Payee Last Name</span>
          <input maxLength={80} aria-label="Payee Last Name"
            value={last} onChange={e=>{setLast(e.target.value);change();}}/></label>
        <div className="payout-inline-row form-cell full">
          <label className="field"><span className="field-label">Type *</span>
            <select aria-label="Payout payment type" value={method}
              onChange={e=>{setMethod(e.target.value as PaymentMethod);change();}}>
              <option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option><option value="cheque">Cheque</option>
            </select></label>
          <label className="field"><span className="field-label">Amount (₹) *</span>
            <input required inputMode="decimal" aria-label="Payout amount (₹)"
              value={value} onChange={e=>{setValue(e.target.value);change();}}/></label>
          <label className="field"><span className="field-label">Purpose *</span>
            <input required minLength={3} maxLength={240} aria-label="Payout purpose"
              value={purpose} onChange={e=>{setPurpose(e.target.value);change();}}/></label>
        </div>
        <label className="field"><span className="field-label">Date (DD/MM/YY) *</span>
          <input required value={paidOn} placeholder="DD/MM/YY"
            pattern="[0-9]{2}/[0-9]{2}/[0-9]{2}" aria-label="Payout date (DD/MM/YY)"
            onChange={e=>{setPaidOn(e.target.value);change();}}/></label>
        <label className="field"><span className="field-label">UTR / Reference Number *</span>
          <input required minLength={6} maxLength={100} aria-label="UTR"
            value={utr} onChange={e=>{setUtr(e.target.value);change();}}/></label>
      </div>
      {error&&<p role="alert" className="form-error">{error}</p>}
      {notice&&<p role="status" className="form-success">{notice}</p>}
      <div className="form-actions"><button type="submit" className="btn btn-primary" disabled={saving}>
        {saving?"Recording…":"Save Payout"}</button></div>
    </form>
  </section>;
}

export function PayoutList({view}:{view:"all"|"active"}){
  const [period,setPeriod]=useState(()=>dateIST().slice(0,7));
  const [offset,setOffset]=useState(0);
  const [refresh,setRefresh]=useState(0);
  const [plans,setPlans]=useState<PlanPage|null>(()=>recentSnapshot<PlanPage>(
    "/api/admin/payouts/plans?"+new URLSearchParams({view,month:dateIST().slice(0,7),offset:"0",limit:"20"})
  ));
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [chosen,setChosen]=useState<Plan|null>(null);
  const [mode,setMode]=useState<"paid"|"pause"|"resume"|"close">("paid");
  const [paymentDate,setPaymentDate]=useState(()=>dateInputFromISO(dateIST()));
  const [method,setMethod]=useState<PaymentMethod>("upi");
  const [reference,setReference]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [saving,setSaving]=useState(false);
  const request=useRef<string|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    const params=new URLSearchParams({view,month:period,offset:String(offset),limit:"20"});
    const key="/api/admin/payouts/plans?"+params;
    const cached=recentSnapshot<PlanPage>(key);
    setPlans(cached);setLoading(!cached);
    fetch(key,{cache:"no-store",signal:controller.signal})
      .then(async r=>{
        if(!r.ok)throw Error("Unable to load payout plans");
        return await r.json() as PlanPage;
      })
      .then(value=>{if(!controller.signal.aborted){rememberSnapshot(key,value);setPlans(value);setError("");}})
      .catch(()=>{if(!controller.signal.aborted)setError("Payout plans could not be loaded.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[view,period,offset,refresh]);
  function open(plan:Plan,action:typeof mode){
    if(loading)return; // Stale navigation snapshots are read-only until refresh completes.
    setChosen(plan);setMode(action);setPaymentDate(dateInputFromISO(dateIST()));setMethod("upi");
    setReference("");setConfirmed(false);setError("");setNotice("");request.current=null;
  }
  function close(){if(!saving){setChosen(null);request.current=null;}}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!chosen||saving)return;
    if(mode==="paid"&&!confirmed){setError("Confirm the money was actually disbursed.");return;}
    const normalizedPaymentDate=dateInputToISO(paymentDate);
    if(mode==="paid"&&(!normalizedPaymentDate||normalizedPaymentDate>dateIST())){
      setError("Use an actual payment date in DD/MM/YY.");return;
    }
    setSaving(true);setError("");setNotice("");
    if(!request.current)request.current=crypto.randomUUID();
    const status=mode==="pause"?"paused":mode==="resume"?"active":"closed";
    const path=mode==="paid"
      ?"/api/admin/payouts/plans/"+chosen.id+"/payments"
      :"/api/admin/payouts/plans/"+chosen.id+"/status";
    const payload=mode==="paid"?{
      request_id:request.current,period_month:period+"-01",paid_on:normalizedPaymentDate,
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
      <tbody>{loading&&!plans?<tr><td colSpan={7}>Loading payouts…</td></tr>
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
              <button type="button" className="text-action" disabled={loading} onClick={()=>open(plan,"paid")}>
                Record paid</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&plan.status==="active"&&
              <button type="button" className="text-action" disabled={loading} onClick={()=>open(plan,"pause")}>
                Pause</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&plan.status==="paused"&&
              <button type="button" className="text-action" disabled={loading} onClick={()=>open(plan,"resume")}>
                Resume</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&
              ["active","paused"].includes(plan.status)&&
              <button type="button" className="text-action" disabled={loading} onClick={()=>open(plan,"close")}>
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
    {chosen&&<div className="modal-scrim" onMouseDown={event=>{
      if(event.target===event.currentTarget)close();
    }}><section className="edit-modal payout-dialog" role="dialog" aria-modal="true"
        aria-labelledby="payout-modal-title">
      <div className="modal-topline"><span>Payout management</span>
        <button type="button" className="text-action" onClick={close} disabled={saving}
          aria-label="Close payout dialog">Close</button></div>
      <div className="content-panel">
        <h2 id="payout-modal-title">{mode==="paid"?"Record paid payout":"Schedule recurring status"}</h2>

         <p className="panel-description">{mode==="paid"?"Record confirmed payments only.":"Applies from next month."}</p>
        <div className="reversal-facts">
          <div><span>Payee</span><strong>{chosen.payee_name}</strong></div>
          <div><span>Amount</span><strong>{money(chosen.amount_paise)}</strong></div>
          <div><span>Purpose</span><strong>{chosen.purpose}</strong></div>
          <div><span>Frequency</span><strong>{chosen.cadence==="one_time"?"One-time":"Monthly"}</strong></div>
        </div>
        <form onSubmit={submit} aria-label="Confirm payout action">
          {mode==="paid"?<>
            <label className="field"><span className="field-label">Date funds left account (IST) *</span>
              <input required type="text" inputMode="numeric" placeholder="DD/MM/YY"
                pattern="[0-9]{2}/[0-9]{2}/[0-9]{2}" aria-label="Date funds left account (DD/MM/YY)"
                value={paymentDate}
                onChange={e=>{setPaymentDate(e.target.value);request.current=null;}}/>
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
          </>:mode==="close"?<p className="accounting-footnote">Closing a plan is irreversible.</p>:null}
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
