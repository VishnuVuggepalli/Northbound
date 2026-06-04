import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { LiveIndicator } from './LiveIndicator';
import { useLiveStore } from '@/store/live';

afterEach(cleanup);

describe('LiveIndicator', () => {
  it('shows "Live" when the stream is open', () => {
    useLiveStore.setState({ status: 'open' });
    render(<LiveIndicator />);
    expect(screen.getByRole('status')).toHaveTextContent('Live');
  });

  it('shows "Connecting…" while connecting', () => {
    useLiveStore.setState({ status: 'connecting' });
    render(<LiveIndicator />);
    expect(screen.getByRole('status')).toHaveTextContent('Connecting');
  });

  it('shows "Offline" when closed', () => {
    useLiveStore.setState({ status: 'closed' });
    render(<LiveIndicator />);
    expect(screen.getByRole('status')).toHaveTextContent('Offline');
  });
});
