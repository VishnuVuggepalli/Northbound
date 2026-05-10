import { Modal } from '@/components/ui/Modal';
import { Kbd } from '@/components/ui/Kbd';

interface HelpOverlayProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS: Array<[label: string, keys: string]> = [
  ['Search', '/'],
  ['Switch to Lab', 'g l'],
  ['Switch to DC', 'g d'],
  ['Home (env picker)', 'g h'],
  ['My requests', 'g r'],
  ['Admin queue (admin)', 'g q'],
  ['Move between ports', 'j / k'],
  ['Request change on selected port', 'r'],
  ['Help (this panel)', '?'],
  ['Close panel / modal', 'Esc'],
];

export function HelpOverlay({ open, onClose }: HelpOverlayProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Keyboard shortcuts"
      subtitle="One-handed operation while you read logs."
      width={520}
    >
      <ul className="divide-y divide-border">
        {SHORTCUTS.map(([label, keys]) => (
          <li key={label} className="flex items-center justify-between py-2.5">
            <span className="text-sm text-fg">{label}</span>
            <span className="flex items-center gap-1">
              {keys.split(' ').map((k, i) => (
                <Kbd key={i}>{k}</Kbd>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
