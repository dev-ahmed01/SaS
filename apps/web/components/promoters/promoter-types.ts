export type Promoter = {
  id:string;
  full_name:string;
  first_name:string|null;
  last_name:string|null;
  email:string|null;
  occupation:string|null;
  mobile_number:string;
  whatsapp_number:string|null;
  area_city:string;
  notes:string|null;
  whatsapp_opt_in:boolean;
  is_active:boolean;
  sponsor_count:number;
  version:number;
  created_at:string;
  updated_at:string;
};
export type PromoterPage={items:Promoter[];total:number;limit:number;offset:number};
export type SponsorLink = {
  assignment_id:string;
  prospect_id:string;
  full_name:string;
  mobile_number:string;
  lifecycle_status:"new"|"active"|"inactive";
  prospect_version:number;
};
export type SponsorPage={items:SponsorLink[];total:number;limit:number;offset:number};
export type Candidate={id:string;full_name:string;mobile_number:string;version:number;archived_at:string|null};
export async function csrfToken():Promise<string>{
  const response=await fetch("/api/admin/session",{cache:"no-store"});
  if(!response.ok)throw Error("Your Admin session has expired. Sign in again.");
  const data=await response.json();
  return data.csrf_token as string;
}
export function normalizedPhone(value:string):string|null{
  const phone=value.trim().replace(/[\s-]/g,"");
  if(!phone)return null;
  if(/^\d{10}$/.test(phone))return "+91"+phone;
  return /^\+[1-9]\d{7,14}$/.test(phone)?phone:null;
}
