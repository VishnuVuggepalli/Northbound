import type { ChangeRequestStatus } from '@/models';
import { Badge } from './Badge';

const LABELS: Record<ChangeRequestStatus, string> = {
  pending: 'Pending',
  needs_revision: 'Needs revision',
  approved: 'Approved',
  applying: 'Applying',
  awaiting_confirm: 'Awaiting confirm',
  applied: 'Applied',
  rejected: 'Rejected',
  reverted: 'Reverted',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

const VARIANT: Record<ChangeRequestStatus, Parameters<typeof Badge>[0]['variant']> = {
  pending: 'warn',
  needs_revision: 'warn',
  approved: 'accent',
  applying: 'accent',
  awaiting_confirm: 'warn',
  applied: 'success',
  rejected: 'muted',
  reverted: 'muted',
  failed: 'danger',
  cancelled: 'muted',
};

export function StatusBadge({ status }: { status: ChangeRequestStatus }) {
  return <Badge variant={VARIANT[status]}>{LABELS[status]}</Badge>;
}
