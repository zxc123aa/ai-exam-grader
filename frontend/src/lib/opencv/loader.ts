/**
 * OpenCV.js Web Worker manager.
 *
 * Manages the lifecycle of a classic Web Worker that loads OpenCV.js via
 * importScripts. Provides a Promise-based API for client-side image
 * preprocessing.
 *
 * The worker file is at /preprocessor-worker.js (served from public/).
 */

import type {
  PageQuad,
  PreprocessOptions,
  PreprocessResult,
  WorkerRequest,
  WorkerResponse,
} from "./types"

// ---- Worker singleton -------------------------------------------------------

let workerInstance: Worker | null = null
let workerReady = false
let nextId = 0
const pendingRequests = new Map<
  string,
  {
    resolve: (value: PreprocessResult) => void
    reject: (reason: Error) => void
    timeout: ReturnType<typeof setTimeout>
  }
>()

const WORKER_TIMEOUT_MS = 30_000 // 30s total for OpenCV load + processing
const PING_TIMEOUT_MS = 5_000

function generateId(): string {
  nextId += 1
  return `preprocess_${nextId}_${Date.now()}`
}

function destroyWorker(): void {
  if (workerInstance) {
    workerInstance.terminate()
    workerInstance = null
  }
  workerReady = false
  for (const [, pending] of pendingRequests) {
    clearTimeout(pending.timeout)
    pending.reject(new Error("Worker terminated"))
  }
  pendingRequests.clear()
}

function createWorker(): Worker {
  const worker = new Worker("/preprocessor-worker.js")

  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const msg = event.data
    if (!msg?.id) return

    const pending = pendingRequests.get(msg.id)
    if (!pending) return

    clearTimeout(pending.timeout)
    pendingRequests.delete(msg.id)

    if (msg.type === "result" && msg.pages) {
      pending.resolve({
        pages: msg.pages,
        metadata: msg.metadata ?? {},
      })
    } else if (msg.type === "pong") {
      // Ping response — handled in waitForReady
    } else {
      pending.reject(new Error(msg.message || "Unknown worker error"))
    }
  }

  worker.onerror = (event: ErrorEvent) => {
    console.error("[preprocessing] Worker error:", event.message)
    // Reject all pending requests
    for (const [, pending] of pendingRequests) {
      clearTimeout(pending.timeout)
      pending.reject(new Error(`Worker error: ${event.message}`))
    }
    pendingRequests.clear()
    workerReady = false
    workerInstance = null
  }

  return worker
}

/**
 * Get (or create) the preprocessing worker.
 * The worker is created lazily on first use.
 */
export function getPreprocessingWorker(): Worker {
  if (workerInstance) return workerInstance

  workerInstance = createWorker()
  return workerInstance
}

/**
 * Wait for the worker to be ready (OpenCV.js loaded).
 */
async function waitForReady(worker: Worker): Promise<void> {
  const id = generateId()
  return new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => {
      worker.removeEventListener("message", handler)
      pendingRequests.delete(id)
      reject(
        new Error("Worker ping timed out — OpenCV.js may have failed to load"),
      )
    }, PING_TIMEOUT_MS)

    const handler = (event: MessageEvent<WorkerResponse>) => {
      const msg = event.data
      if (msg.id === id && msg.type === "pong") {
        clearTimeout(timeout)
        worker.removeEventListener("message", handler)
        if (msg.cvReady) {
          resolve()
        } else {
          reject(new Error("OpenCV.js is not available in the worker"))
        }
      }
    }

    worker.addEventListener("message", handler)
    worker.postMessage({ id, type: "ping" } satisfies WorkerRequest)
  })
}

/**
 * Check if the client-side preprocessing worker is available and ready.
 */
export function isPreprocessingAvailable(): boolean {
  return workerReady
}

/**
 * Preprocess an image with the given page quads using client-side OpenCV.js.
 *
 * @param imageBuffer - Raw image bytes (JPEG or PNG) as ArrayBuffer
 * @param quads - Array of page quads in pixel coordinates (not normalized)
 * @param options - Preprocessing options
 * @returns Promise resolving to the preprocessed pages and metadata
 */
export async function preprocessWithQuads(
  imageBuffer: ArrayBuffer,
  quads: PageQuad[],
  options: PreprocessOptions = {},
): Promise<PreprocessResult> {
  const worker = getPreprocessingWorker()

  // Wait for the worker to be ready (OpenCV.js loaded)
  if (!workerReady) {
    await waitForReady(worker)
    workerReady = true
  }

  const id = generateId()

  return new Promise<PreprocessResult>((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingRequests.delete(id)
      reject(new Error("Preprocessing timed out"))
    }, WORKER_TIMEOUT_MS)

    pendingRequests.set(id, { resolve, reject, timeout })

    const message: WorkerRequest = {
      id,
      type: "preprocess",
      imageBuffer,
      quads,
      options,
    }

    // Transfer the image buffer to avoid copying
    worker.postMessage(message, [imageBuffer])
  })
}

/**
 * Terminate the preprocessing worker and release resources.
 * A new worker will be created on the next call.
 */
export function terminateWorker(): void {
  destroyWorker()
}
