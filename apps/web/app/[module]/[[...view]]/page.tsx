import { notFound } from "next/navigation";
import { ModuleWorkspace } from "../../../components/module-workspace";
import { requireAdminSession } from "../../../lib/admin-guard";

const valid: Record<string,string[]> = {
  dashboard:["add"],prospects:["add","all","active","inactive"],promoters:["add","active","all"],
  collections:["add","active","all"],payouts:["add","active","all"],
  reminders:["add","whatsapp","email"],settings:["add"]
};

export async function generateMetadata({params}:{params:Promise<{module:string;view?:string[]}>}) {
  const {module}=await params;
  return {title:module[0]?.toUpperCase()+module.slice(1)+" | Sponsor a Salah",robots:{index:false,follow:false}};
}

export default async function ModuleRoute({params}:{params:Promise<{module:string;view?:string[]}>}) {
  const {module,view}=await params;
  const target=view?.[0]??(module==="prospects"?"all":"add");
  if(!valid[module]?.includes(target) || (view && view.length!==1))notFound();
  await requireAdminSession();
  return <ModuleWorkspace module={module} view={target}/>;
}
