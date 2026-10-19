export type ProspectStatus = "new" | "active" | "inactive";
export type CrmStage = "active" | "inactive";
export type StageReason = "not_interested" | "budget" | "timing" | "unreachable" | "other";
export const stageReasons: {value:StageReason; label:string}[] = [
  {value:"not_interested",label:"Not interested"},
  {value:"budget",label:"Budget or affordability"},
  {value:"timing",label:"Timing or personal circumstances"},
  {value:"unreachable",label:"Unable to contact"},
  {value:"other",label:"Other reason"},
];
export const reasonLabel = (code:string | null) =>
  stageReasons.find(option=>option.value===code)?.label ?? (code||"—");

export type Prospect = {
  id: string;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  mobile_number: string;
  whatsapp_number: string | null;
  email: string | null;
  occupation: string | null;
  area_city: string;
  monthly_contribution_paise: number;
  next_followup_on: string | null;
  last_contact_on: string | null;
  notes: string | null;
  whatsapp_opt_in: boolean;
  lifecycle_status: ProspectStatus;
  crm_stage: CrmStage;
  crm_inactive_reason: string | null;
  crm_inactive_note: string | null;
  crm_stage_changed_at: string | null;
  days_inactive: number | null;
  stage_history: {from_stage:CrmStage;to_stage:CrmStage;reason:string|null;note:string|null;changed_at:string}[];
  assigned_promoter_id: string | null;
  assigned_promoter_name: string | null;
  last_verified_payment_at: string | null;
  start_month: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  version: number;
  upi_ids: {id:string; masked_vpa:string; is_verified:boolean}[];
};
export type ProspectPage = {
  items: Prospect[];
  total: number;
  limit: number;
  offset: number;
};
