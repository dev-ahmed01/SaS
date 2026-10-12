"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./ui/icon";

const navigation: { name: string; href: string; icon: IconName }[] = [
  {name:"Dashboard",href:"/dashboard",icon:"grid"},
  {name:"Prospects",href:"/prospects",icon:"users"},
  {name:"Promoters",href:"/promoters",icon:"user-plus"},
  {name:"Collections",href:"/collections",icon:"receipt"},
  {name:"Payouts",href:"/payouts",icon:"wallet"},
  {name:"Reminders",href:"/reminders",icon:"bell"},
  {name:"Settings",href:"/settings",icon:"settings"},
];

export function AppShell({children}:{children:React.ReactNode}) {
  const pathname = usePathname();
  const [mobileOpen,setMobileOpen] = useState(false);
  const [collapsed,setCollapsed] = useState(false);
  const closeDrawer = () => setMobileOpen(false);

  return <div className={"app-frame"+(collapsed?" sidebar-collapsed":"")}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    {mobileOpen && <button className="drawer-scrim" aria-label="Close navigation" onClick={closeDrawer}/>}
    <aside className={"site-sidebar"+(mobileOpen?" mobile-open":"")} aria-label="Main navigation">
      <div className="sidebar-head">
        <Link className="brand-link" href="/prospects" onClick={closeDrawer} aria-label="Sponsor a Salah home">
          <span className="brand-mark"><Icon name="moon" size={30}/></span>
          <span className="brand-copy"><strong>Sponsor a Salah</strong><small>Masjid Charity Management</small></span>
        </Link>
        <button className="icon-button desktop-collapse" onClick={()=>setCollapsed(v=>!v)} aria-label={collapsed?"Expand sidebar":"Collapse sidebar"} title={collapsed?"Expand sidebar":"Collapse sidebar"}><Icon name="menu"/></button>
        <button className="icon-button mobile-close" onClick={closeDrawer} aria-label="Close menu"><Icon name="close"/></button>
      </div>
      <nav className="sidebar-nav" aria-label="Modules">
        {navigation.map(link=>{
          const active=pathname===link.href || pathname.startsWith(link.href+"/");
          return <Link key={link.href} href={link.href} onClick={closeDrawer} title={link.name} aria-current={active?"page":undefined} className={"sidebar-link"+(active?" active":"")}>
            <Icon name={link.icon} size={18}/><span className="nav-label">{link.name}</span>
          </Link>;
        })}
      </nav>
      <div className="sidebar-art" aria-hidden="true"><span className="minaret minaret-one"/><span className="dome dome-one"/><span className="minaret minaret-two"/><span className="dome dome-two"/></div>
      <div className="sidebar-bottom"><span className="avatar">A</span><span className="account-copy"><strong>Admin preview</strong><small>Authentication in Phase 03</small></span></div>
    </aside>
    <div className="app-content">
      <header className="topbar">
        <button className="icon-button mobile-toggle" aria-label="Open navigation" aria-expanded={mobileOpen} onClick={()=>setMobileOpen(true)}><Icon name="menu"/></button>
        <span className="topbar-name">Sponsor a Salah</span>
        <span className="topbar-spacer"/>
        <span className="environment-tag">Design preview</span>
        <span className="avatar top-avatar">A</span>
      </header>
      <main id="main-content" className="page-content">{children}</main>
    </div>
  </div>;
}
