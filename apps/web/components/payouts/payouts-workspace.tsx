"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { formatCRMDate } from "../../lib/crm-dates";
import { exportAllCsv } from "../../lib/export-csv";
import { PayoutPaymentHistory } from "./payout-payment-history";
import { useDialogFocus } from "../../lib/dialog-focus";
import type { FieldOptionPage, FieldOption } from "../settings/field-options";

type Plan = {
  id:string; payee_name:string; purpose:string; notes:string|null;
  cadence:"recurring"|"one_time"; amount_paise:number;
  start_month:string; scheduled_on:string|null;
  status:"active"|"paused"|"closed"|"scheduled"|"paid"|"overdue";
  next_status:"active"|"paused"|"closed"|null;
  current_month_due_paise:number;current_month_paid_paise:number;payment_count:number;
  voided?:boolean;
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
  const [purposeOptionId,setPurposeOptionId]=useState("");
  const [purposeOptions,setPurposeOptions]=useState<FieldOption[]>([]);
  const [purposeLoading,setPurposeLoading]=useState(true);
  const [purposeError,setPurposeError]=useState("");
  const [purposeRetry,setPurposeRetry]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setPurposeLoading(true);setPurposeError("");
    fetch("/api/admin/settings/field-options?field_key=payout_purpose&include_inactive=false",{
      cache:"no-store",signal:controller.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("Purpose options could not be loaded.");
      return await response.json() as FieldOptionPage;
    }).then(page=>{if(!controller.signal.aborted)setPurposeOptions(page.items??[]);})
      .catch(()=>{if(!controller.signal.aborted)setPurposeError("Could not load approved purposes.");})
      .finally(()=>{if(!controller.signal.aborted)setPurposeLoading(false);});
    return()=>controller.abort();
  },[purposeRetry]);
  const [method,setMethod]=useState<PaymentMethod>("upi");
  const [value,setValue]=useState("");
  const [paidOn,setPaidOn]=useState(()=>dateIST());
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
    const paid=paidOn;
    if(!paise){setError("Enter a valid positive payout amount.");return;}
    if(!paid||paid>dateIST()){setError("Select a valid payment date, not in the future.");return;}
    if(first.trim().length<2||!purposeOptionId||!purpose||utr.trim().length<6){
      setError("Enter the payee, choose an approved purpose and add the UTR/reference.");return;
    }
    setSaving(true);setError("");setNotice("");
    if(!request.current)request.current=crypto.randomUUID();
    try{
      const response=await securedPost("/api/admin/payouts/quick",{
        request_id:request.current,first_name:first.trim(),last_name:last.trim(),
        purpose:purpose.trim(),purpose_option_id:purposeOptionId,
        amount_paise:paise,paid_on:paid,
        payment_method:method,payment_reference:utr.trim().toUpperCase(),
        funds_disbursed:true,
      });
      if(!response.ok)throw Error(response.status===409
        ?"This payout or UTR was already recorded. Check All Payouts."
        :response.status===422?"Check the date and payment reference.":"Could not record payout.");
      setNotice("Recorded "+money(paise)+" paid to "+[first,last].filter(Boolean).join(" ")+".");
      setFirst("");setLast("");setPurpose("");setPurposeOptionId("");setValue("");setUtr("");
      request.current=null;
    }catch(e){setError(e instanceof Error?e.message:"Could not record payout.");}
    finally{setSaving(false);}
  }
  return <section className="content-panel payouts-form payout-phase3-form" aria-label="Record payout">
    <div className="payout-phase3-form-intro">
      <span className="crm-directory-eyebrow">OUTGOING PAYMENTS</span>
      <h2>Record an outgoing payment</h2>
      <p>Record a payment only after the funds have actually left the Foundation's account.
        This form records evidence and does not initiate a bank transfer.</p>
    </div>
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field"><span className="field-label">Payee First Name *</span>
          <input required minLength={2} maxLength={80} aria-label="Payee First Name"
            value={first} onChange={e=>{setFirst(e.target.value);change();}}/></label>
        <label className="field"><span className="field-label">Payee Last Name</span>
          <input maxLength={80} aria-label="Payee Last Name"
            value={last} onChange={e=>{setLast(e.target.value);change();}}/></label>
        <div className="payout-inline-row form-cell full">
          <label className="field"><span className="field-label">Payment method *</span>
            <select aria-label="Payout payment type" value={method}
              onChange={e=>{setMethod(e.target.value as PaymentMethod);change();}}>
              <option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option><option value="cheque">Cheque</option>
            </select></label>
          <label className="field"><span className="field-label">Amount (₹) *</span>
            <input required inputMode="decimal" aria-label="Payout amount (₹)"
              value={value} onChange={e=>{setValue(e.target.value);change();}}/></label>
          <label className="field"><span className="field-label">UTR / Reference Number *</span>
            <input required minLength={6} maxLength={100} aria-label="UTR"
              value={utr} onChange={e=>{setUtr(e.target.value);change();}}/></label>
        </div>
        <div className="payout-inline-row payout-last-row form-cell full">
          <label className="field"><span className="field-label">Date paid *</span>
            <input type="date" max={dateIST()} required value={paidOn}
              aria-label="Payout date" onChange={e=>{setPaidOn(e.target.value);change();}}/></label>
          <label className="field"><span className="field-label">Purpose *</span>
            <select required aria-label="Payout purpose" disabled={purposeLoading||Boolean(purposeError)}
              value={purposeOptionId} onChange={e=>{
                const option=purposeOptions.find(row=>row.id===e.target.value);
                setPurposeOptionId(option?.id??"");setPurpose(option?.label??"");change();
              }}>
              <option value="" disabled>{purposeLoading?"Loading approved purposes…":"Select purpose"}</option>
              {purposeOptions.map(option=><option value={option.id} key={option.id}>
                {option.label}
              </option>)}
            </select>
            {purposeError&&<span className="form-error" role="alert">{purposeError}{" "}
              <button type="button" className="text-action"
                onClick={()=>setPurposeRetry(x=>x+1)}>Retry</button></span>}
            {!purposeLoading&&!purposeError&&!purposeOptions.length&&
              <span className="crm-muted">No active purposes. An owner can add choices in Settings.</span>}
          </label>
        </div>
      </div>
      {error&&<p role="alert" className="form-error">{error}</p>}
      {notice&&<p role="status" className="form-success">{notice}</p>}
      <div className="payout-phase3-form-bottom">
        <div className="form-actions"><button type="submit" className="btn btn-primary" disabled={saving||purposeLoading||Boolean(purposeError)||!purposeOptionId}>
        {saving?"Recording…":"Save Payout"}</button></div>
      </div>
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
  const [exporting,setExporting]=useState(false);
  const [exportNotice,setExportNotice]=useState("");
  const [chosen,setChosen]=useState<Plan|null>(null);
  const [mode,setMode]=useState<"paid"|"pause"|"resume"|"close">("paid");
  const [paymentDate,setPaymentDate]=useState(()=>dateIST());
  const [method,setMethod]=useState<PaymentMethod>("upi");
  const [reference,setReference]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [saving,setSaving]=useState(false);
  const planDialogRef=useDialogFocus<HTMLElement>(Boolean(chosen),()=>{if(!saving)close();});
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
  async function exportPlans(){
    if(exporting)return;
    setExporting(true);setError("");setExportNotice("Preparing payout-plan export…");
    try{
      const params=new URLSearchParams({view,month:period});
      const count=await exportAllCsv<Plan>({
        url:"/api/admin/payouts/plans?"+params,
        filename:"sas-payout-plans-"+view+"-"+period+".csv",
        onProgress:(done,total)=>setExportNotice("Exporting "+done+" of "+total+" payout plans…"),
        columns:[
          {title:"Payee",value:p=>p.payee_name},
          {title:"Purpose",value:p=>p.purpose},
          {title:"Cadence",value:p=>p.cadence},
          {title:"Commitment INR",value:p=>p.amount_paise/100},
          {title:"Paid this month INR",value:p=>p.current_month_paid_paise/100},
          {title:"Due this month INR",value:p=>p.current_month_due_paise/100},
          {title:"Status",value:p=>p.status},
          {title:"Next status",value:p=>p.next_status},
          {title:"Start month",value:p=>p.start_month},
          {title:"Scheduled date",value:p=>p.scheduled_on},
        ]
      });
      setExportNotice(count+" payout plans exported.");
    }catch(e){setExportNotice("");setError(e instanceof Error?e.message:"Export failed.");}
    finally{setExporting(false);}
  }
  async function exportPayments(){
    if(exporting)return;
    setExporting(true);setError("");setExportNotice("Preparing recorded payments export…");
    try{
      type PaymentRow={payee_name:string;period_month:string;paid_on:string;
        amount_paise:number;payment_method:string;reference_mask:string;evidence:string};
      const count=await exportAllCsv<PaymentRow>({
        url:"/api/admin/payouts/payments",
        filename:"sas-actual-payout-payments-all.csv",
        onProgress:(done,total)=>setExportNotice("Exporting "+done+" of "+total+" payments…"),
        columns:[
          {title:"Payee",value:p=>p.payee_name},
          {title:"Accounting month",value:p=>p.period_month},
          {title:"Date paid",value:p=>p.paid_on},
          {title:"Amount INR",value:p=>p.amount_paise/100},
          {title:"Method",value:p=>p.payment_method},
          {title:"Reference (masked)",value:p=>p.reference_mask},
          {title:"Evidence",value:p=>p.evidence}
        ]
      });
      setExportNotice(count+" payments exported.");
    }catch(e){setExportNotice("");setError(e instanceof Error?e.message:"Payment export failed.");}
    finally{setExporting(false);}
  }

  function open(plan:Plan,action:typeof mode){
    if(loading)return; // Stale navigation snapshots are read-only until refresh completes.
    setChosen(plan);setMode(action);setPaymentDate(dateIST());setMethod("upi");
    setReference("");setConfirmed(false);setError("");setNotice("");request.current=null;
  }
  function close(){if(!saving){setChosen(null);request.current=null;}}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!chosen||saving)return;
    if(mode==="paid"&&!confirmed){setError("Confirm the money was actually disbursed.");return;}
    const normalizedPaymentDate=paymentDate;
    if(mode==="paid"&&(!normalizedPaymentDate||normalizedPaymentDate>dateIST())){
      setError("Select an actual payment date.");return;
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
  return <><section className="payouts-workspace" aria-label={view==="active"?"Active payout plans":"All payout plans"}>
    <div className="payout-list-title payout-phase3-list-header">
      <div className="payout-phase3-title">
        <span className="crm-directory-eyebrow">PAYOUT REGISTER</span>
        <h2>{view==="active"?"Active recurring payouts":"All payouts"}</h2>
        <p>{view==="active"?
          "Review active monthly commitments and schedule future changes.":
          "Review commitments and recorded disbursements with their audit history."}</p>
      </div>
      <div className="payout-phase3-count" role="status" aria-live="polite">
        <strong>{loading&&!plans?"…":plans?.total??0}</strong>
        <span>{view==="active"?"active recurring plans":"plans in this view"}</span>
      </div>
    </div>
    <div className="payout-phase3-filters" aria-label="Payout filters and exports">
      <div className="payout-list-toolbar">
        <label className="field payout-month">
          <span className="field-label">Accounting month (IST)</span>
          <input aria-label="Payout accounting month" type="month" value={period}
            onChange={e=>{setPeriod(e.target.value);setOffset(0);}}/>
        </label>
        <div className="payout-export-actions">
          <button type="button" className="btn btn-secondary btn-action" disabled={exporting}
            onClick={()=>void exportPlans()}>{exporting?"Exporting…":"Export payout plans"}</button>
          <button type="button" className="btn btn-secondary btn-action" disabled={exporting}
            onClick={()=>void exportPayments()}>{exporting?"Exporting…":"Export payments"}</button>
        </div>
      </div>
    </div>
    {exportNotice&&<p className="crm-muted" role="status">{exportNotice}</p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    <div className="table-scroll payout-phase3-table-scroll"><table className="data-table payout-phase3-table">
      <thead><tr><th scope="col">Payee</th><th scope="col">Purpose</th>
        <th scope="col">Frequency</th><th scope="col">Commitment</th>
        <th scope="col">Paid in month</th><th scope="col">Status</th>
        <th scope="col">Actions</th></tr></thead>
      <tbody>{loading&&!plans?<tr><td colSpan={7}>Loading payouts…</td></tr>
        :!plans?.items.length?<tr><td colSpan={7}><div className="empty-state">
          <h3>No payout plans</h3><p>Create an outgoing commitment using Add Payout.</p>
        </div></td></tr>
        :plans.items.map(plan=><tr key={plan.id}>
          <td><strong className="table-name">{plan.payee_name}</strong>
            <small className="payout-phase3-payee-caption">{plan.cadence==="recurring"?
              "Recurring commitment":"One-time commitment"}</small></td>
          <td>{plan.purpose}</td><td>{plan.cadence==="recurring"?"Monthly":"One-time"}</td>
          <td>{money(plan.amount_paise)}</td><td>{money(plan.current_month_paid_paise)}</td>
          <td><span className={"status-pill "+plan.status}>
            {plan.voided?"Voided / corrected":plan.status==="paid"?"Paid":plan.status==="scheduled"?"Scheduled"
              :plan.status==="overdue"?"Overdue":plan.status==="paused"?"Paused"
              :plan.status==="closed"?"Closed":"Active"}</span>
            {plan.next_status&&<small className="payout-future">Next: {plan.next_status}</small>}
          </td>
          <td><div className="payout-actions">
            {plan.current_month_due_paise>0&&plan.current_month_paid_paise===0&&
              period<=dateIST().slice(0,7)&&
              <button type="button" className="btn btn-secondary btn-row-action" disabled={loading} onClick={()=>open(plan,"paid")}>
                Record paid</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&plan.status==="active"&&
              <button type="button" className="btn btn-secondary btn-row-action" disabled={loading} onClick={()=>open(plan,"pause")}>
                Pause</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&plan.status==="paused"&&
              <button type="button" className="btn btn-secondary btn-row-action" disabled={loading} onClick={()=>open(plan,"resume")}>
                Resume</button>}
            {plan.cadence==="recurring"&&!plan.next_status&&
              ["active","paused"].includes(plan.status)&&
              <button type="button" className="btn btn-secondary btn-row-action" disabled={loading} onClick={()=>open(plan,"close")}>
                Close plan</button>}
          </div></td></tr>)}</tbody>
    </table></div>
    <div className="table-footer paging-footer">
      <span>{plans?
        "Showing "+(plans.total?offset+1:0)+"–"+
          Math.min(offset+20,plans.total)+" of "+plans.total+" plans":
        "Loading payout plans…"}</span>
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
        aria-labelledby="payout-modal-title" ref={planDialogRef} tabIndex={-1}>
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
              <input required type="date" max={dateIST()} aria-label="Date funds left account"
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
  </section>
  {view==="all"&&<PayoutPaymentHistory onCorrected={()=>setRefresh(n=>n+1)}/>}
  </>;
}
