import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { accountsApi } from '@/api'
import type { AccountBatchCreateRequest, AccountCreateRequest } from '@/types'

const ACCOUNTS_KEY = 'accounts'
const ACCOUNT_KEY = 'account'

export function useAccounts(skip = 0, limit = 50, status?: string, type?: string) {
  return useQuery({
    queryKey: [ACCOUNTS_KEY, skip, limit, status, type],
    queryFn: () => accountsApi.list(skip, limit, status, type),
    staleTime: 30000,
  })
}

export function useAccount(id: string) {
  return useQuery({
    queryKey: [ACCOUNT_KEY, id],
    queryFn: () => accountsApi.get(id),
    enabled: !!id,
    staleTime: 30000,
  })
}

export function useCreateAccount() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: AccountCreateRequest) => accountsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}

export function useCreateBatchAccounts() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request: AccountBatchCreateRequest) => accountsApi.createBatch(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}

export function useRegisterAccounts() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: AccountBatchCreateRequest) => accountsApi.register(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}

export function useImportAccounts() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (file: File) => accountsApi.importCSV(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}

export function useUpdateAccount() {
  const queryClient = useQueryClient()
  
  return useMutation<unknown, Error, { id: string; data: Partial<AccountCreateRequest> }>({
    mutationFn: ({ id, data }) =>
      accountsApi.update(id, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, variables.id] })
    },
  })
}

export function useDeleteAccount() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => accountsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}

export function useLinkProxy() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ accountId, proxyId }: { accountId: string; proxyId: string }) =>
      accountsApi.linkProxy(accountId, proxyId),
    onSuccess: (_data: unknown, variables: { accountId: string; proxyId: string }) => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, variables.accountId] })
    },
  })
}

export function useSetCooldown() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ accountId, hours }: { accountId: string; hours: number }) =>
      accountsApi.setCooldown(accountId, hours),
    onSuccess: (_data: unknown, variables: { accountId: string; hours: number }) => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, variables.accountId] })
    },
  })
}

export function useForceActive() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (accountId: string) => accountsApi.forceActive(accountId),
    onSuccess: (_data: unknown, accountId: string) => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, accountId] })
    },
  })
}

export function useExtractSession() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ accountId, deviceId }: { accountId: string; deviceId?: string }) =>
      accountsApi.extractSession(accountId, deviceId),
    onSuccess: (_data: unknown, variables: { accountId: string }) => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, variables.accountId] })
    },
  })
}

export function useInjectSession() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ accountId, deviceId }: { accountId: string; deviceId?: string }) =>
      accountsApi.injectSession(accountId, deviceId),
    onSuccess: (_data: unknown, variables: { accountId: string }) => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
      queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, variables.accountId] })
    },
  })
}
