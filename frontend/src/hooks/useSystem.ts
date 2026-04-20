import { useQuery } from '@tanstack/react-query'
import { systemApi } from '@/api'

const SYSTEM_CAPACITY_KEY = 'system-capacity'
const SYSTEM_RESOURCES_KEY = 'system-resources'

export function useSystemCapacity() {
  return useQuery({
    queryKey: [SYSTEM_CAPACITY_KEY],
    queryFn: () => systemApi.getCapacity(),
    staleTime: 10000,
  })
}

export function useSystemResources() {
  return useQuery({
    queryKey: [SYSTEM_RESOURCES_KEY],
    queryFn: () => systemApi.getResources(),
    staleTime: 5000,
    refetchInterval: 10000,
  })
}
