import { apiClient } from './client'
import type { SystemCapacity, SystemResources } from '@/types'

export const systemApi = {
  getCapacity: async () => {
    return apiClient.get<SystemCapacity>('/system/capacity')
  },

  getResources: async () => {
    return apiClient.get<SystemResources>('/system/resources')
  },
}
