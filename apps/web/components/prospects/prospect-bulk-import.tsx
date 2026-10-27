"use client";

import { useState } from "react";
import Link from "next/link";

type BulkPerson={
  full_name:string;mobile_number:string;area_city:string;
  email?:string;monthly_contribution_paise?:number;start_month?:string;
};
type BulkRow={
  row:number;full_name:string;mobile_number:string;
  status:"ready"|"blocked"|"already_imported"|"added";
  detail:string|null;prospect_id:string|null;
};
type BulkResult={
  preview_only:boolean;total:number;ready:number;already_imported:number;
  added:number;blocked:number;default_amount_paise:number;
  default_start_month:string;rows:BulkRow[];
};

const COLUMNS=["Name","Mobile","City","Email","Sponsorship INR","Start Month"];
const accepted=new Set(COLUMNS.map(c=>c.toLowerCase()));

function parseCSV(input:string):string[][]{
  const text=input.replace(/^\uFEFF/,"");
  const rows:string[][]=[];
  let values:string[]=[],cell="",inside=false;
  for(let i=0;i<text.length;i++){
    const char=text[i];
    if(char==='"'){
      if(inside&&text[i+1]==='"'){cell+='"';i++;}
      else if(!inside&&!cell){inside=true;}
      else if(inside){inside=false;}
      else throw Error("Unexpected quote in CSV. Use doubled quotes inside quoted cells.");
    }else if(char===","&&!inside){values.push(cell);cell="";}
    else if((char==="\n"||char==="\r")&&!inside){
      if(char==="\r"&&text[i+1]==="\n")i++;
      values.push(cell);cell="";
      if(values.some(value=>value.trim()))rows.push(values);
      values=[];
    }else{cell+=char;}
  }
  if(inside)throw Error("CSV has an unclosed quoted field.");
  values.push(cell);
  if(values.some(value=>value.trim()))rows.push(values);
  return rows;
}

function parsePeople(text:string):BulkPerson[]{
  // Spreadsheet copy-paste is usually tab-separated; file uploads remain CSV.
  const firstLine=text.split(/\r?\n/,1)[0];
  const matrix=firstLine.includes("\t")&&!firstLine.includes(",")
    ?text.replace(/\r/g,"").split("\n").filter(row=>row.trim())
      .map(row=>row.split("\t"))
    :parseCSV(text);
  if(matrix.length<2)throw Error("CSV needs a header and at least one person.");
  if(matrix.length>101)throw Error("Use a maximum of 100 people in one import.");
  const header=matrix[0].map(s=>s.trim().toLowerCase());
  if(header.some(h=>!accepted.has(h))||new Set(header).size!==header.length){
    throw Error("Use the exact template columns without extra or repeated headers.");
  }
  if(!header.includes("name")||!header.includes("mobile")){
    throw Error("Name and Mobile columns are required.");
  }
  return matrix.slice(1).map((values,index)=>{
    if(values.length!==header.length)throw Error("Row "+(index+2)+" has the wrong column count.");
    const record=Object.fromEntries(header.map((key,i)=>[key,values[i].trim()]));
    const person:BulkPerson={
      full_name:record.name,mobile_number:record.mobile,
      area_city:record.city??"",
    };
    if(record.email)person.email=record.email;
    if(record["sponsorship inr"]){
      const raw=record["sponsorship inr"];
      if(!/^[0-9]+$/.test(raw))throw Error("Row "+(index+2)+": amount must be whole rupees.");
      const rupees=Number(raw);
      if(!Number.isSafeInteger(rupees)||rupees<=0||rupees%250!==0){
        throw Error("Row "+(index+2)+": sponsorship must be ₹250 or a multiple of ₹250.");
      }
      person.monthly_contribution_paise=rupees*100;
    }
    if(record["start month"]){
      const month=record["start month"];
      if(!/^\d{4}-\d{2}$/.test(month))throw Error(
        "Row "+(index+2)+": Start Month must be YYYY-MM."
      );
      person.start_month=month+"-01";
    }
    if(!person.full_name||!/^\+[1-9]\d{7,14}$/.test(person.mobile_number)){
      throw Error("Row "+(index+2)+": enter a name and international phone (e.g. +919876543210).");
    }
    return person;
  });
}

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
        throw Error(typeof detail==="string"?detail:detail?.message??
          (response.status===422?"Check the row values and try again.":"Import could not be confirmed."));
      }
      if(commit){setResult(payload as BulkResult);setChanged(false);}
      else{setPreview(payload as BulkResult);}
    }catch(err){setError(err instanceof Error?err.message:"Connection problem.");}
    finally{setBusy(false);}
  }
  function downloadTemplate(){
    const csv=COLUMNS.join(",")+"\r\n"+
      '"Ayesha Khan","+919876543210","Bengaluru","","250",""\r\n';
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
          placeholder={'Name,Mobile,City,Email,Sponsorship INR,Start Month\nExample Sponsor,+919876543210,Bengaluru,,250,'}
          onChange={e=>setPasted(e.target.value)}/></label>
      <button type="button" className="btn btn-secondary" disabled={!pasted.trim()||busy||Boolean(result)}
        onClick={loadPasted}>Load pasted rows</button>
      <p className="field-helper">Paste the CSV header and rows, or copy columns directly
        from a spreadsheet (tab-separated). Preview and confirm to save.</p>
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
        <thead><tr><th>Row</th><th>Name</th><th>Mobile</th><th>Sponsorship</th>
          <th>Status</th></tr></thead>
        <tbody>{shown.rows.map(item=><tr key={item.row}>
          <td>{item.row}</td><td>{item.full_name}</td><td>{item.mobile_number}</td>
          <td>₹{(rows[item.row-1]?.monthly_contribution_paise??
            shown.default_amount_paise)/100}</td>
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
