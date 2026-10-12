import { notFound } from "next/navigation";
import { ModuleWorkspace } from "../../../components/module-workspace";

const valid: Record<string,string[]> = {
  dashboard:["add"],prospects:["add","inactive","all"],promoters:["add","active","all"],
  collections:["add","active","all"],payouts:["add","active","all"],
  reminders:["add","whatsapp","email"],settings:["add"]
};

export async function generateMetadata({params}:{params:Promise<{module:string;view?:string[]}>}) {
  const {module}=await params;
  return {title:module[0]?.toUpperCase()+module.slice(1)+" | Sponsor a Salah"};
}

export default async function ModuleRoute({params}:{params:Promise<{module:string;view?:string[]}>}) {
  const {module,view}=await params;
  const target=view?.[0]??"add";
  if(!valid[module]?.includes(target) || (view && view.length!==1))notFound();
  return <ModuleWorkspace module={module} view={target}/>;
}
