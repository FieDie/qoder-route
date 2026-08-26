import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { AuthGate } from './components/auth/AuthGate'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => {
        if (error instanceof Error && error.message === 'Invalid API key') return false
        return count < 2
      },
      staleTime: 3000,
      refetchOnWindowFocus: true,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthGate>
          <AppLayout />
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  )
}