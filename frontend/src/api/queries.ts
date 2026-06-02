/**
 * React Query keys + hooks.
 *
 * Centralizing keys here means cache invalidation is a grep instead of a
 * cross-tree refactor. Mutations live next to the queries they invalidate.
 */

import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { apiClient as api } from './index';
import type { ChangeRequestStatus, Environment } from '@/types';

export const queryKeys = {
  platforms: () => ['platforms'] as const,
  devices: (env?: Environment) => ['devices', env ?? 'all'] as const,
  device: (id: string) => ['devices', id] as const,
  ports: (deviceId: string) => ['devices', deviceId, 'ports'] as const,
  allPorts: () => ['ports'] as const,
  links: (env?: Environment) => ['links', env ?? 'all'] as const,
  requests: (filter?: { mine?: string; status?: ChangeRequestStatus }) =>
    ['requests', filter?.mine ?? 'all', filter?.status ?? 'all'] as const,
  audit: (deviceId?: string, port?: string) =>
    ['audit', deviceId ?? 'all', port ?? 'all'] as const,
  users: () => ['users'] as const,
  sites: () => ['sites'] as const,
  system: (deviceId: string) => ['devices', deviceId, 'system'] as const,
  protocol: (deviceId: string, slug: string) =>
    ['devices', deviceId, 'protocol', slug] as const,
  vlans: (deviceId: string) => ['devices', deviceId, 'vlans'] as const,
  l3: (deviceId: string) => ['devices', deviceId, 'l3-interfaces'] as const,
  settings: () => ['settings'] as const,
} as const;

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings(), queryFn: () => api.getSettings() });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<import('./realClient').RuntimeSettings>) =>
      api.updateSettings(patch),
    onSuccess: (data) => qc.setQueryData(queryKeys.settings(), data),
  });
}

export function useDevices(env?: Environment) {
  return useQuery({
    queryKey: queryKeys.devices(env),
    queryFn: () => api.listDevices(env),
  });
}

export function useDevice(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.device(id ?? ''),
    queryFn: () => api.getDevice(id as string),
    enabled: !!id,
  });
}

export function usePorts(deviceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.ports(deviceId ?? ''),
    queryFn: () => api.listPortsForDevice(deviceId as string),
    enabled: !!deviceId,
    staleTime: 30_000,
  });
}

export function useAllPorts() {
  return useQuery({ queryKey: queryKeys.allPorts(), queryFn: () => api.listAllPorts() });
}

export function useLinks(env?: Environment) {
  return useQuery({ queryKey: queryKeys.links(env), queryFn: () => api.listLinks(env) });
}

export function useRequests(filter?: { mine?: string; status?: ChangeRequestStatus }) {
  return useQuery({
    queryKey: queryKeys.requests(filter),
    queryFn: () => api.listRequests(filter),
  });
}

export function useAudit(deviceId?: string, portName?: string) {
  return useQuery({
    queryKey: queryKeys.audit(deviceId, portName),
    queryFn: () => api.listAudit({ device_id: deviceId, port_name: portName }),
  });
}

export function usePlatforms() {
  return useQuery({ queryKey: queryKeys.platforms(), queryFn: () => api.listPlatforms() });
}

export function useSites() {
  return useQuery({ queryKey: queryKeys.sites(), queryFn: () => api.listSites() });
}

export function useSystemInfo(deviceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.system(deviceId ?? ''),
    queryFn: () => api.getSystemInfo(deviceId!),
    enabled: !!deviceId,
  });
}

export function useProtocolDetail(deviceId: string, slug: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.protocol(deviceId, slug),
    queryFn: () => api.getProtocolDetail(deviceId, slug),
    enabled,
  });
}

export function useVlans(deviceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.vlans(deviceId ?? ''),
    queryFn: () => api.getVlans(deviceId!),
    enabled: !!deviceId,
  });
}

export function useL3Interfaces(deviceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.l3(deviceId ?? ''),
    queryFn: () => api.getL3Interfaces(deviceId!),
    enabled: !!deviceId,
  });
}

/* ------------------------------------ mutations ------------------------------------ */

export function useCreateSite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { slug: string; name: string }) => api.createSite(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.sites() }),
  });
}

export function useUpdatePortMetadata(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      portName: string;
      patch: { host_model?: string; bmc_ip?: string; notes?: string };
    }) => api.updatePortMetadata(deviceId, input.portName, input.patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ports(deviceId) });
      qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
    },
  });
}

export function useSetPortDescription(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { portName: string; description: string }) =>
      api.setPortDescription(deviceId, input.portName, input.description),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ports(deviceId) });
      qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
      qc.invalidateQueries({ queryKey: ['devices', deviceId, 'config'] });
    },
  });
}

export function useSetPortConfig(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { portName: string; patch: import('./realClient').PortConfigPatch }) =>
      api.setPortConfig(deviceId, input.portName, input.patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ports(deviceId) });
      qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
      qc.invalidateQueries({ queryKey: queryKeys.vlans(deviceId) });
      qc.invalidateQueries({ queryKey: ['devices', deviceId, 'config'] });
    },
  });
}

function invalidateRequestsAndPorts(qc: QueryClient, deviceId: string) {
  qc.invalidateQueries({ queryKey: ['requests'] });
  qc.invalidateQueries({ queryKey: queryKeys.ports(deviceId) });
  qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
}

export function useCreateRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createRequest,
    onSuccess: (req) => invalidateRequestsAndPorts(qc, req.device_id),
  });
}

export function useApproveRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reviewer }: { id: string; reviewer: string }) =>
      api.approveRequest(id, reviewer),
    onSuccess: (req) => invalidateRequestsAndPorts(qc, req.device_id),
  });
}

export function useRejectRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reviewer, comment }: { id: string; reviewer: string; comment: string }) =>
      api.rejectRequest(id, reviewer, comment),
    onSuccess: (req) => invalidateRequestsAndPorts(qc, req.device_id),
  });
}

export function useApplyRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reviewer }: { id: string; reviewer: string }) =>
      api.applyRequest(id, reviewer),
    onSuccess: (req) => invalidateRequestsAndPorts(qc, req.device_id),
  });
}

export function useConfirmRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string }) => api.confirmRequest(id),
    onSuccess: (req) => invalidateRequestsAndPorts(qc, req.device_id),
  });
}

export function useTestConnection() {
  return useMutation({ mutationFn: api.testConnection });
}

export function useDiscoverDevice() {
  return useMutation({ mutationFn: api.discoverDevice });
}

export function useConfirmOnboard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.confirmOnboard,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['devices'] });
      qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
    },
  });
}
