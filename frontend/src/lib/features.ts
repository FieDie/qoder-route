import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

/**
 * Worker page is optional: the public build ships without the trial-activation
 * worker. import.meta.glob resolves at build time — when the file is absent
 * the glob is empty and the page/route simply do not register, no build error.
 */
const workerGlob = import.meta.glob<{ Worker: ComponentType }>('../components/worker/Worker.tsx')
const workerLoader = workerGlob['../components/worker/Worker.tsx']

export const WORKER_ENABLED = workerLoader !== undefined

export const WorkerPage: LazyExoticComponent<ComponentType> | null = workerLoader
  ? lazy(() => workerLoader().then((m) => ({ default: m.Worker })))
  : null
