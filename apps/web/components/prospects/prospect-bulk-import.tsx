"use client";

import { useState } from "react";
import Link from "next/link";

import { COLUMNS, parsePeople } from "./prospect-import-parser.mjs";
import type { BulkPerson } from "./prospect-import-parser.mjs";

type BulkRow={
  row:number;full_name:string;mobile_number:string;
  status:"ready"|"blocked"|"already_imported"|"added";
  detail:string|null;prospect_id:string|null;
  promoter_id:string|null;promoter_name:string|null;
};
type BulkResult={
  preview_only:boolean;total:number;ready:number;already_imported:number;
  added:number;blocked:number;default_amount_paise:number;
  default_start_month:string;rows:BulkRow[];
};

function statusLabel(row:BulkRow):string{
  return row.status==="ready"?"Ready":row.status==="added"?"Added":
    row.status==="already_imported"?"Previously added":"Needs correction";
}

export function ProspectBulkImport(){
  const [rows,setRows]=useState<BulkPerson[]>([]);
  const [batchId,setBatchId]=useState("");
  const [fileName,setFileName]=useState("");
  const [pasted,setPasted]=useState("");
  const [preview,setPreview]=useState<BulkResult|null>(null);
  const [result,setResult]=useState<BulkResult|null>(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [changed,setChanged]=useState(false);

  async function loadFile(file:File|undefined){
    setError("");setPreview(null);setResult(null);setRows([]);setChanged(false);
    if(!file)return;
    setFileName(file.name);
    if(file.size>64000){setError("Use a CSV smaller than 64 KB and at most 100 rows.");return;}
    try{
      const parsed=parsePeople(await file.text());
      setRows(parsed);setBatchId(crypto.randomUUID());setChanged(true);
    }catch(err){setError(err instanceof Error?err.message:"Invalid CSV file.");}
  }
  function loadPasted(){
    setError("");setPreview(null);setResult(null);setRows([]);setChanged(false);
    if(pasted.length>64000){setError("Paste at most 64 KB and 100 rows.");return;}
    try{
      const parsed=parsePeople(pasted);
      setFileName("Pasted spreadsheet");
      setRows(parsed);setBatchId(crypto.randomUUID());setChanged(true);
    }catch(err){setError(err instanceof Error?err.message:"Invalid pasted table.");}
  }
  async function submit(commit:boolean){
    if(!rows.length||!batchId||busy||commit&&(!preview||preview.blocked>0||result))return;
    setBusy(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired. Sign in again.");
      const {csrf_token}=await session.json();
      const body:Record<string,unknown>={batch_id:batchId,commit,rows};
      if(commit){
        body.expected_month=preview?.default_start_month;
        body.expected_default_amount_paise=preview?.default_amount_paise;
        body.expected_promoter_ids=preview?.rows.map(item=>item.promoter_id??null);
      }
      const response=await fetch("/api/admin/prospects/bulk",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify(body),
      });
      const payload=await response.json();
      if(!response.ok){
        const detail=payload?.detail;
        if(detail?.rows&&Array.isArray(detail.rows)){
          setPreview(current=>current?{...current,blocked:detail.rows.filter(
            (item:BulkRow)=>item.status==="blocked"
          ).length,rows:detail.rows}:null);
        }
        const validation=Array.isArray(detail)?detail.map((issue:{loc?:unknown[];msg?:string})=>{
          const index=issue.loc?.[2]; const field=issue.loc?.[3];
          return typeof index==="number"?"Row "+(index+2)+(field?" ("+String(field)+")":"")+": "+(issue.msg??"Invalid value"):"Invalid import value";
        }).join("; "):null;
        throw Error(typeof detail==="string"?detail:validation??detail?.message??
          (response.status===422?"Check the row values and try again.":"Import could not be confirmed."));
      }
      if(commit){setResult(payload as BulkResult);setChanged(false);}
      else{setPreview(payload as BulkResult);}
    }catch(err){setError(err instanceof Error?err.message:"Connection problem.");}
    finally{setBusy(false);}
  }
  function downloadTemplate(){
    const csv=COLUMNS.join(",")+"\r\n"+
      '"","","","","","","","",""\r\n';
    const url=URL.createObjectURL(new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"}));
    const link=document.createElement("a");
    link.href=url;link.download="sas-prospect-import-template.csv";
    document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
  }
  const shown=result??preview;
  return <section className="crm-list crm-bulk-import" aria-label="Bulk import prospects">
    <div className="crm-panel-heading">
      <div><h2>Import prospects</h2><p className="panel-description">
        Upload a CSV or paste rows from a spreadsheet. Review before saving up to 100 contacts.</p></div>
      <Link href="/prospects" className="btn btn-secondary">Back to Prospects</Link>
    </div>
    <div className="crm-bulk-toolbar">
      <label className="field"><span className="field-label">CSV file *</span>
        <input aria-label="Prospect CSV file" type="file" accept=".csv,text/csv"
          disabled={busy} onChange={e=>void loadFile(e.target.files?.[0])}/></label>
      <button className="btn btn-secondary" type="button" onClick={downloadTemplate}>
        Download CSV template</button>
      <button className="btn btn-primary" type="button" disabled={!rows.length||busy||!!result}
        onClick={()=>void submit(false)}>
        {busy?"Checking…":"Preview import"}</button>
    </div>
    <div className="crm-bulk-paste">
      <label className="field"><span className="field-label">Or paste spreadsheet rows</span>
        <textarea aria-label="Paste prospect rows" rows={4} value={pasted}
          disabled={busy||Boolean(result)}
          placeholder={COLUMNS.join(",")+"\nSample,Person,91,9876543210,,Bengaluru,250,2026-11,"}
          onChange={e=>setPasted(e.target.value)}/></label>
      <button type="button" className="btn btn-secondary" disabled={!pasted.trim()||busy||Boolean(result)}
        onClick={loadPasted}>Load pasted rows</button>
      <p className="field-helper">Paste the CSV header and rows, or copy columns directly
        from a spreadsheet (tab-separated). For Excel files, save as CSV or copy the nine columns here.
        Use sponsorship in rupees, Start Month as YYYY-MM or e.g. Nov-26, and an exact active promoter name (optional).</p>
    </div>
    <p className="panel-description">
      Names may repeat, but mobile numbers must be unique. Blank sponsorship amounts use the CRM
      default. All new records start Inactive; no WhatsApp messages are sent.</p>
    {fileName&&<p className="crm-muted">{fileName} · {rows.length} rows
      {changed?" · not yet saved":""}</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    {shown&&<div className="crm-bulk-results" aria-live="polite">
      <h3>{result?"Import results":"Preview results"}</h3>
      <p>{shown.ready} ready · {shown.already_imported} previously added ·
        {" "}{shown.blocked} blocked · {shown.added} added</p>
      <p className="crm-muted">Default: ₹{shown.default_amount_paise/100} per month,
        starting {shown.default_start_month.slice(0,7)}.</p>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Row</th><th>Name</th><th>Mobile</th><th>Sponsorship</th><th>Start Month</th><th>Promoter</th>
          <th>Status</th></tr></thead>
        <tbody>{shown.rows.map(item=><tr key={item.row}>
          <td>{item.row}</td><td>{item.full_name}</td><td>{item.mobile_number}</td>
          <td>₹{(rows[item.row-1]?.monthly_contribution_paise??
            shown.default_amount_paise)/100}</td>
          <td>{(rows[item.row-1]?.start_month??shown.default_start_month).slice(0,7)}</td>
          <td>{item.promoter_name??"Unassigned"}</td>
          <td>{item.prospect_id&&result?<Link href={"/prospects/"+item.prospect_id}>
            {statusLabel(item)}</Link>:statusLabel(item)}
            {item.detail&&<small className="table-subtitle">{item.detail}</small>}</td>
        </tr>)}</tbody></table></div>
      {!result&&<div className="crm-bulk-actions">
        <button className="btn btn-primary" type="button" disabled={
          busy||shown.blocked>0||shown.ready===0
        } onClick={()=>void submit(true)}>Confirm &amp; add {shown.ready} prospects</button>
        {shown.blocked>0&&<p className="form-error">Correct the CSV and preview it again.
          No records will be saved while a row is blocked.</p>}
      </div>}
      {result&&<p className="form-success" role="status">
        Import confirmed. {result.added} new prospects added.</p>}
    </div>}
  </section>;
}
