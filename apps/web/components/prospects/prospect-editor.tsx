"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Prospect } from "./prospects-types";

type EditValues = {
  full_name: string;
  mobile_number: string;
  whatsapp_number: string;
  amount_rupees: string;
  upi_id: string;
  whatsapp_opt_in: boolean;
};

const contributionOptions = [250,500,750,1000,1250,1500,1750,2000,2500,3000,5000,10000] as const;

const empty: EditValues = {
  full_name: "", mobile_number: "", whatsapp_number: "",
  amount_rupees: "", upi_id: "", whatsapp_opt_in: false,
};

function toRupees(paise: number): string {
  return (paise / 100).toFixed(2).replace(/\.00$/, "");
}

function toPaise(amount: string): number | null {
  if (!/^\d{1,8}(?:\.\d{1,2})?$/.test(amount.trim())) return null;
  const [whole, fraction = ""] = amount.trim().split(".");
  const paise = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(paise) && paise >= 25000 && paise <= 1000000000
    && paise % 25000 === 0 ? paise : null;
}

function normalizePhone(input: string): string | null {
  const trimmed = input.trim().replace(/[\s-]/g, "");
  if (trimmed === "") return null;
  if (/^\d{10}$/.test(trimmed)) return "+91" + trimmed;
  return /^\+[1-9]\d{7,14}$/.test(trimmed) ? trimmed : null;
}

async function csrfToken(): Promise<string> {
  const result = await fetch("/api/admin/session", {cache:"no-store"});
  if (!result.ok) throw Error("Your session expired. Sign in again.");
  return (await result.json()).csrf_token;
}

