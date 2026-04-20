import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useWebSocket } from '@/contexts/WebSocketContext'

const INSTANCES_KEY = 'instances'
const INSTANCE_KEY = 'instance'
const ACCOUNTS_KEY = 'accounts'
const ACCOUNT_KEY = 'account'
const SONGS_KEY = 'songs'
const SONG_KEY = 'song'
const STREAM_LOGS_KEY = 'stream-logs'
const STREAM_LOGS_SUMMARY_KEY = 'stream-logs-summary'
const CHALLENGES_KEY = 'challenges'

interface WSMessage {
  type: string
  data?: Record<string, unknown>
  payload?: Record<string, unknown>
}

export function WebSocketEventBridge() {
  const { lastMessage } = useWebSocket()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!lastMessage) return

    const message = lastMessage as unknown as WSMessage
    const eventType = message.type

    // Normalize data/payload - backend uses both shapes
    const data = message.data || message.payload || {}

    switch (eventType) {
      case 'alert': {
        const level = (data.level as string) || 'info'
        const messageText = (data.message as string) || 'Unknown alert'

        if (level === 'error') {
          toast.error(messageText)
        } else if (level === 'warning') {
          toast.warning(messageText)
        } else {
          toast.info(messageText)
        }

        // Alerts may affect multiple areas - refresh broadly
        queryClient.invalidateQueries({ queryKey: [STREAM_LOGS_KEY] })
        queryClient.invalidateQueries({ queryKey: [STREAM_LOGS_SUMMARY_KEY] })
        break
      }

      case 'instance_status': {
        const instanceId = data.id as string | undefined
        const status = data.status as string | undefined

        if (instanceId && status) {
          // Invalidate specific instance and list
          queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, instanceId] })
          queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })

          // If instance went to error, show toast
          if (status === 'error') {
            const instanceName = (data.account_email as string) || instanceId.slice(0, 8)
            toast.error(`Instance ${instanceName} marked as error`)
          }
        }
        break
      }

      case 'stream_completed': {
        const result = data.result as string | undefined
        const songId = data.song_id as string | undefined
        const accountId = data.account_id as string | undefined
        const instanceId = data.instance_id as string | undefined

        // Invalidate related caches
        if (songId) {
          queryClient.invalidateQueries({ queryKey: [SONG_KEY, songId] })
        }
        if (accountId) {
          queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, accountId] })
        }
        if (instanceId) {
          queryClient.invalidateQueries({ queryKey: [INSTANCE_KEY, instanceId] })
        }

        // Always refresh lists and summaries
        queryClient.invalidateQueries({ queryKey: [SONGS_KEY] })
        queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
        queryClient.invalidateQueries({ queryKey: [INSTANCES_KEY] })
        queryClient.invalidateQueries({ queryKey: [STREAM_LOGS_KEY] })
        queryClient.invalidateQueries({ queryKey: [STREAM_LOGS_SUMMARY_KEY] })

        // Toast for failures
        if (result === 'fail') {
          toast.error('Stream failed - check logs for details')
        }
        break
      }

      case 'challenge_detected': {
        const challengeType = data.challenge_type as string | undefined
        const accountEmail = data.account_email as string | undefined

        // Invalidate challenges list
        queryClient.invalidateQueries({ queryKey: [CHALLENGES_KEY] })

        // Show urgent toast
        const displayEmail = accountEmail || 'Unknown account'
        const displayType = challengeType || 'Unknown'
        toast.warning(
          `Challenge detected: ${displayType} on ${displayEmail}`,
          { duration: 10000 } // Longer duration for challenges
        )
        break
      }

      case 'account_downgraded': {
        const accountId = data.account_id as string | undefined
        const email = data.email as string | undefined
        const reason = data.reason as string | undefined

        // Invalidate account data
        if (accountId) {
          queryClient.invalidateQueries({ queryKey: [ACCOUNT_KEY, accountId] })
        }
        queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })

        // Show toast
        const displayEmail = email || accountId?.slice(0, 8) || 'Unknown'
        toast.error(
          `Account ${displayEmail} downgraded${reason ? ` (${reason})` : ''}`
        )
        break
      }

      default:
        // Unknown event type - no action
        break
    }
  }, [lastMessage, queryClient])

  // This component doesn't render anything visible
  return null
}
