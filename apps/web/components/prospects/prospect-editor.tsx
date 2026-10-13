"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Prospect } from "./prospects-types";

type EditValues = {
  full_name: string;
  mobile_number: string;
  whatsapp_number: string;
  area_city: string;
  amount_rupees: string;
  next_followup_on: string;
  last_contact_on: string;
  notes: string;
  upi_id: string;
  whatsapp_opt_in: boolean;
};

const empty: EditValues = {
  full_name: "", mobile_number: "", whatsapp_number: "",
  area_city: "", amount_rupees: "", next_followup_on: "",
  last_contact_on: "", notes: "", upi_id: "", whatsapp_opt_in: false,
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
      area_city:initial.area_city,
      amount_rupees:toRupees(initial.monthly_contribution_paise),
      next_followup_on:initial.next_followup_on ?? "",
      last_contact_on:initial.last_contact_on ?? "",
      notes:initial.notes ?? "", upi_id:"", whatsapp_opt_in:initial.whatsapp_opt_in
    } : {...empty});
  const [ready, setReady] = useState(Boolean(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [upiError, setUpiError] = useState("");
  const [upiBusy, setUpiBusy] = useState(false);
  const [current, setCurrent] = useState<Prospect | undefined>(initial);

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
        area_city:values.area_city.trim(),
        ...(!current || !legacyUnchanged
          ? {monthly_contribution_paise:amount}
          : {}),
        next_followup_on:values.next_followup_on || null,
        last_contact_on:values.last_contact_on || null,
        notes:values.notes.trim() || null,
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
    <p className="panel-description">Manage contact details and the agreed monthly contribution. A new prospect stays New until the first recorded positive contribution. Both commitments and incoming recorded contributions start at ₹250 and use ₹250 increments.</p>
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field"><span className="field-label">Full name <span className="required">*</span></span><input required minLength={2} maxLength={160} value={values.full_name} onChange={e=>update("full_name",e.target.value)} placeholder="Enter full name"/></label>
        <label className="field"><span className="field-label">Mobile number <span className="required">*</span></span><input required type="tel" value={values.mobile_number} onChange={e=>update("mobile_number",e.target.value)} placeholder="+91 98765 43210"/></label>
        <label className="field"><span className="field-label">WhatsApp number (optional)</span><input type="tel" value={values.whatsapp_number} onChange={e=>update("whatsapp_number",e.target.value)} placeholder="+91 98765 43210"/></label>
        <label className="field"><span className="field-label">Area / City <span className="required">*</span></span><input required minLength={2} maxLength={120} value={values.area_city} onChange={e=>update("area_city",e.target.value)} placeholder="Enter area or city"/></label>
        <label className="field"><span className="field-label">Monthly contribution (₹) <span className="required">*</span></span><input required type="number" step={current && current.monthly_contribution_paise%25000!==0?"any":"250"}
          min={current && current.monthly_contribution_paise<25000?"0.01":"250"}
          max="10000000" value={values.amount_rupees} onChange={e=>update("amount_rupees",e.target.value)} placeholder="Amount"/></label>
        <label className="field"><span className="field-label">Next follow-up date</span><input type="date" value={values.next_followup_on} onChange={e=>update("next_followup_on",e.target.value)}/></label>
        <label className="field"><span className="field-label">Last contact date</span><input type="date" value={values.last_contact_on} onChange={e=>update("last_contact_on",e.target.value)}/></label>
        {!current && <label className="field"><span className="field-label">UPI ID (optional)</span><input maxLength={193} value={values.upi_id} onChange={e=>update("upi_id",e.target.value)} placeholder="name@bank"/></label>}
        <label className="field form-cell full"><span className="field-label">Notes</span><textarea rows={3} maxLength={1500} value={values.notes} onChange={e=>update("notes",e.target.value)} placeholder="Enter any notes about this prospect"/></label>
        <label className="checkbox-field form-cell full"><input type="checkbox" checked={values.whatsapp_opt_in} onChange={e=>update("whatsapp_opt_in",e.target.checked)}/><span>WhatsApp communication consent recorded (no messages sent in this phase)</span></label>
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
