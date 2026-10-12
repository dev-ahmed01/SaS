export type ProspectStatus = "new" | "active" | "inactive";
export type Prospect = {
  id: string;
  full_name: string;
  mobile_number: string;
  whatsapp_number: string | null;
  area_city: string;
  monthly_contribution_paise: number;
  next_followup_on: string | null;
  last_contact_on: string | null;
  notes: string | null;
  whatsapp_opt_in: boolean;
  lifecycle_status: ProspectStatus;
  last_verified_payment_at: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  version: number;
  upi_ids: {id:string; masked_vpa:string; is_verified:boolean}[];
};
export type ProspectPage = {
  items:Prospect[];
  total:number;
  limit:number;
  offset:number;
};
