import type { ChangeRequestStatus } from '@/types';
import { Badge } from './Badge';

const LABELS: Record<ChangeRequestStatus, string> = {
  pending: 'Pending',
  approved: 'Approved',
  applied: 'Applied',
  rejected: 'Rejected',
  failed: 'Failed',
};

const VARIANT: Record<ChangeRequestStatus, Parameters<typeof Badge>[0]['variant']> = {
  pending: 'warn',
  approved: 'accent',
  applied: 'success',
  rejected: 'muted',
  failed: 'danger',
};

export function StatusBadge({ status }: { status: ChangeRequestStatus }) {
  return <Badge variant={VARIANT[status]}>{LABELS[status]}</Badge>;
}
