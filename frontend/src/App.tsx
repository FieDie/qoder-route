import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 3000,
      gcTime: 30 * 60 * 1000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      networkMode: 'always',
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
