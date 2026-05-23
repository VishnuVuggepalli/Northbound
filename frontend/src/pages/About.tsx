/**
 * About — ecosystem positioning page.
 *
 * Copy mirrors `supporting material/pm-plan.md` ("Ecosystem positioning"). The
 * goal: answer "why doesn't Northbound do X?" before the user asks. Linked
 * from the TopBar account menu.
 */

import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Wordmark } from '@/components/ui/Wordmark';

interface BulletProps {
  title: string;
  detail: string;
}

const NOT_BULLETS: readonly BulletProps[] = [
  {
    title: 'A monitoring or alerting platform',
    detail: 'Use LibreNMS, Observium, or Prometheus + Grafana.',
  },
  {
    title: 'A bulk config push tool',
    detail: 'Use Ansible, MikroWizard, or Napalm.',
  },
  {
    title: 'A network source-of-truth / intent model',
    detail: 'Use NetBox or Nautobot.',
  },
  {
    title: 'A multi-vendor abstraction layer',
    detail: 'Northbound ships direct drivers for five platforms. Napalm is overkill at this scale.',
  },
  {
    title: 'A firmware update orchestrator',
    detail: 'Out of scope forever — too much vendor-specific risk.',
  },
];

export function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <Link
        to="/"
        className="mb-6 inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg"
      >
        <ArrowLeft size={12} />
        <span>Back home</span>
      </Link>

      <header className="mb-8">
        <Wordmark size={20} />
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-fg">
          What Northbound is &mdash; and isn&rsquo;t
        </h1>
        <p className="mt-2 text-sm text-fg-muted">
          Read this once and 60% of your &ldquo;why doesn&rsquo;t Northbound do X?&rdquo; questions
          will already be answered.
        </p>
      </header>

      <section className="mb-8 rounded-lg border border-accent/40 bg-accent-soft p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-fg">
          What it is
        </h2>
        <p className="mt-2 text-base text-fg">
          Northbound is a <strong>request-mediated port-change workflow</strong>. Alice needs port
          14 on VLAN 200; she files a request, an admin sees the rendered diff, clicks apply, and
          the change ships in about 30 seconds with backup, audit, and rollback.
        </p>
        <p className="mt-2 text-sm text-fg-muted">
          It targets a specific tooling gap between &ldquo;observing the network&rdquo; and
          &ldquo;mass-changing the network&rdquo; &mdash; the boring everyday port move that
          interrupts everybody&rsquo;s day.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted">
          What it is NOT
        </h2>
        <ul className="mt-3 space-y-3">
          {NOT_BULLETS.map((b) => (
            <li
              key={b.title}
              className="rounded-md border border-border bg-bg-elev-1 px-4 py-3 text-sm"
            >
              <div className="font-medium text-fg">{b.title}</div>
              <div className="mt-1 text-fg-muted">{b.detail}</div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mb-8 rounded-md border border-border bg-bg-elev-1 p-5 text-sm text-fg">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted">
          How it fits with what you already run
        </h2>
        <p className="mt-2">
          Northbound <strong>complements</strong> the tools above. Keep LibreNMS for graphs and
          alerts. Keep NetBox if you have it. Run Northbound for the day-to-day port move that
          would otherwise be a Slack ping, a context switch, and a CLI session.
        </p>
      </section>

      <section className="text-xs text-fg-subtle">
        <p>
          When a change falls outside this scope &mdash; complex BGP, vendor-specific knobs, SwOS
          writes &mdash; Northbound surfaces an <strong>&ldquo;Open in vendor UI&rdquo;</strong>{' '}
          button so you escape cleanly to the device&rsquo;s native interface. No dead ends.
        </p>
      </section>
    </div>
  );
}
