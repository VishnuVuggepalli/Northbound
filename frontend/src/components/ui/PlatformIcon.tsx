import { Server, Network, Router, ShieldCheck, Layers } from 'lucide-react';
import type { DeviceRole, Platform } from '@/types';
import { cn } from '@/lib/cn';

interface PlatformIconProps {
  platform: Platform;
  role?: DeviceRole;
  size?: number;
  className?: string;
}

const PLATFORM_TINT: Record<Platform, string> = {
  cisco: 'text-[oklch(0.74_0.16_200)] bg-[oklch(0.74_0.16_200/0.12)]',
  arista: 'text-[oklch(0.72_0.18_240)] bg-[oklch(0.72_0.18_240/0.12)]',
  pica8: 'text-[oklch(0.78_0.18_55)] bg-[oklch(0.78_0.18_55/0.12)]',
  mikrotik: 'text-[oklch(0.74_0.17_25)] bg-[oklch(0.74_0.17_25/0.12)]',
  freebsd: 'text-[oklch(0.72_0.16_300)] bg-[oklch(0.72_0.16_300/0.12)]',
  mock: 'text-[oklch(0.70_0.02_250)] bg-[oklch(0.70_0.02_250/0.12)]',
};

export function PlatformIcon({ platform, role, size = 14, className }: PlatformIconProps) {
  const Icon =
    role === 'spine' ? Layers : role === 'router' ? Router : role === 'vpn' ? ShieldCheck : role === 'leaf' ? Network : Server;
  return (
    <span
      className={cn(
        'inline-flex h-7 w-7 items-center justify-center rounded-md border border-border',
        PLATFORM_TINT[platform],
        className,
      )}
    >
      <Icon size={size} />
    </span>
  );
}
