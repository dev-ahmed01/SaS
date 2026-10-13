import Link from "next/link";
import { AppShell } from "./app-shell";
import { EmptyTable, ModuleTabs, PageHeading, Panel, PhaseNotice, PreviewButton, SelectField, TextField } from "./ui/primitives";
import { Icon } from "./ui/icon";
import { AdminSettingsForm } from "./admin-settings-form";
import { AccountingOverview } from "./accounting/accounting-overview";
import { ManualCollections } from "./collections/manual-collections";
import { ProspectsWorkspace } from "./prospects/prospects-workspace";
import { PromotersWorkspace } from "./promoters/promoters-workspace";

type Field = {label:string; placeholder:string; required?:boolean; kind?:"text"|"date"|"number"|"tel"|"email"|"select"|"textarea"};
type Module = "prospects" | "promoters" | "collections" | "payouts";
const definitions: Record<Module,{name:string;singular:string;phase:string;description:string;tabs:{id:string;label:string;href:string}[];fields:Field[];columns:string[];search:string}> = {
  prospects:{
    name:"Prospects",singular:"Prospect",phase:"04",description:"Register and manage people who may sponsor a salah.",
    tabs:[{id:"add",label:"Add Prospect",href:"/prospects"},{id:"inactive",label:"Inactive",href:"/prospects/inactive"},{id:"all",label:"All Prospects",href:"/prospects/all"}],
    fields:[{label:"Full name",placeholder:"Enter full name",required:true},{label:"Mobile number",placeholder:"Enter mobile number",required:true,kind:"tel"},{label:"WhatsApp number",placeholder:"Enter WhatsApp number (optional)",kind:"tel"},{label:"UPI ID",placeholder:"example@bank (optional)"},{label:"Area / City",placeholder:"Enter area or city",required:true},{label:"Monthly contribution (₹)",placeholder:"250",required:true,kind:"number"},{label:"Next follow-up date",placeholder:"Select date",kind:"date"},{label:"Notes",placeholder:"Add notes about this prospect",kind:"textarea"}],
    columns:["Name","Mobile number","Area / City","Last contact","Status","Actions"],search:"Search name, number or area"
  },
  promoters:{
    name:"Promoters",singular:"Promoter",phase:"05",description:"Manage promoters and the sponsors they support.",
    tabs:[{id:"add",label:"Add Promoter",href:"/promoters"},{id:"active",label:"Active",href:"/promoters/active"},{id:"all",label:"All Promoters",href:"/promoters/all"}],
    fields:[{label:"Full name",placeholder:"Enter full name",required:true},{label:"Phone number",placeholder:"Enter phone number",required:true,kind:"tel"},{label:"Area / City",placeholder:"Enter area or city",required:true},{label:"Notes",placeholder:"Add notes about this promoter",kind:"textarea"}],
    columns:["Name","Phone number","Area / City","Status","Actions"],search:"Search name, number or area"
  },
  collections:{
    name:"Collections",singular:"Collection",phase:"08",description:"Track recurring monthly contributions and recorded UPI collections.",
    tabs:[{id:"add",label:"Add",href:"/collections"},{id:"active",label:"Active",href:"/collections/active"},{id:"all",label:"All",href:"/collections/all"}],
    fields:[{label:"Sponsor name",placeholder:"Select sponsor",required:true,kind:"select"},{label:"Amount (₹)",placeholder:"Enter amount",required:true,kind:"number"},{label:"Collection date",placeholder:"Select date",required:true,kind:"date"},{label:"Payment method",placeholder:"Select method",required:true,kind:"select"},{label:"Reference / Notes",placeholder:"Transaction reference or notes",kind:"textarea"}],
    columns:["Sponsor name","Amount (₹)","Collection date","Payment method","Status","Actions"],search:"Search sponsor name or transaction reference"
  },
  payouts:{
    name:"Payouts",singular:"Payout",phase:"09",description:"Record recurring and one-time outgoing payments.",
    tabs:[{id:"add",label:"Add Payout",href:"/payouts"},{id:"active",label:"Active",href:"/payouts/active"},{id:"all",label:"All",href:"/payouts/all"}],
    fields:[{label:"Payee name",placeholder:"Enter payee name",required:true},{label:"Amount (₹)",placeholder:"Enter amount",required:true,kind:"number"},{label:"Date",placeholder:"Select date",required:true,kind:"date"},{label:"Purpose",placeholder:"Select purpose",required:true,kind:"select"},{label:"Notes",placeholder:"Enter any notes",kind:"textarea"}],
    columns:["Payee name","Amount (₹)","Date","Purpose","Frequency","Actions"],search:"Search payee or payment purpose"
  }
};

function FormPreview({definition}:{definition:typeof definitions[Module]}) {
  const fields=definition.fields;
  return <Panel title={"Add "+definition.singular}>
    <p className="panel-description">Enter the details for this {definition.singular.toLowerCase()}.</p>
    <form aria-label={"Add "+definition.singular+" form preview"}>
      <fieldset className="preview-fieldset" disabled><legend className="sr-only">Form preview — cannot submit</legend>
        <div className="form-grid">{fields.map(field=><div key={field.label} className={"form-cell"+(field.kind==="textarea"?" full":"")}>
          {field.kind==="textarea"?<label className="field"><span className="field-label">{field.label}</span><textarea disabled rows={3} placeholder={field.placeholder}/></label>
          :field.kind==="select"?<SelectField {...field}/>
          :<TextField {...field} kind={field.kind}/>}
        </div>)}</div>
      </fieldset>
      <div className="form-actions"><button type="reset" className="btn btn-secondary" disabled>Clear</button><PreviewButton>Save {definition.singular}</PreviewButton></div>
    </form>
  </Panel>;
}

