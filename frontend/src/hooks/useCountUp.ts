import { useEffect, useRef, useState } from 'react'

/** Animates a number from 0 to `target` with easeOutCubic. */
export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0)
  const raf = useRef<number>(0)
  const start = useRef<number>(0)
  const from = useRef(0)

  useEffect(() => {
    from.current = value
    start.current = performance.now()

    const tick = (now: number) => {
      const elapsed = now - start.current
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = from.current + (target - from.current) * eased
      setValue(current)
      if (progress < 1) raf.current = requestAnimationFrame(tick)
    }

    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, duration])

  return value
}