import type { ChangeRequestStatus } from '@/types';
import { Badge } from './Badge';

const LABELS: Record<ChangeRequestStatus, string> = {
  pending: 'Pending',
  approved: 'Approved',
  applying: 'Applying',
  awaiting_confirm: 'Awaiting confirm',
  applied: 'Applied',
  rejected: 'Rejected',
  reverted: 'Reverted',
  failed: 'Failed',
};

const VARIANT: Record<ChangeRequestStatus, Parameters<typeof Badge>[0]['variant']> = {
  pending: 'warn',
  approved: 'accent',
  applying: 'accent',
  awaiting_confirm: 'warn',
  applied: 'success',
  rejected: 'muted',
  reverted: 'muted',
  failed: 'danger',
};

export function StatusBadge({ status }: { status: ChangeRequestStatus }) {
  return <Badge variant={VARIANT[status]}>{LABELS[status]}</Badge>;
}
