export type BulkPerson={full_name:string;first_name?:string;last_name?:string;mobile_number:string;area_city:string;email?:string;monthly_contribution_paise?:number;start_month?:string;promoter?:string;};
export const COLUMNS: string[];
export function parsePeople(input:string):BulkPerson[];
