import { notFound } from "next/navigation";
import { PromotersWorkspace } from "../../../components/promoters/promoters-workspace";
import { PromoterDetails } from "../../../components/promoters/promoter-details";
import { requireAdminSession } from "../../../lib/admin-guard";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const tabs=new Set(["add","all","active","inactive"]);

export async function generateMetadata(){
  return {title:"Promoters | Sponsor a Salah",robots:{index:false,follow:false}};
}
export default async function PromoterPage({params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  if(!tabs.has(id)&&!UUID.test(id))notFound();
  await requireAdminSession();
  if(tabs.has(id)){
    return <PromotersWorkspace view={id as "add"|"all"|"active"|"inactive"}/>;
  }
  return <PromoterDetails id={id}/>;
}
