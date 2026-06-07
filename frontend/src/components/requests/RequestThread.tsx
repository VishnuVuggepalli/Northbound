import { useState } from 'react';
import { Button } from '@/shared/Button';
import { Textarea } from '@/shared/Input';
import { useAddRequestComment, useRequestTimeline } from '@/api/queries';
import { timeAgo } from '@/lib/format';

/**
 * Per-request conversation: the unified event timeline (status transitions +
 * comments, oldest first) plus a comment box. Backed by the request's
 * ChangeRequestEvent log; polls lightly while open for near-realtime.
 */
export function RequestThread({ requestId, open }: { requestId: string; open: boolean }) {
  const { data: events = [], isLoading } = useRequestTimeline(requestId, open);
  const add = useAddRequestComment(requestId);
  const [draft, setDraft] = useState('');

  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">
        Conversation
      </div>
      <div className="space-y-1">
        {events.map((e) => (
          <div key={e.id} className="flex items-baseline gap-2 text-xs">
            <span className="nb-mono shrink-0 text-fg">
              @{e.actor_username ?? e.actor.slice(0, 8)}
            </span>
            {e.kind === 'comment' ? (
              <span className="text-fg-muted">{e.body}</span>
            ) : (
              <span className="italic text-fg-subtle">
                {e.from_status && e.from_status !== e.to_status
                  ? `${e.from_status} → ${e.to_status}`
                  : `→ ${e.to_status}`}
              </span>
            )}
            <span className="ml-auto shrink-0 text-fg-subtle" title={e.created_at}>
              {timeAgo(new Date(e.created_at).getTime())}
            </span>
          </div>
        ))}
        {events.length === 0 && (
          <p className="text-xs text-fg-subtle">{isLoading ? 'Loading…' : 'No comments yet.'}</p>
        )}
      </div>
      <form
        className="flex items-end gap-2"
        onSubmit={(ev) => {
          ev.preventDefault();
          const body = draft.trim();
          if (!body) return;
          add.mutate(body, { onSuccess: () => setDraft('') });
        }}
      >
        <Textarea
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a comment…"
          className="flex-1"
        />
        <Button type="submit" kind="primary" size="sm" disabled={!draft.trim() || add.isPending}>
          {add.isPending ? 'Sending…' : 'Send'}
        </Button>
      </form>
    </div>
  );
}
