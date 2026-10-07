// Minimal inline icon set matching the Stitch reference (outlined, 1.75px stroke).
import type { ReactNode } from "react";
type P = { size?: number; className?: string };

const svg = (size: number, className: string | undefined, children: ReactNode) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.75}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
  >
    {children}
  </svg>
);

export const PlusIcon = ({ size = 16, className }: P) => svg(size, className, <path d="M12 5v14M5 12h14" />);
export const CheckCircleIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><circle cx="12" cy="12" r="9" /><path d="m8.5 12.5 2.5 2.5 4.5-5" /></>);
export const ClipboardIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4h6v3H9zM12 11v4M12 17.5v.01" /></>);
export const InfoIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><circle cx="12" cy="12" r="9" /><path d="M12 8v.01M12 11v5" /></>);
export const SlidersIcon = ({ size = 16, className }: P) =>
  svg(size, className, <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4" />);
export const UserIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><circle cx="12" cy="8" r="3.5" /><path d="M5 20c1.2-3.5 4-5 7-5s5.8 1.5 7 5" /></>);
export const CloseIcon = ({ size = 16, className }: P) => svg(size, className, <path d="M6 6l12 12M18 6 6 18" />);
export const SendIcon = ({ size = 14, className }: P) => svg(size, className, <path d="M4 12h13M13 6l6 6-6 6" />);
export const ShieldIcon = ({ size = 16, className }: P) =>
  svg(size, className, <path d="M12 3 5 6v6c0 4.2 3 7.5 7 9 4-1.5 7-4.8 7-9V6z" />);
export const DotsIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><circle cx="12" cy="5" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="12" cy="19" r="1" /></>);
export const MenuIcon = ({ size = 18, className }: P) => svg(size, className, <path d="M4 7h16M4 12h16M4 17h16" />);
export const AlertIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><path d="M12 3 2.5 20h19z" /><path d="M12 10v4M12 17v.01" /></>);
export const HandIcon = ({ size = 16, className }: P) =>
  svg(size, className, <><circle cx="12" cy="8" r="3.5" /><path d="M5 20c1.2-3.5 4-5 7-5s5.8 1.5 7 5" /><path d="M18 4v4M16 6h4" /></>);
