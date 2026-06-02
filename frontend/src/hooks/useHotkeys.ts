/**
 * Keyboard shortcut hooks.
 *
 * Two flavors:
 *   - `useHotkeys` for single-key bindings (e.g. `/`, `?`, `r`, `Escape`).
 *   - `useSequenceHotkeys` for vim-flavored two-key sequences (`g l`, `g d`).
 *
 * Listeners ignore keystrokes targeted at form controls (except `Escape`),
 * so the user can type into search inputs without accidentally triggering
 * shortcuts.
 */

import { useEffect, useRef } from 'react';

type HotkeyHandler = (e: KeyboardEvent) => boolean | void;

function isFormElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

export function useHotkeys(map: Record<string, HotkeyHandler>): void {
  const mapRef = useRef(map);
  mapRef.current = map;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Never shadow browser/OS shortcuts: a bare 'r' is "request", but Ctrl/Cmd+R
      // is reload — without this guard the handler ran and preventDefault() blocked
      // the page refresh. Let any modified chord through to the browser.
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isFormElement(e.target) && e.key !== 'Escape') return;
      const handler =
        mapRef.current[e.key.toLowerCase()] ?? mapRef.current[e.key];
      if (!handler) return;
      const result = handler(e);
      if (result !== false) e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

/**
 * Two-key sequence shortcuts. Prefix is held for ~900ms then cleared.
 * Only `g`-prefixed sequences are wired (matches the prototype).
 */
export function useSequenceHotkeys(map: Record<string, () => void>): void {
  const mapRef = useRef(map);
  mapRef.current = map;

  useEffect(() => {
    let prefix: string | null = null;
    let timer: number | null = null;

    const reset = () => {
      prefix = null;
      if (timer != null) window.clearTimeout(timer);
      timer = null;
    };

    const onKey = (e: KeyboardEvent) => {
      if (isFormElement(e.target)) return;
      const k = e.key.toLowerCase();
      if (prefix) {
        const combo = `${prefix} ${k}`;
        const fn = mapRef.current[combo];
        if (fn) {
          fn();
          e.preventDefault();
          reset();
          return;
        }
        reset();
      }
      if (k === 'g' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        prefix = 'g';
        e.preventDefault();
        timer = window.setTimeout(reset, 900);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      reset();
    };
  }, []);
}
