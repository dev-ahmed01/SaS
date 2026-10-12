"use client";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "../../components/ui/icon";

export default function LoginPage() {
  const router = useRouter();
  const [email,setEmail] = useState("");
  const [password,setPassword] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  useEffect(()=>{
    let active=true;
    fetch("/api/admin/session",{cache:"no-store"}).then(r=>{
      if(active && r.ok){router.replace("/prospects");}
    }).catch(()=>{});
    return ()=>{active=false;};
  },[router]);
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(busy)return;
    setBusy(true);setError("");
    try {
      const result=await fetch("/api/admin/login",{
        method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",
        body:JSON.stringify({email,password})
      });
      if(!result.ok){
        setError(result.status===429?"Too many attempts. Please try again later.":result.status===503?"Sign-in is temporarily unavailable.":"Unable to sign in. Check your details and try again.");
        return;
      }
      router.replace("/prospects");
      
    } catch {
      setError("Connection problem. Please try again.");
    } finally {setBusy(false);}
  }
  return <main className="login-layout">
    <section className="login-illustration" aria-label="Sponsor a Salah welcome">
      <div className="login-brand"><Icon name="moon" size={38}/><h1>Sponsor a Salah</h1><p>Masjid Charity Management</p></div>
      <div className="login-mosque" aria-hidden="true"><span className="minaret minaret-one"/><span className="dome dome-one"/><span className="minaret minaret-two"/><span className="dome dome-two"/></div>
    </section>
    <section className="login-card" aria-labelledby="login-title">
      <span className="login-mark"><Icon name="moon" size={32}/></span>
      <h2 id="login-title">Welcome back</h2><p>Sign in to manage your masjid sponsorships.</p>
      <form onSubmit={submit}>
        <div className="login-fields">
          <label className="field"><span className="field-label">Email address</span><input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="Enter your email address"/></label>
          <label className="field"><span className="field-label">Password</span><input type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password"/></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy?"Signing in…":"Sign In"}</button>
      </form>
      <p className="login-disclaimer">Authorized Emlen Foundation Admin access only.</p>
    </section>
  </main>;
}
