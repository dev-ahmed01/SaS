import type { ReactNode } from "react";

export type IconName = "moon" | "grid" | "users" | "user-plus" | "wallet" | "receipt" | "bell" | "settings" | "menu" | "close" | "chevron-down" | "arrow-left" | "search" | "calendar" | "mail" | "message" | "shield" | "logout" | "check" | "info" | "file" | "clock" | "dots" | "upload" | "eye" | "eye-off";

const paths: Record<IconName, ReactNode> = {
  moon: <path d="M20.5 14.1A8.4 8.4 0 0 1 9.9 3.5 8.6 8.6 0 1 0 20.5 14.1Z"/>,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></>,
  "user-plus": <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6m-3-3h6"/></>,
  wallet: <><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9h18m-5 4h3"/></>,
  receipt: <><path d="M4 3h16v18l-4-2-4 2-4-2-4 2V3Z"/><path d="M8 8h8m-8 4h8"/></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19 13.5a7 7 0 0 0 0-3l2-1.5-2-3-2.5 1a7 7 0 0 0-2.5-1.5L13.5 3h-3L10 5.5A7 7 0 0 0 7.5 7L5 6 3 9l2 1.5a7 7 0 0 0 0 3L3 15l2 3 2.5-1a7 7 0 0 0 2.5 1.5l.5 2.5h3l.5-2.5a7 7 0 0 0 2.5-1.5l2.5 1 2-3-2-1.5Z"/></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
  close: <path d="M5 5l14 14M19 5 5 19"/>,
  "chevron-down": <path d="m6 9 6 6 6-6"/>,
  "arrow-left": <path d="m12 19-7-7 7-7M5 12h14"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></>,
  mail: <><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 7 10 7 10-7"/></>,
  message: <><path d="M21 11.5a8.5 8.5 0 0 1-12 7.8L3 21l1.7-6A8.5 8.5 0 1 1 21 11.5Z"/><path d="M8 12h8"/></>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></>,
  logout: <><path d="M10 17l5-5-5-5m5 5H3"/><path d="M13 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/></>,
  check: <path d="m4 12 5 5L20 6"/>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/></>,
  file: <><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z"/><path d="M13 2v7h7M8 14h8m-8 4h8"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/></>,
  dots: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
  upload: <><path d="M12 16V3m-5 5 5-5 5 5"/><path d="M4 16v4h16v-4"/></>,
  eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
  "eye-off": <><path d="M3 3l18 18M10.6 5.1A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a16.4 16.4 0 0 1-3 3.7M6.3 6.3C3.6 8.2 2 12 2 12s3.5 7 10 7c1.6 0 3.1-.4 4.4-1.1"/><path d="M10 10a3 3 0 0 0 4 4"/></>,
};

export function Icon({ name, size = 19, className = "" }: { name: IconName; size?: number; className?: string }) {
  return <svg aria-hidden="true" className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.85" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
