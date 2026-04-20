import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { instancesApi, systemApi } from '@/api'
import type { InstanceCreateRequest } from '@/types'

const INSTANCES_KEY = 'instances'
const INSTANCE_KEY = 'instance'
const CAPACITY_KEY = 'capacity'

export function useInstances(skip = 0, limit = 50, status?: string) {
  return useQuery({
    queryKey: [INSTANCES_KEY, skip, limit, status],
    queryFn: () => instancesApi.list(skip, limit, status),
    staleTime: 30000,
  })
}

export function useInstance(id: string) {
  return useQuery({
    queryKey: [INSTANCE_KEY, id],
    queryFn: () => instancesApi.get(id),
    enabled: !!id,
    staleTime: 30000,
  })
}

export function useCapacity() {
  return useQuery({
    queryKey: [CAPACITY_KEY],
    queryFn: () => systemApi.getCapacity(),
    staleTime: 5000,
  })
}

export function useCreateInstance() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: InstanceCreateRequest) => instancesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [CAPACITY_KEY] })
    },
  })
}

export function useStartInstance() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => instancesApi.start(id),
    onSuccess: (_data: unknown, id: string) => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, id] })
    },
  })
}

export function useStopInstance() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => instancesApi.stop(id),
    onSuccess: (_data: unknown, id: string) => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, id] })
    },
  })
}

export function useRestartInstance() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => instancesApi.restart(id),
    onSuccess: (_data: unknown, id: string) => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, id] })
    },
  })
}

export function useDestroyInstance() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => instancesApi.destroy(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [CAPACITY_KEY] })
    },
  })
}

export function useAssignAccount() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ instanceId, accountId }: { instanceId: string; accountId: string }) =>
      instancesApi.assignAccount(instanceId, accountId),
    onSuccess: (_data: unknown, variables: { instanceId: string; accountId: string }) => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, variables.instanceId] })
    },
  })
}

export function useUnassignAccount() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (instanceId: string) => instancesApi.unassignAccount(instanceId),
    onSuccess: (_data: unknown, instanceId: string) => {
      queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
      queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, instanceId] })
    },
  })
}
