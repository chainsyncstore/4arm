import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { proxiesApi } from '@/api'
import type { ProxyCreateRequest } from '@/types'

const PROXIES_KEY = 'proxies'
const PROXY_KEY = 'proxy'
const ACCOUNTS_KEY = 'accounts'

export function useProxies(skip = 0, limit = 50, status?: string, unlinked?: boolean) {
  return useQuery({
    queryKey: [PROXIES_KEY, skip, limit, status, unlinked],
    queryFn: () => proxiesApi.list(skip, limit, status, unlinked),
    staleTime: 30000,
  })
}

export function useProxy(id: string) {
  return useQuery({
    queryKey: [PROXY_KEY, id],
    queryFn: () => proxiesApi.get(id),
    enabled: !!id,
    staleTime: 30000,
  })
}

export function useCreateProxy() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: ProxyCreateRequest) => proxiesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROXIES_KEY] })
    },
  })
}

export function useImportProxies() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (file: File) => proxiesApi.importCSV(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROXIES_KEY] })
    },
  })
}

export function useDeleteProxy() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => proxiesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROXIES_KEY] })
    },
  })
}

export function useTestProxy() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => proxiesApi.test(id),
    onSuccess: (_data: unknown, id: string) => {
      queryClient.invalidateQueries({ queryKey: [PROXIES_KEY] })
      queryClient.invalidateQueries({ queryKey: [PROXY_KEY, id] })
    },
  })
}

export function useTestAllProxies() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => proxiesApi.testAll(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROXIES_KEY] })
    },
  })
}

export function useAutoAssignProxies() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => proxiesApi.autoAssign(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROXIES_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}

export function useVerifyProxyIp() {
  return useMutation({
    mutationFn: (id: string) => proxiesApi.verifyIp(id),
  })
}
