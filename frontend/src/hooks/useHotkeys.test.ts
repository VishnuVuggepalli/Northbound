import { describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useHotkeys } from './useHotkeys';

function press(init: KeyboardEventInit): KeyboardEvent {
  const ev = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
  window.dispatchEvent(ev);
  return ev;
}

describe('useHotkeys', () => {
  it('fires the handler and preventDefaults a bare key', () => {
    const onR = vi.fn();
    renderHook(() => useHotkeys({ r: onR }));
    const ev = press({ key: 'r' });
    expect(onR).toHaveBeenCalledOnce();
    expect(ev.defaultPrevented).toBe(true);
  });

  it.each(['ctrlKey', 'metaKey', 'altKey'] as const)(
    'ignores the key when %s is held so browser/OS shortcuts pass through',
    (mod) => {
      const onR = vi.fn();
      renderHook(() => useHotkeys({ r: onR }));
      // e.g. Ctrl+R / Cmd+R is reload — must not be swallowed.
      const ev = press({ key: 'r', [mod]: true });
      expect(onR).not.toHaveBeenCalled();
      expect(ev.defaultPrevented).toBe(false);
    },
  );

  it('does not preventDefault when the handler returns false', () => {
    renderHook(() => useHotkeys({ k: () => false }));
    const ev = press({ key: 'k' });
    expect(ev.defaultPrevented).toBe(false);
  });
});
