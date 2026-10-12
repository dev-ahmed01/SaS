import type { ReactNode } from "react";
import Link from "next/link";
import { Icon } from "./icon";

export function PageHeading({ title, description }: { title: string; description?: string }) {
  return <header className="page-heading"><h1>{title}</h1>{description && <p>{description}</p>}</header>;
}

export function PhaseNotice({ phase, text }: { phase: string; text: string }) {
  return <div className="phase-notice" role="status"><Icon name="info" size={17}/><span><strong>UI preview · Phase {phase}</strong> — {text}</span></div>;
}

export function ModuleTabs({ current, tabs }: { current: string; tabs: readonly { label: string; href: string; id: string }[] }) {
  return <nav className="module-tabs" aria-label="Module views">{tabs.map(tab=><Link key={tab.id} href={tab.href} className={"module-tab" + (tab.id===current?" selected":"")} aria-current={tab.id===current?"page":undefined}>{tab.label}</Link>)}</nav>;
}

export function TextField({ label, placeholder, kind="text", required=false }: { label: string; placeholder: string; kind?: string; required?:boolean }) {
  return <label className="field"><span className="field-label">{label}{required&&<span className="required" aria-label="required"> *</span>}</span><input type={kind} placeholder={placeholder} disabled aria-label={label}/></label>;
}

export function SelectField({ label, placeholder, required=false }: {label:string; placeholder:string; required?:boolean}) {
  return <label className="field"><span className="field-label">{label}{required&&<span className="required" aria-label="required"> *</span>}</span><select defaultValue="" disabled aria-label={label}><option value="">{placeholder}</option></select></label>;
}

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return <section className="content-panel">{title && <h2>{title}</h2>}{children}</section>;
}

export function EmptyTable({ title, description, columns, search }: { title: string; description: string; columns: string[]; search: string }) {
  return <section className="list-panel" aria-label={title}>
    <div className="list-tools"><label className="search-control"><Icon name="search" size={17}/><span className="sr-only">Search records</span><input disabled placeholder={search}/></label></div>
    <div className="table-scroll"><table className="data-table"><thead><tr>{columns.map(column=><th key={column} scope="col">{column}</th>)}</tr></thead><tbody><tr><td colSpan={columns.length}><div className="empty-state"><Icon name="file" size={27}/><h3>{title}</h3><p>{description}</p></div></td></tr></tbody></table></div>
    <div className="table-footer">No records to display · Data connections arrive in the module phase.</div>
  </section>;
}

export function PreviewButton({ children }: { children: ReactNode }) {
  return <button className="btn btn-primary" type="button" disabled title="Available when this module is implemented">{children}</button>;
}
