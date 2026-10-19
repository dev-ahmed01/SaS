import { AppShell } from "./app-shell";
import { EmptyTable, ModuleTabs, Panel, PhaseNotice, PreviewButton, SelectField, TextField } from "./ui/primitives";
import { AdminSettingsForm } from "./admin-settings-form";
import { DashboardLive } from "./dashboard/dashboard-live";
import { ManualCollections } from "./collections/manual-collections";
import { CommunicationWorkspace } from "./communication/workspace";
import { CollectionsAllWorkspace } from "./collections/collections-all-workspace";
import { PayoutAdd, PayoutList } from "./payouts/payouts-workspace";
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
    tabs:[{id:"add",label:"Record Collection",href:"/collections"},{id:"active",label:"Received This Month",href:"/collections/active"},{id:"all",label:"All Collections",href:"/collections/all"}],
    fields:[{label:"Sponsor name",placeholder:"Select sponsor",required:true,kind:"select"},{label:"Amount (₹)",placeholder:"Enter amount",required:true,kind:"number"},{label:"Collection date",placeholder:"Select date",required:true,kind:"date"},{label:"Payment method",placeholder:"Select method",required:true,kind:"select"},{label:"Reference / Notes",placeholder:"Transaction reference or notes",kind:"textarea"}],
    columns:["Sponsor name","Amount (₹)","Collection date","Payment method","Status","Actions"],search:"Search sponsor name or transaction reference"
  },
  payouts:{
    name:"Payouts",singular:"Payout",phase:"09",description:"Record recurring and one-time outgoing payments.",
    tabs:[{id:"add",label:"Add Payout",href:"/payouts"},{id:"active",label:"Recurring Plans",href:"/payouts/active"},{id:"all",label:"All Payouts",href:"/payouts/all"}],
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
  return <AppShell>
    <ModuleTabs current={view} tabs={definition.tabs}/>
    <PhaseNotice phase={definition.phase} text="The layout is ready. Data entry and status actions are intentionally disabled until its secured backend is implemented."/>
    {view==="add"?<FormPreview definition={definition}/>:<EmptyTable title={title} description={"No "+definition.name.toLowerCase()+" to display in this design preview."} columns={definition.columns} search={definition.search}/>}
  </AppShell>;
}

function Dashboard() {
  return <AppShell>
    <DashboardLive/>
  </AppShell>;
}

function Settings() {
  return <AppShell>
    <AdminSettingsForm/>
  </AppShell>;
}

export function ModuleWorkspace({module,view="add"}:{module:string;view?:string}) {
  if(module==="dashboard"&&view==="add") return <Dashboard/>;
  if(module==="settings"&&view==="add") return <Settings/>;
  if(module==="communication" && ["compose","campaigns","templates"].includes(view)) return <CommunicationWorkspace view={view as "compose"|"campaigns"|"templates"}/>;
  if(module==="prospects" && ["add","inactive","active","all","stages"].includes(view)) return <ProspectsWorkspace view={view as "add"|"inactive"|"active"|"all"|"stages"}/>;
  if(module==="promoters" && ["add","active","inactive","all"].includes(view)) return <PromotersWorkspace view={view as "add"|"active"|"inactive"|"all"}/>;
  if(module==="collections" && view==="add") return <AppShell><div className="finance-tabs"><ModuleTabs current={view} tabs={definitions.collections.tabs}/></div><ManualCollections/></AppShell>;
  if(module==="collections" && ["active","all"].includes(view)) return <AppShell><ModuleTabs current={view} tabs={definitions.collections.tabs}/><CollectionsAllWorkspace activeOnly={view==="active"}/></AppShell>;
  if(module==="payouts" && view==="add") return <AppShell><div className="finance-tabs"><ModuleTabs current={view} tabs={definitions.payouts.tabs}/></div><PayoutAdd/></AppShell>;
  if(module==="payouts" && ["active","all"].includes(view)) return <AppShell><ModuleTabs current={view} tabs={definitions.payouts.tabs}/><PayoutList view={view as "active"|"all"}/></AppShell>;
  if(["prospects","promoters","collections","payouts"].includes(module))return <BusinessModule module={module as Module} view={view}/>;
  return null;
}
