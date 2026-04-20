import { createContext, useContext, useEffect, useRef, useState, useCallback, type ReactNode } from 'react'
import type { WebSocketMessage } from '@/types'

interface WebSocketContextType {
  isConnected: boolean
  lastMessage: WebSocketMessage | null
  sendMessage: (message: WebSocketMessage) => void
  reconnect: () => void
}

const WebSocketContext = createContext<WebSocketContextType | null>(null)

const isLocalDevHost = ['localhost', '127.0.0.1'].includes(window.location.hostname)
const WS_URL = import.meta.env.DEV && isLocalDevHost
  ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:8000/ws/dashboard`
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/dashboard`
const RECONNECT_DELAY = 5000
const MAX_RECONNECT_ATTEMPTS = 10
const PING_INTERVAL = 30000

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const silentCloseSocketsRef = useRef(new WeakSet<WebSocket>())

  const connect = useCallback(() => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN
      || wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    try {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('WebSocket connected')
        setIsConnected(true)
        reconnectAttemptsRef.current = 0

        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, PING_INTERVAL)
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage
          setLastMessage(message)
        } catch {
          console.error('Failed to parse WebSocket message')
        }
      }

      ws.onclose = () => {
        const wasIntentional = silentCloseSocketsRef.current.has(ws)

        if (!wasIntentional) {
          console.log('WebSocket disconnected')
        }

        if (wsRef.current === ws) {
          wsRef.current = null
        }

        setIsConnected(false)
        
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
          pingIntervalRef.current = null
        }

        if (!wasIntentional && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1
          const delay = RECONNECT_DELAY * Math.min(reconnectAttemptsRef.current, 5)
          console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`)
          
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
        }
      }

      ws.onerror = () => {
        if (!silentCloseSocketsRef.current.has(ws)) {
          setIsConnected(false)
        }
      }
    } catch {
      console.error('Failed to create WebSocket connection')
    }
  }, [])

  const sendMessage = useCallback((message: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    } else {
      console.warn('WebSocket is not connected')
    }
  }, [])

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      silentCloseSocketsRef.current.add(wsRef.current)
      wsRef.current.close()
    }
    connect()
  }, [connect])

  useEffect(() => {
    connect()

    return () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        silentCloseSocketsRef.current.add(wsRef.current)
        wsRef.current.close()
      }
    }
  }, [connect])

  return (
    <WebSocketContext.Provider value={{ isConnected, lastMessage, sendMessage, reconnect }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocket() {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider')
  }
  return context
}
