import { notFound } from "next/navigation";
import { ProspectDetails } from "../../../components/prospects/prospect-details";
import { ProspectsWorkspace } from "../../../components/prospects/prospects-workspace";
import { requireAdminSession } from "../../../lib/admin-guard";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const sections=new Set(["add","all","active","inactive","stages","bulk"]);

export async function generateMetadata({params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  return {title:(sections.has(id)?"Prospects":"Prospect details")+" | Sponsor a Salah",
    robots:{index:false,follow:false}};
}

export default async function ProspectDetailPage({params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  if(!sections.has(id)&&!UUID.test(id))notFound();
  await requireAdminSession();
  if(sections.has(id)){
    return <ProspectsWorkspace view={id as "add"|"all"|"active"|"inactive"|"stages"|"bulk"}/>;
  }
  return <ProspectDetails id={id}/>;
}
