import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { Layout } from '@/components/layout/Layout'
import { WebSocketProvider } from '@/contexts/WebSocketContext'
import { WebSocketEventBridge } from '@/components/WebSocketEventBridge'
import { Overview } from '@/pages/Overview'
import { Instances } from '@/pages/Instances'
import { Accounts } from '@/pages/Accounts'
import { Songs } from '@/pages/Songs'
import { Proxies } from '@/pages/Proxies'
import { Logs } from '@/pages/Logs'
import { Challenges } from '@/pages/Challenges'
import { Settings } from '@/pages/Settings'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30, // 30 seconds
      refetchInterval: 1000 * 30, // 30 seconds
      retry: 1,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <WebSocketEventBridge />
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="instances" element={<Instances />} />
              <Route path="accounts" element={<Accounts />} />
              <Route path="songs" element={<Songs />} />
              <Route path="proxies" element={<Proxies />} />
              <Route path="logs" element={<Logs />} />
              <Route path="challenges" element={<Challenges />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" theme="dark" />
      </WebSocketProvider>
    </QueryClientProvider>
  )
}

export default App
