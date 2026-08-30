import { useEffect } from 'react'

/** Chrome freezes rAF / timers after ~5 min in a background tab. Kick layout
 *  (Recharts) when the page is shown again so frozen views don't stay blank. */
export function usePageResume() {
  useEffect(() => {
    const kick = () => window.dispatchEvent(new Event('resize'))
    const onVis = () => {
      if (!document.hidden) kick()
    }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('pageshow', kick)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('pageshow', kick)
    }
  }, [])
}