function BusinessModule({module,view}:{module:Module;view:string}) {
  const definition=definitions[module];
  const valid=definition.tabs.some(tab=>tab.id===view);
  if(!valid) return null;
  const title = view==="inactive" ? "Inactive "+definition.name : view==="active" ? "Active "+definition.name : "All "+definition.name;
  return <AppShell><PageHeading title={definition.name} description={definition.description}/>
    <ModuleTabs current={view} tabs={definition.tabs}/>
    <PhaseNotice phase={definition.phase} text="The layout is ready. Data entry and status actions are intentionally disabled until its secured backend is implemented."/>
    {view==="add"?<FormPreview definition={definition}/>:<EmptyTable title={title} description={"No "+definition.name.toLowerCase()+" to display in this design preview."} columns={definition.columns} search={definition.search}/>}
  </AppShell>;
}

function Reminders({view}:{view:string}) {
  if(view==="whatsapp"||view==="email") {
    const wa=view==="whatsapp";
    return <AppShell><Link className="back-link" href="/reminders"><Icon name="arrow-left" size={17}/> Back to reminders</Link>
      <PageHeading title={wa?"WhatsApp Reminder":"Email Reminder"} description={wa?"Preview the monthly sponsorship WhatsApp reminder.":"Email reminders are planned but not connected yet."}/>
      <PhaseNotice phase="11" text="Message delivery is disabled until WhatsApp/Email onboarding, consent and backend eligibility checks are complete."/>
      <div className="composer-grid"><Panel title="Message details">
        <div className="form-grid"><div className="form-cell full">{wa?<SelectField label="Message template" placeholder="Monthly Salah Sponsorship Reminder" required/>:<TextField label="Subject" placeholder="Monthly Salah Sponsorship Reminder" required/>}</div>
        <div className="form-cell full"><label className="field"><span className="field-label">Message content</span><textarea rows={7} disabled defaultValue={"Assalamu Alaikum {name},\n\nThis is a friendly reminder about your monthly Salah sponsorship.\n\nJazakAllahu Khair for your continued support."}/></label></div>
        <div className="form-cell full"><SelectField label="Send to" placeholder="Eligible active sponsors" required/></div></div>
        <div className="form-actions"><PreviewButton>{wa?"Send WhatsApp Reminders":"Send Email Reminders"}</PreviewButton></div>
      </Panel><Panel title="Recipient preview"><div className="recipient-preview"><Icon name={wa?"message":"mail"} size={32}/><h3>Delivery is not enabled</h3><p>Only eligible sponsors with appropriate consent will be included after Phase 11. No messages are being sent.</p></div></Panel></div>
    </AppShell>;
  }
  if(view!=="add") return null;
  return <AppShell><PageHeading title="Reminders" description="Send sponsorship reminders through the approved communication channels."/>
    <PhaseNotice phase="11" text="WhatsApp and email delivery will be enabled after provider setup and backend eligibility checks."/>
    <div className="reminder-cards"><Link href="/reminders/whatsapp" className="reminder-card"><span className="reminder-icon whatsapp"><Icon name="message" size={26}/></span><h2>WhatsApp Reminders</h2><p>Send monthly sponsorship reminders through WhatsApp.</p><span className="reminder-card-link">View reminder composer →</span></Link><Link href="/reminders/email" className="reminder-card"><span className="reminder-icon email"><Icon name="mail" size={26}/></span><h2>Email Reminders</h2><p>Prepare email reminders for sponsors.</p><span className="reminder-card-link">View reminder composer →</span></Link></div>
  </AppShell>;
}

function Dashboard() {
  return <AppShell><PageHeading title="Dashboard" description="An overview of your masjid sponsorship operations."/>
    <PhaseNotice phase="12" text="The Dashboard is built last, from verified Prospects, Collections, Payouts and reminder records."/>
    <div className="metric-grid">{["Total sponsors","Active subscriptions","This month's collections","Recurring payouts"].map(x=><section className="metric-preview" key={x}><span>{x}</span><strong>—</strong><small>Waiting for live data</small></section>)}</div>
    <Panel title="Recent Activity"><div className="empty-state"><Icon name="clock" size={28}/><h3>No activity yet</h3><p>Activity appears here once the corresponding modules are implemented.</p></div></Panel>
  </AppShell>;
}

function Settings() {
  return <AppShell><PageHeading title="Settings" description="Manage organisation preferences and administrative configuration."/>
    <AdminSettingsForm/>
  </AppShell>;
}

export function ModuleWorkspace({module,view="add"}:{module:string;view?:string}) {
  if(module==="dashboard"&&view==="add") return <Dashboard/>;
  if(module==="settings"&&view==="add") return <Settings/>;
  if(module==="reminders") return <Reminders view={view}/>;
  if(module==="prospects" && ["add","inactive","all"].includes(view)) return <ProspectsWorkspace view={view as "add"|"inactive"|"all"}/>;
  if(module==="promoters" && ["add","active","all"].includes(view)) return <PromotersWorkspace view={view as "add"|"active"|"all"}/>;
  if(module==="collections" && view==="add") return <AppShell><PageHeading title="Collections" description="Record received contributions with an audit trail."/><ModuleTabs current={view} tabs={definitions.collections.tabs}/><ManualCollections/></AppShell>;
  if(module==="collections" && view==="all") return <AppShell><PageHeading title="Collections" description="Monthly commitments and verified contributions."/><ModuleTabs current={view} tabs={definitions.collections.tabs}/><AccountingOverview/></AppShell>;
  if(["prospects","promoters","collections","payouts"].includes(module))return <BusinessModule module={module as Module} view={view}/>;
  return null;
}
