import { Outlet, useParams } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { useUIStore } from '@/store/ui';
import { useEffect } from 'react';
import type { Environment } from '@/types';

export function EnvironmentPage() {
  const { env } = useParams<{ env: Environment }>();
  const setEnv = useUIStore((s) => s.setEnv);

  useEffect(() => {
    if (env) setEnv(env);
  }, [env, setEnv]);

  if (!env) return null;

  return (
    // viewport − TopBar (3.5rem) − Breadcrumb bar (2rem)
    <div className="flex h-[calc(100vh-3.5rem-2rem)]">
      <Sidebar env={env} />
      <section aria-label={`${env} site`} className="relative flex-1 overflow-hidden">
        <Outlet />
      </section>
    </div>
  );
}
