import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { challengesApi } from '@/api'

const CHALLENGES_KEY = 'challenges'

export function useChallenges(status?: string) {
  return useQuery({
    queryKey: [CHALLENGES_KEY, status],
    queryFn: () => challengesApi.list(status),
    refetchInterval: 10000, // Poll every 10s for urgent challenges
  })
}

export function usePendingChallengeCount() {
  return useQuery({
    queryKey: [CHALLENGES_KEY, 'pending-count'],
    queryFn: () => challengesApi.getPendingCount(),
    refetchInterval: 15000,
  })
}

export function useResolveChallenge() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action, notes }: { id: string; action: string; notes?: string }) =>
      challengesApi.resolve(id, action, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [CHALLENGES_KEY] })
    },
  })
}
