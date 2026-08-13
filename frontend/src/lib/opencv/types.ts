/**
 * TypeScript type declarations for the OpenCV.js global (cv).
 *
 * This covers only the subset of the OpenCV.js API used by the client-side
 * preprocessing pipeline. OpenCV.js is loaded as a classic script in the
 * Web Worker; these types document the API surface for type-checking the
 * driver code in src/lib/opencv/loader.ts.
 */

export interface CVSize {
  width: number
  height: number
}

export interface CVPoint {
  x: number
  y: number
}

export interface CVRect {
  x: number
  y: number
  width: number
  height: number
}

export type CVScalar = Record<number, number>

export interface CVMat {
  rows: number
  cols: number
  /** Raw data as Uint8Array (for CV_8U mats) */
  data: Uint8Array
  /** Raw data as Uint8Array */
  data8S: Int8Array
  /** Raw data as Uint16Array */
  data16U: Uint16Array
  /** Raw data as Int16Array */
  data16S: Int16Array
  /** Raw data as Int32Array */
  data32S: Int32Array
  /** Raw data as Float32Array */
  data32F: Float32Array
  /** Raw data as Float64Array */
  data64F: Float64Array
  /** Channel count */
  channels(): number
  /** Element size in bytes */
  elemSize(): number
  /** Clone the mat */
  clone(): CVMat
  /** Release memory */
  delete(): void
  /** Extract ROI */
  roi(rect: CVRect): CVMat
}

export interface CVMatVector {
  get(index: number): CVMat
  set(index: number, mat: CVMat): void
  push_back(mat: CVMat): void
  size(): number
  delete(): void
}

export interface CVCLAHE {
  apply(src: CVMat, dst: CVMat): void
  delete(): void
}

export declare var cv: {
  // --- Constants ---
  readonly CV_8U: number
  readonly CV_8UC3: number
  readonly CV_8UC4: number
  readonly CV_32F: number
  readonly CV_32FC2: number
  readonly CV_64F: number

  readonly INTER_LINEAR: number
  readonly INTER_CUBIC: number
  readonly INTER_AREA: number
  readonly BORDER_CONSTANT: number

  readonly COLOR_BGR2GRAY: number
  readonly COLOR_BGR2Lab: number
  readonly COLOR_Lab2BGR: number
  readonly COLOR_BGR2RGB: number

  readonly THRESH_BINARY_INV: number
  readonly THRESH_OTSU: number

  readonly IMWRITE_JPEG_QUALITY: number
  readonly IMWRITE_PNG_COMPRESSION: number
  readonly IMREAD_COLOR: number

  readonly REDUCE_SUM: number

  // --- Mat ---
  Mat: {
    new (): CVMat
  }

  // --- MatVector ---
  MatVector: {
    new (): CVMatVector
  }

  // --- Size ---
  Size: {
    new (width: number, height: number): CVSize
  }

  // --- Point ---
  Point: {
    new (x: number, y: number): CVPoint
  }

  // --- Rect ---
  Rect: {
    new (x: number, y: number, width: number, height: number): CVRect
  }

  // --- Scalar ---
  Scalar: {
    new (v0: number, v1: number, v2: number, v3?: number): CVScalar
  }

  // --- CLAHE ---
  CLAHE: {
    new (clipLimit: number, tileGridSize: CVSize): CVCLAHE
  }

  // --- Image I/O ---
  imdecode(buf: Uint8Array, flags: number): CVMat
  imencode(
    ext: string,
    img: CVMat,
    buf?: CVMatVector | CVMat,
    params?: number[],
  ): CVMat | CVMatVector

  // --- Matrix creation ---
  matFromArray(rows: number, cols: number, type: number, data: number[]): CVMat

  // --- Color conversion ---
  cvtColor(src: CVMat, dst: CVMat, code: number, dstCn?: number): void

  // --- Split / Merge ---
  split(src: CVMat, dst: CVMatVector): void
  merge(src: CVMatVector, dst: CVMat): void

  // --- Geometric transforms ---
  getPerspectiveTransform(src: CVMat, dst: CVMat): CVMat
  warpPerspective(
    src: CVMat,
    dst: CVMat,
    m: CVMat,
    dsize: CVSize,
    flags?: number,
    borderMode?: number,
    borderValue?: CVScalar,
  ): void
  getRotationMatrix2D(center: CVPoint, angle: number, scale: number): CVMat
  warpAffine(
    src: CVMat,
    dst: CVMat,
    m: CVMat,
    dsize: CVSize,
    flags?: number,
    borderMode?: number,
    borderValue?: CVScalar,
  ): void

  // --- Image processing ---
  resize(
    src: CVMat,
    dst: CVMat,
    dsize: CVSize,
    fx?: number,
    fy?: number,
    interpolation?: number,
  ): void
  GaussianBlur(
    src: CVMat,
    dst: CVMat,
    ksize: CVSize,
    sigmaX: number,
    sigmaY?: number,
  ): void
  Canny(
    src: CVMat,
    dst: CVMat,
    threshold1: number,
    threshold2: number,
    apertureSize?: number,
  ): void
  HoughLinesP(
    src: CVMat,
    dst: CVMat,
    rho: number,
    theta: number,
    threshold: number,
    minLineLength?: number,
    maxLineGap?: number,
  ): CVMat
  threshold(
    src: CVMat,
    dst: CVMat,
    thresh: number,
    maxval: number,
    type: number,
  ): void
  Laplacian(src: CVMat, dst: CVMat, ddepth: number, ksize?: number): void
  fastNlMeansDenoisingColored(
    src: CVMat,
    dst: CVMat,
    h: number,
    hColor: number,
    templateWindowSize: number,
    searchWindowSize: number,
  ): void
  reduce(
    src: CVMat,
    dst: CVMat,
    dim: number,
    rtype: number,
    dtype: number,
  ): void
  meanStdDev(src: CVMat, mean: CVMat, stddev: CVMat): void

  // --- Runtime ---
  onRuntimeInitialized?: (() => void) | undefined
}

// ---- Application-level types ------------------------------------------------

/** A single page quad: 4 corner points in pixel coordinates */
export type PageQuad = [
  [number, number],
  [number, number],
  [number, number],
  [number, number],
]

/** Preprocessed page result from the worker */
export interface PreprocessedPage {
  name: string
  buffer: ArrayBuffer
  width: number
  height: number
  sharpness: number
  deskew: Record<string, unknown>
  sourceQuad: [number, number][]
}

/** Worker result for a preprocess request */
export interface PreprocessResult {
  pages: PreprocessedPage[]
  metadata: Record<string, unknown>
}

/** Options for the preprocessing pipeline */
export interface PreprocessOptions {
  marginMode?: "conservative" | "minimal" | "safe"
  applyDeskew?: boolean
  jpegQuality?: number
  splitAxis?: "horizontal" | "vertical"
}

/** Worker message types (request) */
export interface WorkerRequest {
  id: string
  type: "preprocess" | "ping"
  imageBuffer?: ArrayBuffer
  quads?: PageQuad[]
  options?: PreprocessOptions
}

/** Worker message types (response) */
export interface WorkerResponse {
  id: string
  type: "result" | "error" | "pong"
  pages?: PreprocessedPage[]
  metadata?: Record<string, unknown>
  message?: string
  cvReady?: boolean
}
