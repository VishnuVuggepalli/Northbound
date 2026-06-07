import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Breadcrumbs } from './Breadcrumbs';
import { queryKeys } from '@/api/queries';
import type { Device, Site } from '@/models';

afterEach(cleanup);

function seedClient(): QueryClient {
  const qc = new QueryClient();
  qc.setQueryData(queryKeys.sites(), [{ slug: 'lab', name: 'Lab' } as unknown as Site]);
  qc.setQueryData(queryKeys.devices('lab'), [
    { id: 'da70', name: 'swos-css326' } as unknown as Device,
  ]);
  return qc;
}

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={seedClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/env/:env/devices/:deviceId" element={<Breadcrumbs />} />
          <Route path="/env/:env" element={<Breadcrumbs />} />
          <Route path="/requests" element={<Breadcrumbs />} />
          <Route path="/" element={<Breadcrumbs />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Breadcrumbs', () => {
  it('builds Home › Lab › device, resolving dynamic labels from the cache', () => {
    renderAt('/env/lab/devices/da70');
    const nav = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(nav).toHaveTextContent('Home');
    expect(nav).toHaveTextContent('Lab'); // site name, not the slug
    // device crumb resolved to its name and marked current (not a link)
    const current = screen.getByText('swos-css326');
    expect(current).toHaveAttribute('aria-current', 'page');
    // Lab is a link to the env
    expect(screen.getByRole('link', { name: 'Lab' })).toHaveAttribute('href', '/env/lab');
  });

  it('shows Home › Requests for a top-level section', () => {
    renderAt('/requests');
    const nav = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(nav).toHaveTextContent('Home');
    expect(screen.getByText('Requests')).toHaveAttribute('aria-current', 'page');
  });

  it('renders nothing on the home route (no single-crumb noise)', () => {
    const { container } = renderAt('/');
    expect(container.querySelector('nav')).toBeNull();
  });
});
