import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { songsApi } from '@/api'
import type { SongCreateRequest } from '@/types'

const SONGS_KEY = 'songs'
const SONG_KEY = 'song'
const SONG_ETA_KEY = 'song-eta'

export function useSongs(skip = 0, limit = 50, status?: string, priority?: string) {
  return useQuery({
    queryKey: [SONGS_KEY, skip, limit, status, priority],
    queryFn: () => songsApi.list(skip, limit, status, priority),
    staleTime: 30000,
  })
}

export function useSong(id: string) {
  return useQuery({
    queryKey: [SONG_KEY, id],
    queryFn: () => songsApi.get(id),
    enabled: !!id,
    staleTime: 30000,
  })
}

export function useSongETA(id: string) {
  return useQuery({
    queryKey: [SONG_ETA_KEY, id],
    queryFn: () => songsApi.getETA(id),
    enabled: !!id,
    staleTime: 60000,
  })
}

export function useCreateSong() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: SongCreateRequest) => songsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [SONGS_KEY] })
    },
  })
}

export function useUpdateSong() {
  const queryClient = useQueryClient()
  
  return useMutation<unknown, Error, { id: string; data: Partial<SongCreateRequest> }>({
    mutationFn: ({ id, data }) =>
      songsApi.update(id, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: [SONGS_KEY] })
      queryClient.invalidateQueries({ queryKey: [SONG_KEY, variables.id] })
    },
  })
}

export function useDeleteSong() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => songsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [SONGS_KEY] })
    },
  })
}

export function usePauseSong() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => songsApi.pause(id),
    onSuccess: (_data: unknown, id: string) => {
      queryClient.invalidateQueries({ queryKey: [SONGS_KEY] })
      queryClient.invalidateQueries({ queryKey: [SONG_KEY, id] })
    },
  })
}

export function useResumeSong() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (id: string) => songsApi.resume(id),
    onSuccess: (_data: unknown, id: string) => {
      queryClient.invalidateQueries({ queryKey: [SONGS_KEY] })
      queryClient.invalidateQueries({ queryKey: [SONG_KEY, id] })
    },
  })
}
