import { notFound } from "next/navigation";
import { ProspectDetails } from "../../../components/prospects/prospect-details";
import { requireAdminSession } from "../../../lib/admin-guard";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function generateMetadata(){
  return {title:"Prospect details | Sponsor a Salah",robots:{index:false,follow:false}};
}

export default async function ProspectDetailPage({params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  if(!UUID.test(id))notFound();
  await requireAdminSession();
  return <ProspectDetails id={id}/>;
}
