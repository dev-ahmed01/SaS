"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { todayISTISO } from "../../lib/crm-dates";

type Prospect={id:string;full_name:string;mobile_number:string;monthly_contribution_paise:number;
  lifecycle_status:string;crm_stage:"active"|"inactive";whatsapp_opt_in:boolean};
type Entry={id:string;sponsor_name:string;amount_paise:number;received_on:string;
  period_month:string;reference_mask:string;message_status:string;payment_method:string};
type Page={items:Entry[];total:number};
const deliveryLabel=(value:string):string=>({
  awaiting_integration:"Awaiting provider setup",
  suppressed:"Not eligible",
  claimed:"Dispatch in progress",
  accepted:"Provider accepted",
  unknown:"Unconfirmed",
  failed:"Provider rejected",
  cancelled:"Cancelled",
  sent:"Sent (confirmed)",
  delivered:"Delivered (confirmed)",
}[value]??"Unknown");

const contributionOptions=[250,500,750,1000,1250,1500,1750,2000,2500,3000,5000,10000];
const amount=(value:number)=>(value/100).toLocaleString("en-IN",{style:"currency",currency:"INR"});
const istDate=todayISTISO;

export function ManualCollections(){
  const [search,setSearch]=useState("");
  const [results,setResults]=useState<Prospect[]>([]);
  const [lookupState,setLookupState]=useState<"idle"|"searching"|"found"|"missing"|"failed">("idle");
  const [selected,setSelected]=useState<Prospect|null>(null);
  const [rupees,setRupees]=useState("");
  const [customAmount,setCustomAmount]=useState(false);
  const [receivedOn,setReceivedOn]=useState(()=>istDate());
  const [period,setPeriod]=useState(()=>istDate().slice(0,7));
  const [method,setMethod]=useState("upi");
  const [reference,setReference]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [success,setSuccess]=useState("");
  const requestId=useRef<string|null>(null);
  useEffect(()=>{
    if(search.trim().length<2||selected){setResults([]);setLookupState("idle");return;}
    setLookupState("searching");
    const controller=new AbortController();
    const timeout=setTimeout(()=>{
      fetch("/api/admin/prospects?"+new URLSearchParams({q:search.trim(),limit:"30"}),{
        cache:"no-store",signal:controller.signal,
      }).then(async r=>{if(!r.ok)throw Error("Search unavailable");return await r.json();})
        .then(data=>{if(!controller.signal.aborted){const entries=data.items as Prospect[];setResults(entries);setLookupState(entries.length?"found":"missing");}})
        .catch(()=>{if(!controller.signal.aborted){setResults([]);setLookupState("failed");}});
    },250);
    return ()=>{clearTimeout(timeout);controller.abort();};
  },[search,selected]);

  function select(prospect:Prospect){
    setSelected(prospect);setSearch(prospect.full_name);setResults([]);
    setRupees("");setCustomAmount(false);setError("");
    requestId.current=null;
  }
  function update(){setError("");setSuccess("");requestId.current=null;}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving)return;
    if(!selected||selected.crm_stage!=="active"){
      const inactive=results.some(p=>p.crm_stage==="inactive" &&
        (p.full_name.toLowerCase()===search.trim().toLowerCase()||p.mobile_number===search.trim()));
      setError(inactive?"This prospect is inactive. Reactivate them in Prospects before recording a collection.":
        "This name is not a selected, active prospect. Search and select a registered prospect first.");return;
    }
    const receivedISO=receivedOn;
    if(!receivedISO||receivedISO>istDate()){
      setError("Select a valid received date, not in the future.");return;
    }
    const trimmed=rupees.trim();
    if(!/^\d{1,8}(?:\.\d{1,2})?$/.test(trimmed)){setError("Enter a valid amount in rupees, in ₹250 steps.");return;}
    const [whole,fraction=""]=trimmed.split(".");
    const paise=Number(whole)*100+Number(fraction.padEnd(2,"0"));
    if(!Number.isSafeInteger(paise)||paise<25000||paise>1_000_000_000
      ||paise%25000!==0){
      setError("Record ₹250, ₹500, ₹750, or another positive multiple of ₹250.");return;
    }
    setSaving(true);setError("");setSuccess("");
    if(!requestId.current)requestId.current=crypto.randomUUID();
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const {csrf_token}=await session.json();
      const result=await fetch("/api/admin/collections",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({
          request_id:requestId.current,prospect_id:selected.id,
          amount_paise:paise,period_month:period+"-01",received_on:receivedISO,
          payment_method:method,receipt_reference:reference.trim()||null,
          funds_confirmed:true,
        }),
      });
      if(!result.ok){
        if(result.status===409){
          setError("This receipt or request may already exist. Check All Collections before retrying.");
        }else if(result.status===422){
          setError("Check the billing month, receipt date and amount. Use ₹250 multiples.");
        }else{
          setError("The collection was not confirmed. Check All Collections before retrying.");
        }
        return;
      }
      const data:Entry=await result.json();
      setSuccess("Recorded "+amount(data.amount_paise)+" for "+data.sponsor_name+
        ". "+(data.message_status==="awaiting_integration"
          ?"WhatsApp confirmation is awaiting provider setup; it has not been sent."
          :data.message_status==="suppressed"
            ?"No WhatsApp confirmation was prepared because consent is missing."
            :"WhatsApp status: "+deliveryLabel(data.message_status)+
              ". View authenticated delivery status in Reminders."));
      setSelected(null);setSearch("");setRupees("");setCustomAmount(false);setReference("");
      requestId.current=null;
    }catch{setError("Connection interrupted. Check All Collections before retrying.");}
    finally{setSaving(false);}
  }
  return <div className="manual-collections-workspace">
    <section className="content-panel" aria-label="Record a manual collection">
      <h2>Record Collection</h2>
      <p className="crm-form-summary">Select an active sponsor. Saving a collection confirms the Foundation received these funds.</p>
      <form onSubmit={submit}>
        <div className="form-grid collection-entry-grid">
          <div className="form-cell collection-sponsor">
            <label className="field"><span className="field-label">Sponsor <span className="required">*</span></span>
              <input aria-label="Search sponsor" autoComplete="off" required value={search}
                placeholder="Search by name or mobile number"
                onChange={e=>{setSearch(e.target.value);setSelected(null);setRupees("");setCustomAmount(false);update();}}/>
            </label>
            {selected&&<p className="manual-selected">Selected: {selected.full_name} · {selected.mobile_number}
              · {selected.whatsapp_opt_in?"WhatsApp consent recorded":"No WhatsApp consent"}</p>}
            {!selected&&results.length>0&&<div className="manual-search-results" aria-label="Matching prospects">
              {results.map(candidate=><button type="button" key={candidate.id}
                role="option" aria-selected={false} disabled={candidate.crm_stage!=="active"} onClick={()=>select(candidate)}>
                <strong>{candidate.full_name}</strong><span>{candidate.mobile_number} · {candidate.crm_stage==="active"?"Active":"Inactive — cannot record collection"}</span>
              </button>)}
            </div>}
            {!selected&&search.trim().length>=2&&lookupState==="missing"&&<p className="form-error" role="status">
              No registered prospect found for “{search.trim()}”. Add the person in Prospects first.</p>}
            {!selected&&results.some(p=>p.crm_stage==="inactive")&&<p className="form-error" role="status">
              Inactive prospects cannot receive collections. Reactivate the person from their Prospect Details page.</p>}
            {!selected&&lookupState==="failed"&&<p className="form-error" role="alert">Prospect lookup unavailable. Please retry.</p>}
            {!selected&&lookupState==="searching"&&<p role="status" className="crm-muted">Searching prospects…</p>}
          </div>
          <label className="field collection-method"><span className="field-label">Payment method *</span>
            <select aria-label="Payment method" value={method} onChange={e=>{setMethod(e.target.value);update();}}>
              <option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
            </select></label>
          <div className="field collection-amount"><label className="field-label" htmlFor="collection-amount">Amount received (₹) *</label>
            <select id="collection-amount" aria-label="Amount received (₹)" required value={customAmount?"other":rupees}
              onChange={e=>{setCustomAmount(e.target.value==="other");setRupees(e.target.value==="other"?"":e.target.value);update();}}>
              <option value="" disabled>Select amount</option>
              {contributionOptions.map(value=><option key={value} value={value}>{value.toLocaleString("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:0})}</option>)}
              <option value="other">Other multiple of ₹250…</option>
            </select>
            {customAmount&&<input aria-label="Custom collection amount (₹)" required type="number" inputMode="numeric"
              min="250" step="250" max="10000000" value={rupees} placeholder="Enter a multiple of ₹250"
              onChange={e=>{setRupees(e.target.value);update();}}/>}
          </div>
          <label className="field collection-reference"><span className="field-label">Transaction ID</span>
            <input aria-label="Transaction reference" minLength={6} maxLength={100}
              value={reference} placeholder="Enter transaction ID if available"
              onChange={e=>{setReference(e.target.value);update();}}/></label>          <label className="field collection-month"><span className="field-label">Sponsorship month *</span>
            <input aria-label="Sponsorship month" required type="month" max={istDate().slice(0,7)}
              value={period} onChange={e=>{setPeriod(e.target.value);update();}}/>
          </label>
          <label className="field collection-date"><span className="field-label">Date Paid (IST) *</span>
            <input aria-label="Received date" required type="date" max={istDate()}
              value={receivedOn} onChange={e=>{setReceivedOn(e.target.value);update();}}/>
          </label>


        </div>
        {error&&<p className="form-error" role="alert">{error}</p>}
        {success&&<p className="form-success" role="status">{success}</p>}
        <div className="manual-collections-submit"><button type="submit" disabled={saving}
          className="btn btn-primary">{saving?"Recording…":"Save Collection"}</button></div>
      </form>
    </section>
  </div>;
}
