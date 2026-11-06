"use client";

import {FormEvent,useEffect,useState} from "react";

type StaffRole="owner"|"crm"|"finance"|"messaging"|"viewer";
type Staff={id:string;email:string;role:StaffRole;is_active:boolean;created_at:string};
const roles:StaffRole[]=["owner","crm","finance","messaging","viewer"];
const labels:Record<StaffRole,string>={
  owner:"Owner — full access",
  crm:"CRM — prospects and promoters",
  finance:"Finance — collections and payouts",
  messaging:"Messaging — campaigns and reminders",
  viewer:"Viewer — read-only"
};

export function TeamAccess({csrf}:{csrf:string}){
  const [members,setMembers]=useState<Staff[]>([]);
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [role,setRole]=useState<StaffRole>("crm");
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [busyId,setBusyId]=useState<string|null>(null);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [myEmail,setMyEmail]=useState("");
  async function refresh(){
    const [session,res]=await Promise.all([
      fetch("/api/admin/session",{cache:"no-store"}),
      fetch("/api/admin/users",{cache:"no-store"})
    ]);
    if(!session.ok||!res.ok)throw Error("Staff access could not be loaded.");
    const sessionValue=await session.json();
    setMyEmail(sessionValue.email??"");
    setMembers(await res.json() as Staff[]);
  }
  useEffect(()=>{
    let active=true;
    void Promise.all([
      fetch("/api/admin/session",{cache:"no-store"}),
      fetch("/api/admin/users",{cache:"no-store"})
    ]).then(async ([session,res])=>{
      if(!session.ok||!res.ok)throw Error();
      const identity=await session.json();
      const people=await res.json() as Staff[];
      if(active){setMyEmail(identity.email??"");setMembers(people);}
    }).catch(()=>{if(active)setError("Could not load staff. Reload settings.");})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[]);
  async function create(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving||password.length<12||!csrf)return;
    setSaving(true);setError("");setNotice("");
    try{
      const res=await fetch("/api/admin/users",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({email:email.trim(),password,role}),
      });
      if(!res.ok)throw Error(res.status===409?"Staff email already registered.":"Could not create staff account.");
      setEmail("");setPassword("");setNotice("Staff account created with the selected permissions.");
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:"Staff account could not be created.");}
    finally{setSaving(false);}
  }
  async function change(member:Staff,next:Partial<Staff>){
    if(busyId||!csrf||member.email===myEmail)return;
    setBusyId(member.id);setError("");setNotice("");
    try{
      const res=await fetch("/api/admin/users/"+member.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({
          role:next.role??member.role,is_active:next.is_active??member.is_active,
        }),
      });
      if(!res.ok)throw Error(res.status===409
        ?"This change would remove the last active owner, or cannot change your own role."
        :"Staff permissions could not be updated.");
      await refresh();setNotice("Staff permissions updated. Deactivated accounts lose active sessions.");
    }catch(e){setError(e instanceof Error?e.message:"Unable to update staff.");}
    finally{setBusyId(null);}
  }
  return <section className="content-panel team-access" aria-label="Staff access management">
    <h2>Staff access</h2>
    <p className="panel-description">Create separate accounts for CRM, finance, messaging
      and read-only staff. Only owners can manage access. Passwords are never shown again.</p>
    <form onSubmit={create} className="team-create-form">
      <div className="form-grid">
        <label className="field"><span className="field-label">Staff email *</span>
          <input type="email" required maxLength={320} value={email}
            onChange={e=>setEmail(e.target.value)} autoComplete="off"/></label>
        <label className="field"><span className="field-label">Temporary password (12+ characters) *</span>
          <input type="password" required minLength={12} maxLength={256}
            value={password} onChange={e=>setPassword(e.target.value)} autoComplete="new-password"/></label>
        <label className="field"><span className="field-label">Permission role *</span>
          <select value={role} onChange={e=>setRole(e.target.value as StaffRole)}>
            {roles.map(value=><option key={value} value={value}>{labels[value]}</option>)}
          </select></label>
      </div>
      <div className="form-actions"><button type="submit" className="btn btn-primary"
        disabled={saving||!csrf}>{saving?"Creating…":"Create staff account"}</button></div>
    </form>
    {loading&&<p role="status">Loading staff accounts…</p>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    {notice&&<p role="status" className="form-success">{notice}</p>}
    {!loading&&<div className="table-scroll"><table className="data-table">
      <thead><tr><th scope="col">Email</th><th scope="col">Role</th>
        <th scope="col">Status</th><th scope="col">Action</th></tr></thead>
      <tbody>{members.map(member=><tr key={member.id}>
        <td>{member.email}{member.email===myEmail?" (You)":""}</td>
        <td><select aria-label={"Role for "+member.email} value={member.role}
          disabled={busyId!==null||member.email===myEmail}
          onChange={e=>void change(member,{role:e.target.value as StaffRole})}>
          {roles.map(value=><option key={value} value={value}>{labels[value]}</option>)}
        </select></td>
        <td>{member.is_active?"Active":"Disabled"}</td>
        <td><button type="button" className="btn btn-secondary"
          disabled={busyId!==null||member.email===myEmail}
          onClick={()=>void change(member,{is_active:!member.is_active})}>
          {member.is_active?"Deactivate":"Reactivate"}</button></td>
      </tr>)}</tbody>
    </table></div>}
  </section>;
}
