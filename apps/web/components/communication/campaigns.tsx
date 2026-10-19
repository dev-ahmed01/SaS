"use client";

import { useEffect, useState } from "react";
import { apiGet, apiWrite, istDisplay } from "./types";
import type { Campaign } from "./types";

export function CommunicationCampaigns({revision}:{revision:number}){
  const [items,setItems]=useState<Campaign[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState("");
  const [reload,setReload]=useState(0);
  useEffect(()=>{
    setLoading(true);
    apiGet<Campaign[]>("/campaigns").then(setItems)
      .catch(()=>setError("Could not load saved campaigns."))
      .finally(()=>setLoading(false));
  },[revision,reload]);
  async function cancel(item:Campaign){
    if(!window.confirm("Cancel this communication plan? It will remain in the audit log."))return;
    setBusy(item.id);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+item.id+"/cancel","POST",{});
      setNotice("Campaign plan cancelled. No messages were dispatched.");
      setReload(x=>x+1);
    }catch(e){setError(e instanceof Error?e.message:"Could not cancel.");}
    finally{setBusy("");}
  }
  return <section className="comm-panel" aria-label="Communication campaigns">
    <div className="comm-panel-header"><div><h2>Campaigns</h2>
      <p>Drafts and plans across all audiences.</p></div>
      <button type="button" className="btn btn-secondary" onClick={()=>setReload(x=>x+1)}>
        Refresh</button>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
    <div className="comm-campaign-table-scroll"><table className="data-table comm-campaign-table">
      <thead><tr>{["Campaign","Channel","Audience","Recipients","Planned IST","Status","Action"].map(h=>
        <th key={h} scope="col">{h}</th>)}</tr></thead>
      <tbody>{loading?<tr><td colSpan={7}>Loading campaigns…</td></tr>:!items.length?
        <tr><td colSpan={7} className="comm-empty">No saved campaigns yet. Start in Compose.</td></tr>:
        items.map(item=><tr key={item.id}>
          <td><div className="comm-campaign-title"><strong>{item.title}</strong>
            <span>{item.category.replace("_"," ")}</span></div></td>
          <td>{item.channel==="whatsapp"?"WhatsApp":"Email"}</td>
          <td>{item.audience} · {item.segment}</td>
          <td>{item.eligible_snapshot}/{item.candidate_snapshot}</td>
          <td>{item.planned_for?istDisplay(item.planned_for):"—"}</td>
          <td><span className={"status-pill "+(item.status==="cancelled"?"inactive":"scheduled")}>
            {item.status==="scheduled"?"Planned":item.status==="cancelled"?"Cancelled":"Draft"}
          </span></td>
          <td>{item.status==="cancelled"?"—":<button type="button"
            className="comm-text-button" disabled={busy===item.id}
            onClick={()=>cancel(item)}>Cancel</button>}</td>
        </tr>)}</tbody>
    </table></div>
    <p className="comm-muted comm-history-footnote">
      Planned dates are saved in IST, but plans are not automatically sent.
      Provider delivery must be configured and explicitly activated separately.
    </p>
  </section>;
}
