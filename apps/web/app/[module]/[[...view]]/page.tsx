import { notFound, redirect } from "next/navigation";
import { ModuleWorkspace } from "../../../components/module-workspace";
import { CampaignResultDetails } from "../../../components/communication/campaign-results";
import { requireAdminSession } from "../../../lib/admin-guard";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const valid: Record<string,string[]> = {
  dashboard:["add"],prospects:["add","all","active","inactive","stages"],promoters:["add","active","all","inactive"],
  collections:["add","active","all"],payouts:["add","active","all"],
  reminders:["add","whatsapp","email"],communication:["compose","campaigns","templates","automations"],settings:["add"]
};

export async function generateMetadata({params}:{params:Promise<{module:string;view?:string[]}>}) {
  const {module}=await params;
  return {title:module[0]?.toUpperCase()+module.slice(1)+" | Sponsor a Salah",robots:{index:false,follow:false}};
}

export default async function ModuleRoute({params,searchParams}:{
  params:Promise<{module:string;view?:string[]}>;
  searchParams:Promise<{campaign?:string}>;
}) {
  const {module,view}=await params;
  const target=view?.[0]??(module==="communication"?"compose":
    ["prospects","promoters"].includes(module)?"all":"add");
  if(!valid[module]?.includes(target) || (view && view.length!==1))notFound();
  await requireAdminSession();
  // The existing /communication/campaigns module route is already reliable
  // across Next production builds. Keep a directly linkable full-page result
  // view using its campaign query rather than a conflicting dynamic sub-route.
  if(module==="communication" && target==="campaigns"){
    const {campaign}=await searchParams;
    if(campaign!==undefined){
      if(!UUID.test(campaign))notFound();
      return <CampaignResultDetails id={campaign}/>;
    }
  }
  if(module==="reminders") redirect("/communication");
  if(module==="communication"&&target==="automations") redirect("/communication/templates");
  return <ModuleWorkspace module={module} view={target}/>;
}
