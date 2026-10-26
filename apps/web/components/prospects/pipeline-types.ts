export type PipelineStage={
  id:string;name:string;description:string|null;color:string;
  sort_order:number;version:number;prospect_count:number;created_at:string;
  is_registration_default:boolean;
};
export const stagePalette=[
  "#64748b","#0f766e","#16a34a","#2563eb","#7c3aed","#db2777",
  "#dc2626","#ea580c","#ca8a04","#0891b2",
];
export async function pipelineStages():Promise<PipelineStage[]>{
  const r=await fetch("/api/admin/prospect-stages",{cache:"no-store"});
  if(!r.ok)throw Error("Could not load prospect stages.");
  return await r.json() as PipelineStage[];
}
