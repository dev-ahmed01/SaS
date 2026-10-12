import Link from "next/link";
import { Icon } from "../../components/ui/icon";
import { TextField, PreviewButton } from "../../components/ui/primitives";

export const metadata={title:"Sign in preview | Sponsor a Salah"};

export default function LoginPreview() {
  return <main className="login-layout">
    <section className="login-illustration" aria-label="Sponsor a Salah welcome">
      <div className="login-brand"><Icon name="moon" size={38}/><h1>Sponsor a Salah</h1><p>Masjid Charity Management</p></div>
      <div className="login-mosque" aria-hidden="true"><span className="minaret minaret-one"/><span className="dome dome-one"/><span className="minaret minaret-two"/><span className="dome dome-two"/></div>
    </section>
    <section className="login-card" aria-labelledby="login-title">
      <span className="login-mark"><Icon name="moon" size={32}/></span>
      <h2 id="login-title">Welcome back</h2>
      <p>Sign in to manage your masjid sponsorships.</p>
      <div className="login-fields"><TextField label="Email address" kind="email" placeholder="Enter your email address" required/><TextField label="Password" kind="password" placeholder="Enter your password" required/></div>
      <PreviewButton>Sign In</PreviewButton>
      <p className="login-disclaimer">Sign-in becomes available in Phase 03. This page cannot authenticate users.</p>
      <Link href="/prospects" className="preview-return">← Return to design preview</Link>
    </section>
  </main>;
}