export function ProspectEditor({
  initial, onSaved, onCancel,
}: {initial?: Prospect; onSaved: () => void; onCancel?: () => void}) {
  const registrationKey=useRef<string | null>(null);
  const [values, setValues] = useState<EditValues>(() => initial
    ? {
      full_name:initial.full_name,
      mobile_number:initial.mobile_number,
      whatsapp_number:initial.whatsapp_number ?? "",
      amount_rupees:toRupees(initial.monthly_contribution_paise),
      upi_id:"", whatsapp_opt_in:initial.whatsapp_opt_in
    } : {...empty});
  const [ready, setReady] = useState(Boolean(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [upiError, setUpiError] = useState("");
  const [upiBusy, setUpiBusy] = useState(false);
  const [current, setCurrent] = useState<Prospect | undefined>(initial);
  const [promoterSearch,setPromoterSearch] = useState("");
  const [promoters,setPromoters] = useState<{id:string;full_name:string}[]>([]);
  const [promoterId,setPromoterId] = useState("");
  const [promoterError,setPromoterError] = useState("");

  useEffect(()=>{
    const controller = new AbortController();
    const timer = setTimeout(()=>{
      const params = new URLSearchParams({active:"true",q:promoterSearch,limit:"50"});
      fetch("/api/admin/promoters?"+params,{cache:"no-store",signal:controller.signal})
        .then(async response=>{
          if(!response.ok)throw Error("Promoters unavailable");
          return await response.json();
        })
        .then(page=>{if(!controller.signal.aborted){setPromoters(page.items);setPromoterError("");}})
        .catch(()=>{if(!controller.signal.aborted)setPromoterError("Could not load promoters.");});
    },200);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[promoterSearch]);

  useEffect(() => {
    if (initial) return;
    let active = true;
    fetch("/api/admin/settings", {cache:"no-store"})
      .then(async response => {
        if (!response.ok) throw Error("Unable to load organisation defaults.");
        const configuration = await response.json();
        if (active) {
          setValues(prev => ({
            ...prev, amount_rupees:toRupees(configuration.default_contribution_paise),
          }));
          setReady(true);
        }
      }).catch(() => {if(active)setError("Unable to load the default contribution. Try refreshing.");});
    return () => {active=false;};
  },[initial]);

  function update<K extends keyof EditValues>(field: K, value: EditValues[K]) {
    setValues(previous => ({...previous, [field]:value}));
    setError("");
  }

  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || saving) return;
    const mobile = normalizePhone(values.mobile_number);
    const whatsapp = normalizePhone(values.whatsapp_number);
    const amount = toPaise(values.amount_rupees);
    if (!mobile || (values.whatsapp_number.trim() && !whatsapp)) {
      setError("Use a valid mobile number (10-digit Indian number or international + format).");
      return;
    }
    const legacyUnchanged = Boolean(current
      && values.amount_rupees === toRupees(current.monthly_contribution_paise));
    if (amount === null && !legacyUnchanged) {
      setError("Monthly sponsorship must be ₹250, ₹500, ₹750, or another positive multiple of ₹250.");
      return;
    }
    setSaving(true);setError("");
    try {
      const body: Record<string,unknown> = {
        full_name:values.full_name.trim(),
        mobile_number:mobile,
        whatsapp_number:whatsapp,
        ...(!current || !legacyUnchanged
          ? {monthly_contribution_paise:amount}
          : {}),
        whatsapp_opt_in:values.whatsapp_opt_in,
      };
      if (current) body.version = current.version;
      else {
        if (!registrationKey.current) registrationKey.current=crypto.randomUUID();
        body.request_id=registrationKey.current;
        body.upi_ids=values.upi_id.trim() ? [values.upi_id.trim()] : [];
      }
      const csrf = await csrfToken();
      const response = await fetch(
        current ? "/api/admin/prospects/" + current.id : "/api/admin/prospects", {
          method:current?"PATCH":"POST", credentials:"same-origin",
          headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
          body:JSON.stringify(body)
        }
      );
      if (!response.ok) {
        setError(
          response.status === 409
            ? "This prospect has changed. Close and reopen the form before editing."
            : response.status === 422
              ? "Please review the fields, especially the UPI ID and contact numbers."
              : "Unable to save the prospect. Please try again."
        );
        return;
      }
      const saved:Prospect = await response.json();
      setCurrent(saved);
      if(promoterId){
        const assigned=await fetch("/api/admin/promoters/"+promoterId+"/sponsors/"+saved.id,{
          method:"PUT",credentials:"same-origin",
          headers:{"X-CSRF-Token":csrf,"If-Match":String(saved.version)},
        });
        if(!assigned.ok){
          setError("Prospect saved, but the promoter could not be linked. Retry the assignment or use the Promoters list.");
          return;
        }
        setPromoterId("");
      }
      if (!current) {
        registrationKey.current=null;
        setValues({...empty, amount_rupees:values.amount_rupees});
      }
      onSaved();
    }catch{
      setError("Connection problem. The save could not be confirmed.");
    }finally{setSaving(false);}
  }

  async function changeUpi(id?:string) {
    if (!current || upiBusy) return;
    setUpiBusy(true);setUpiError("");
    try {
      const csrf = await csrfToken();
      const url = "/api/admin/prospects/" + current.id + "/upi-ids" +
        (id ? "/" + id : "");
      const response = await fetch(url,{
        method:id?"DELETE":"POST",credentials:"same-origin",
        headers:{"X-CSRF-Token":csrf,...(id
          ? {"If-Match":String(current.version)}
          : {"Content-Type":"application/json"})},
        ...(id?{}:{body:JSON.stringify({
          version:current.version,upi_id:values.upi_id.trim()
        })})
      });
      if (!response.ok) {
        setUpiError(response.status === 409
          ? "This record changed or the UPI ID is already registered. Reopen it to refresh."
          : "Unable to update UPI identifiers.");
        return;
      }
      const updated:Prospect=await response.json();
      setCurrent(updated);
      setValues(v=>({...v,upi_id:""}));
      onSaved();
    } catch{setUpiError("Could not update the UPI identifier.");}
    finally{setUpiBusy(false);}
  }

  return <section className="content-panel prospect-form-panel" aria-label={current?"Edit Prospect":"Add Prospect"}>
    <h2>{current?"Edit Prospect":"Add Prospect"}</h2>
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field"><span className="field-label">Full name <span className="required">*</span></span><input required minLength={2} maxLength={160} value={values.full_name} onChange={e=>update("full_name",e.target.value)} placeholder="Enter full name"/></label>
        <label className="field"><span className="field-label">Mobile number <span className="required">*</span></span><input required type="tel" value={values.mobile_number} onChange={e=>update("mobile_number",e.target.value)} placeholder="+91 98765 43210"/></label>
        <label className="field"><span className="field-label">Monthly contribution (₹) <span className="required">*</span></span>
          <select aria-label="Monthly contribution (₹)" required disabled={!ready}
            value={contributionOptions.includes(Number(values.amount_rupees) as typeof contributionOptions[number])?values.amount_rupees:"other"}
            onChange={e=>update("amount_rupees",e.target.value==="other"?"":e.target.value)}>
            {contributionOptions.map(amount=><option key={amount} value={amount}>{amount.toLocaleString("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:0})}</option>)}
            <option value="other">Other multiple of ₹250…</option>
          </select>
        </label>
        {!contributionOptions.includes(Number(values.amount_rupees) as typeof contributionOptions[number])&&
          <label className="field form-cell full"><span className="field-label">Custom monthly contribution (₹) *</span>
            <input required type="number" min="250" step="250" max="10000000" value={values.amount_rupees}
              onChange={e=>update("amount_rupees",e.target.value)} placeholder="Enter a multiple of 250"/>
          </label>}
        <details className="optional-details">
          <summary>More details (optional)</summary>
          <div className="optional-fields">
            <label className="field"><span className="field-label">WhatsApp number</span><input type="tel" value={values.whatsapp_number} onChange={e=>update("whatsapp_number",e.target.value)} placeholder="Same as mobile if empty"/></label>
            <div className="field full"><label className="field-label" htmlFor="promoter-search">Link to promoter</label>
              <input id="promoter-search" value={promoterSearch} onChange={e=>{setPromoterSearch(e.target.value);setPromoterId("");}} placeholder="Search promoters by name or number"/>
              <select aria-label="Assign promoter" value={promoterId} onChange={e=>setPromoterId(e.target.value)}>
                <option value="">No new assignment</option>
                {promoters.map(promoter=><option key={promoter.id} value={promoter.id}>{promoter.full_name}</option>)}
              </select>
              {promoterError&&<span className="form-error" role="status">{promoterError}</span>}
            </div>
            {!current&&<label className="field"><span className="field-label">UPI ID</span><input maxLength={193} value={values.upi_id} onChange={e=>update("upi_id",e.target.value)} placeholder="name@bank"/></label>}
            <label className="checkbox-field full"><input type="checkbox" checked={values.whatsapp_opt_in} onChange={e=>update("whatsapp_opt_in",e.target.checked)}/><span>WhatsApp communication consent recorded</span></label>
          </div>
        </details>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="form-actions">
        {onCancel && <button type="button" className="btn btn-secondary" disabled={saving} onClick={onCancel}>Cancel</button>}
        {!current && <button type="button" className="btn btn-secondary" disabled={saving} onClick={()=>setValues(v=>({...empty,amount_rupees:v.amount_rupees}))}>Clear</button>}
        <button className="btn btn-primary" type="submit" disabled={saving || !ready}>{saving?"Saving…":current?"Save Changes":"Add Prospect"}</button>
      </div>
    </form>
    {initial && current && <div className="upi-manager">
      <h3>Payment identifiers</h3>
      <p>Only masked identifiers are stored. They must be verified against bank records in Phase 8 before automatic payment matching.</p>
      <div className="upi-items">{current.upi_ids.length === 0 && <span className="muted">No UPI IDs registered.</span>}
        {current.upi_ids.map(upi=><div key={upi.id} className="upi-row"><span>{upi.masked_vpa} · Unverified</span><button className="text-action" type="button" disabled={upiBusy} onClick={()=>changeUpi(upi.id)}>Remove</button></div>)}
      </div>
      {current.upi_ids.length < 5 && <div className="upi-input-row"><label className="field"><span className="field-label">Add UPI ID</span><input value={values.upi_id} onChange={e=>update("upi_id",e.target.value)} placeholder="name@bank" maxLength={193}/></label><button type="button" className="btn btn-secondary" disabled={!values.upi_id.trim()||upiBusy} onClick={()=>changeUpi()}>Add ID</button></div>}
      {upiError && <p className="form-error" role="alert">{upiError}</p>}
    </div>}
  </section>;
}
