/**
 * Preprocessor Web Worker for client-side exam photo rectification.
 *
 * Mirrors backend/app/services/exam_photo_preprocessing.py pixel-for-pixel
 * using OpenCV.js (4.13.0 WASM) matching the server's opencv-python-headless.
 *
 * Orientation normalization (Gemini) is NOT included — it stays server-side.
 *
 * Protocol:
 *   In:  { id, type: "preprocess", imageBuffer: ArrayBuffer, quads: [[x,y]*4], options }
 *   Out: { id, type: "result", pages: [{name, buffer: ArrayBuffer, width, height}], metadata }
 *   Err: { id, type: "error", message }
 */

// ---- OpenCV loader --------------------------------------------------------

let cvReady = false
let cvLoading = false
let cvResolveQueue = []

function waitForCV() {
  if (cvReady) return Promise.resolve()
  if (!cvLoading && typeof cv === "undefined") {
    return Promise.reject(new Error("OpenCV.js failed to load"))
  }
  return new Promise((resolve, reject) => {
    cvResolveQueue.push(() => {
      if (cvReady) resolve()
      else reject(new Error("OpenCV.js failed to load"))
    })
  })
}

function onCVReady() {
  cvReady = true
  cvResolveQueue.forEach((cb) => {
    cb()
  })
  cvResolveQueue = []
}

var origOnReady, queue, q
if (typeof importScripts === "function") {
  cvLoading = true
  try {
    importScripts("/opencv/opencv.js")
    if (typeof cv !== "undefined") {
      if (cv.onRuntimeInitialized) {
        origOnReady = cv.onRuntimeInitialized
        cv.onRuntimeInitialized = () => {
          origOnReady?.()
          onCVReady()
        }
      } else {
        // opencv.js may already be initialized
        onCVReady()
      }
    }
  } catch (e) {
    cvReady = false
    cvLoading = false
    console.error("[preprocessor-worker] Failed to load OpenCV.js:", e)
    // Reject all queued waiters so preprocess/ping handlers don't hang forever
    queue = cvResolveQueue
    cvResolveQueue = []
    for (q = 0; q < queue.length; q++) {
      try {
        queue[q]()
      } catch (_) {
        /* best-effort */
      }
    }
  }
}

// ---- Memory helpers --------------------------------------------------------

/**
 * Delete a Mat or MatVector safely (no-op if null/undefined).
 */
function safeDelete(obj) {
  if (obj && typeof obj.delete === "function") {
    try {
      obj.delete()
    } catch (_) {
      /* ignore */
    }
  }
}

/**
 * Encode a cv.Mat to JPEG ArrayBuffer.
 */
function encodeJPEG(mat, quality) {
  const effectiveQuality = quality || 92
  // In OpenCV.js 4.x, imencode signature varies.
  // Try the MatVector path first, then the direct-return path.
  var vec, encoded, data, result, buf
  try {
    vec = new cv.MatVector()
    cv.imencode(".jpg", mat, vec, [cv.IMWRITE_JPEG_QUALITY, effectiveQuality])
    encoded = vec.get(0)
    // Clone data before deleting the MatVector
    data = new Uint8Array(encoded.data)
    safeDelete(encoded)
    safeDelete(vec)
    return data.buffer
  } catch (e1) {
    safeDelete(vec)
    // Fallback: direct return
    try {
      result = cv.imencode(".jpg", mat, [
        cv.IMWRITE_JPEG_QUALITY,
        effectiveQuality,
      ])
      if (result?.data) {
        buf = new Uint8Array(result.data).buffer
        safeDelete(result)
        return buf
      }
    } catch (e2) {
      throw new Error(`cv.imencode failed: ${e1} / ${e2}`)
    }
    throw e1
  }
}

/**
 * Encode a cv.Mat to PNG ArrayBuffer.
 */
function _encodePNG(mat) {
  var vec, encoded, data, result, buf
  try {
    vec = new cv.MatVector()
    cv.imencode(".png", mat, vec, [cv.IMWRITE_PNG_COMPRESSION, 3])
    encoded = vec.get(0)
    data = new Uint8Array(encoded.data)
    safeDelete(encoded)
    safeDelete(vec)
    return data.buffer
  } catch (e1) {
    safeDelete(vec)
    try {
      result = cv.imencode(".png", mat, [cv.IMWRITE_PNG_COMPRESSION, 3])
      if (result?.data) {
        buf = new Uint8Array(result.data).buffer
        safeDelete(result)
        return buf
      }
    } catch (e2) {
      throw new Error(`cv.imencode PNG failed: ${e1} / ${e2}`)
    }
    throw e1
  }
}

// ---- Pure math utilities ---------------------------------------------------

/**
 * Order 4 points as: top-left, top-right, bottom-right, bottom-left.
 * Exact mirror of exam_photo_preprocessing.py:order_points().
 */
function orderPoints(points) {
  // points: array of [x, y] pairs (Float32Array or regular array)
  var pts = []
  var i
  for (i = 0; i < 4; i++) {
    pts.push([points[i][0], points[i][1]])
  }

  var summed = pts.map((p) => p[0] + p[1])
  var diff = pts.map((p) => p[1] - p[0])

  var tlIdx = summed.indexOf(Math.min.apply(null, summed))
  var brIdx = summed.indexOf(Math.max.apply(null, summed))
  var trIdx = diff.indexOf(Math.min.apply(null, diff))
  var blIdx = diff.indexOf(Math.max.apply(null, diff))

  return [
    [pts[tlIdx][0], pts[tlIdx][1]], // top-left
    [pts[trIdx][0], pts[trIdx][1]], // top-right
    [pts[brIdx][0], pts[brIdx][1]], // bottom-right
    [pts[blIdx][0], pts[blIdx][1]], // bottom-left
  ]
}

/**
 * Expand page quad with margin.
 * Exact mirror of expand_page_quad().
 */
function expandPageQuad(
  quad,
  imageWidth,
  imageHeight,
  pageIndex,
  pageCount,
  splitAxis,
  marginMode,
) {
  // quad: [[x,y],[x,y],[x,y],[x,y]] already ordered
  var ordered = quad.slice() // copy
  var verticalMargin, outerMargin, innerMargin, k

  if (marginMode === "minimal") {
    verticalMargin = Math.max(2.0, imageHeight * 0.004)
    outerMargin = Math.max(2.0, imageWidth * 0.004)
    innerMargin = Math.max(4.0, imageWidth * 0.004)
  } else if (marginMode === "safe") {
    verticalMargin = Math.max(16.0, imageHeight * 0.06)
    outerMargin = Math.max(16.0, imageWidth * 0.06)
    innerMargin = Math.max(10.0, imageWidth * 0.015)
  } else {
    // conservative (default)
    verticalMargin = Math.max(12.0, imageHeight * 0.045)
    outerMargin = Math.max(12.0, imageWidth * 0.045)
    innerMargin = Math.max(8.0, imageWidth * 0.008)
  }

  // Expand top edges
  ordered[0][1] -= verticalMargin
  ordered[1][1] -= verticalMargin
  // Expand bottom edges
  ordered[2][1] += verticalMargin
  ordered[3][1] += verticalMargin

  if (pageCount === 1) {
    ordered[0][0] -= outerMargin
    ordered[3][0] -= outerMargin
    ordered[1][0] += outerMargin
    ordered[2][0] += outerMargin
  } else if (splitAxis === "vertical" && pageIndex === 0) {
    ordered[0][1] -= outerMargin
    ordered[1][1] -= outerMargin
    ordered[2][1] += innerMargin
    ordered[3][1] += innerMargin
    ordered[0][0] -= outerMargin
    ordered[3][0] -= outerMargin
    ordered[1][0] += outerMargin
    ordered[2][0] += outerMargin
  } else if (splitAxis === "vertical") {
    ordered[0][1] -= innerMargin
    ordered[1][1] -= innerMargin
    ordered[2][1] += outerMargin
    ordered[3][1] += outerMargin
    ordered[0][0] -= outerMargin
    ordered[3][0] -= outerMargin
    ordered[1][0] += outerMargin
    ordered[2][0] += outerMargin
  } else if (pageIndex === 0) {
    ordered[0][0] -= outerMargin
    ordered[3][0] -= outerMargin
    ordered[1][0] += innerMargin
    ordered[2][0] += innerMargin
  } else {
    ordered[0][0] -= innerMargin
    ordered[3][0] -= innerMargin
    ordered[1][0] += outerMargin
    ordered[2][0] += outerMargin
  }

  // Clip to image bounds
  for (k = 0; k < 4; k++) {
    ordered[k][0] = Math.max(0, Math.min(imageWidth - 1, ordered[k][0]))
    ordered[k][1] = Math.max(0, Math.min(imageHeight - 1, ordered[k][1]))
  }

  return ordered
}

// ---- Core OpenCV algorithms (exact mirrors of Python) ----------------------

/**
 * Four-point perspective transform.
 * Exact mirror of exam_photo_preprocessing.py:four_point_transform_with_matrix().
 *
 * Returns { warped: cv.Mat, matrix: cv.Mat } — caller owns both Mats.
 */
function fourPointTransformWithMatrix(src, points) {
  var rect = orderPoints(points)
  var topLeft = rect[0],
    topRight = rect[1],
    bottomRight = rect[2],
    bottomLeft = rect[3]

  var widthA = Math.hypot(
    bottomRight[0] - bottomLeft[0],
    bottomRight[1] - bottomLeft[1],
  )
  var widthB = Math.hypot(topRight[0] - topLeft[0], topRight[1] - topLeft[1])
  var heightA = Math.hypot(
    topRight[0] - bottomRight[0],
    topRight[1] - bottomRight[1],
  )
  var heightB = Math.hypot(
    topLeft[0] - bottomLeft[0],
    topLeft[1] - bottomLeft[1],
  )

  var maxWidth = Math.max(widthA, widthB) | 0
  var maxHeight = Math.max(heightA, heightB) | 0

  if (maxWidth < 50 || maxHeight < 50) {
    throw new Error("Detected document is too small")
  }

  // Build source points Mat (4x1 CV_32FC2)
  var srcPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
    rect[0][0],
    rect[0][1],
    rect[1][0],
    rect[1][1],
    rect[2][0],
    rect[2][1],
    rect[3][0],
    rect[3][1],
  ])

  // Build destination points Mat
  var dstPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
    0,
    0,
    maxWidth - 1,
    0,
    maxWidth - 1,
    maxHeight - 1,
    0,
    maxHeight - 1,
  ])

  var matrix = cv.getPerspectiveTransform(srcPts, dstPts)
  var warped = new cv.Mat()
  // Default interpolation: INTER_LINEAR, border: BORDER_CONSTANT (default=0/black)
  cv.warpPerspective(src, warped, matrix, new cv.Size(maxWidth, maxHeight))

  safeDelete(srcPts)
  safeDelete(dstPts)

  return { warped: warped, matrix: matrix }
}

/**
 * CLAHE enhancement + non-local means denoising.
 * Exact mirror of exam_photo_preprocessing.py:enhance_page().
 */
function enhancePage(src) {
  var lab = new cv.Mat()
  cv.cvtColor(src, lab, cv.COLOR_BGR2Lab)

  var channels = new cv.MatVector()
  cv.split(lab, channels)

  var lChannel = channels.get(0)
  var _aChannel = channels.get(1)
  var _bChannel = channels.get(2)

  var clahe = new cv.CLAHE(2.0, new cv.Size(8, 8))
  var enhancedL = new cv.Mat()
  clahe.apply(lChannel, enhancedL)

  // Replace L channel
  safeDelete(channels.get(0))
  channels.set(0, enhancedL)

  var merged = new cv.Mat()
  cv.merge(channels, merged)
  cv.cvtColor(merged, merged, cv.COLOR_Lab2BGR)

  // fastNlMeansDenoisingColored: h=3, hColor=3, templateWindowSize=7, searchWindowSize=21
  var denoised = new cv.Mat()
  cv.fastNlMeansDenoisingColored(merged, denoised, 3, 3, 7, 21)

  safeDelete(lab)
  safeDelete(enhancedL)
  safeDelete(channels.get(1)) // aChannel
  safeDelete(channels.get(2)) // bChannel
  safeDelete(channels)
  safeDelete(merged)

  return denoised
}

/**
 * Estimate horizontal text skew angle from Hough lines.
 * Exact mirror of estimate_horizontal_text_skew().
 *
 * Returns { angle: number|null, metadata: object }
 */
function estimateHorizontalTextSkew(src) {
  var height = src.rows,
    width = src.cols
  var metadata = {}
  var resized, i, j, k
  var x1, y1, x2, y2, dx, dy, length, angle, weight

  if (width < 80 || height < 80) {
    return {
      angle: null,
      metadata: { status: "skipped", reason: "image_too_small" },
    }
  }

  var gray = new cv.Mat()
  cv.cvtColor(src, gray, cv.COLOR_BGR2GRAY)

  var scale = Math.min(1200 / Math.max(height, width), 1.0)
  var grayWork = gray
  if (scale < 1.0) {
    resized = new cv.Mat()
    cv.resize(
      gray,
      resized,
      new cv.Size((width * scale) | 0, (height * scale) | 0),
      0,
      0,
      cv.INTER_AREA,
    )
    safeDelete(gray)
    grayWork = resized
  }

  var grayHeight = grayWork.rows,
    grayWidth = grayWork.cols

  var top = (grayHeight * 0.04) | 0
  var bottom = (grayHeight * 0.96) | 0
  var left = (grayWidth * 0.04) | 0
  var right = (grayWidth * 0.96) | 0

  var roi = grayWork.roi(new cv.Rect(left, top, right - left, bottom - top))
  if (roi.rows === 0 || roi.cols === 0) {
    safeDelete(grayWork)
    safeDelete(roi)
    return { angle: null, metadata: { status: "skipped", reason: "empty_roi" } }
  }

  var blurred = new cv.Mat()
  cv.GaussianBlur(roi, blurred, new cv.Size(3, 3), 0)
  var edges = new cv.Mat()
  cv.Canny(blurred, edges, 50, 150, 3)

  var minLineLength = Math.max(45, (grayWidth * 0.08) | 0)
  var maxLineGap = Math.max(8, (grayWidth * 0.015) | 0)
  var houghThreshold = Math.max(35, (grayWidth * 0.035) | 0)

  var lines
  try {
    lines = cv.HoughLinesP(
      edges,
      1,
      Math.PI / 180,
      houghThreshold,
      minLineLength,
      maxLineGap,
    )
  } catch (_e) {
    safeDelete(roi)
    safeDelete(blurred)
    safeDelete(edges)
    safeDelete(grayWork)
    return {
      angle: null,
      metadata: { status: "skipped", reason: "no_hough_lines", line_count: 0 },
    }
  }

  if (!lines || lines.rows === 0) {
    safeDelete(roi)
    safeDelete(blurred)
    safeDelete(edges)
    if (lines) safeDelete(lines)
    safeDelete(grayWork)
    return {
      angle: null,
      metadata: { status: "skipped", reason: "no_hough_lines", line_count: 0 },
    }
  }

  var weightedAngles = []
  for (i = 0; i < lines.rows; i++) {
    x1 = lines.data32S[i * 4]
    y1 = lines.data32S[i * 4 + 1]
    x2 = lines.data32S[i * 4 + 2]
    y2 = lines.data32S[i * 4 + 3]
    dx = x2 - x1
    dy = y2 - y1
    length = Math.hypot(dx, dy)
    if (length < minLineLength) continue
    angle = (Math.atan2(dy, dx) * 180) / Math.PI
    if (angle > 90) angle -= 180
    if (angle < -90) angle += 180
    if (Math.abs(angle) <= 8) {
      weight = Math.min(length, grayWidth * 0.45)
      weightedAngles.push({ angle: angle, weight: weight })
    }
  }

  safeDelete(roi)
  safeDelete(blurred)
  safeDelete(edges)
  safeDelete(lines)
  safeDelete(grayWork)

  if (weightedAngles.length < 4) {
    return {
      angle: null,
      metadata: {
        status: "skipped",
        reason: "insufficient_horizontal_lines",
        line_count: weightedAngles.length,
      },
    }
  }

  // Weighted median
  weightedAngles.sort((a, b) => a.angle - b.angle)
  var totalWeight = 0
  for (j = 0; j < weightedAngles.length; j++)
    totalWeight += weightedAngles[j].weight
  var midpointWeight = totalWeight / 2
  var accumulated = 0
  var medianAngle = weightedAngles[(weightedAngles.length / 2) | 0].angle
  for (k = 0; k < weightedAngles.length; k++) {
    accumulated += weightedAngles[k].weight
    if (accumulated >= midpointWeight) {
      medianAngle = weightedAngles[k].angle
      break
    }
  }

  // IQR
  var rawAngles = weightedAngles.map((w) => w.angle)
  rawAngles.sort((a, b) => a - b)
  var q1 = rawAngles[(rawAngles.length * 0.25) | 0]
  var q3 = rawAngles[(rawAngles.length * 0.75) | 0]
  var angleIqr = q3 - q1

  metadata = {
    status: "estimated",
    angle: Math.round(medianAngle * 1000) / 1000,
    line_count: weightedAngles.length,
    angle_iqr: Math.round(angleIqr * 1000) / 1000,
    scale: Math.round(scale * 10000) / 10000,
  }

  return { angle: medianAngle, metadata: metadata }
}

/**
 * Rotate image with white background fill.
 * Exact mirror of rotate_bound_with_background().
 */
function rotateBoundWithBackground(src, angle, bgColor) {
  const bg = bgColor || [255, 255, 255]
  var height = src.rows,
    width = src.cols
  var centerX = width / 2.0,
    centerY = height / 2.0
  var radians = (angle * Math.PI) / 180
  var cos = Math.abs(Math.cos(radians))
  var sin = Math.abs(Math.sin(radians))
  var nextWidth = (height * sin + width * cos) | 0
  var nextHeight = (height * cos + width * sin) | 0

  var rotMat = cv.getRotationMatrix2D(
    new cv.Point(centerX, centerY),
    angle,
    1.0,
  )
  rotMat.data64F[2] += nextWidth / 2.0 - centerX
  rotMat.data64F[5] += nextHeight / 2.0 - centerY

  var result = new cv.Mat()
  cv.warpAffine(
    src,
    result,
    rotMat,
    new cv.Size(nextWidth, nextHeight),
    cv.INTER_CUBIC,
    cv.BORDER_CONSTANT,
    new cv.Scalar(bg[0], bg[1], bg[2]),
  )

  safeDelete(rotMat)
  return result
}

/**
 * Projection-based deskew score (variance of horizontal projection).
 * Exact mirror of projection_deskew_score().
 */
function projectionDeskewScore(src) {
  var gray = new cv.Mat()
  cv.cvtColor(src, gray, cv.COLOR_BGR2GRAY)

  var height = gray.rows,
    width = gray.cols
  var scale = Math.min(1000 / Math.max(height, width), 1.0)
  var grayWork = gray
  var resized
  if (scale < 1.0) {
    resized = new cv.Mat()
    cv.resize(
      gray,
      resized,
      new cv.Size((width * scale) | 0, (height * scale) | 0),
      0,
      0,
      cv.INTER_AREA,
    )
    safeDelete(gray)
    grayWork = resized
  }

  height = grayWork.rows
  width = grayWork.cols
  var binary = new cv.Mat()
  cv.threshold(grayWork, binary, 0, 255, cv.THRESH_BINARY_INV + cv.THRESH_OTSU)

  var top = (height * 0.05) | 0
  var bottom = (height * 0.95) | 0
  var left = (width * 0.04) | 0
  var right = (width * 0.96) | 0

  var roi = binary.roi(new cv.Rect(left, top, right - left, bottom - top))
  if (roi.rows === 0 || roi.cols === 0) {
    safeDelete(grayWork)
    safeDelete(binary)
    safeDelete(roi)
    return 0.0
  }

  // Sum rows to get horizontal projection
  // Use reduce to sum along columns (axis=1 in numpy)
  var projection = new cv.Mat()
  cv.reduce(roi, projection, 1, cv.REDUCE_SUM, cv.CV_32F)

  // Compute variance / mean
  var mean = new cv.Mat(),
    stddev = new cv.Mat()
  cv.meanStdDev(projection, mean, stddev)
  var meanVal = mean.data64F[0]
  var stddevVal = stddev.data64F[0]
  var variance = stddevVal * stddevVal

  safeDelete(grayWork)
  safeDelete(binary)
  safeDelete(roi)
  safeDelete(projection)
  safeDelete(mean)
  safeDelete(stddev)

  return variance / (meanVal + 1e-6)
}

/**
 * Estimate best projection-based deskew angle.
 * Exact mirror of estimate_projection_deskew_angle().
 */
function estimateProjectionDeskewAngle(src, houghAngle, maxAbsAngle) {
  const maxAngle = maxAbsAngle || 3.0
  var a, i, j, rotated, score, sameSignCandidates, sameSignBest
  var zeroScore = projectionDeskewScore(src)
  var candidates = [{ angle: 0.0, score: zeroScore }]

  for (a = -maxAngle; a <= maxAngle + 0.001; a += 0.25) {
    a = Math.round(a * 1000) / 1000
    if (Math.abs(a) < 1e-6) continue
    rotated = rotateBoundWithBackground(src, a)
    score = projectionDeskewScore(rotated)
    candidates.push({ angle: a, score: score })
    safeDelete(rotated)
  }

  var bestAngle = 0.0,
    bestScore = zeroScore
  for (i = 0; i < candidates.length; i++) {
    if (candidates[i].score > bestScore) {
      bestScore = candidates[i].score
      bestAngle = candidates[i].angle
    }
  }

  // Prefer Hough-supported sign when nearly tied
  if (
    houghAngle !== null &&
    houghAngle !== undefined &&
    Math.abs(houghAngle) >= 0.35
  ) {
    sameSignCandidates = candidates.filter(
      (c) =>
        Math.abs(c.angle) >= 0.35 &&
        Math.sign(c.angle) === Math.sign(houghAngle),
    )
    if (sameSignCandidates.length > 0) {
      sameSignBest = sameSignCandidates[0]
      for (j = 1; j < sameSignCandidates.length; j++) {
        if (sameSignCandidates[j].score > sameSignBest.score) {
          sameSignBest = sameSignCandidates[j]
        }
      }
      if (sameSignBest.score >= bestScore * 0.97) {
        bestAngle = sameSignBest.angle
        bestScore = sameSignBest.score
      }
    }
  }

  var improvement = zeroScore > 1e-6 ? bestScore / zeroScore : 1.0
  var metadata = {
    zero_score: Math.round(zeroScore * 1000) / 1000,
    best_score: Math.round(bestScore * 1000) / 1000,
    best_angle: Math.round(bestAngle * 1000) / 1000,
    improvement: Math.round(improvement * 1000) / 1000,
    candidate_count: candidates.length,
  }

  if (Math.abs(bestAngle) < 0.35 || improvement < 1.08) {
    metadata.status = "skipped"
    metadata.reason = "weak_projection_improvement"
    return { angle: null, metadata: metadata }
  }

  metadata.status = "estimated"
  return { angle: bestAngle, metadata: metadata }
}

/**
 * Estimate vertical line skew.
 * Exact mirror of estimate_vertical_line_skew().
 */
function estimateVerticalLineSkew(src) {
  var resized, i, j, k
  var x1, y1, x2, y2, dx, dy, length, angle, dev
  var height = src.rows,
    width = src.cols
  if (width < 80 || height < 80) {
    return {
      dev: null,
      metadata: { status: "skipped", reason: "image_too_small" },
    }
  }

  var gray = new cv.Mat()
  cv.cvtColor(src, gray, cv.COLOR_BGR2GRAY)

  var scale = Math.min(1200 / Math.max(height, width), 1.0)
  var grayWork = gray
  if (scale < 1.0) {
    resized = new cv.Mat()
    cv.resize(
      gray,
      resized,
      new cv.Size((width * scale) | 0, (height * scale) | 0),
      0,
      0,
      cv.INTER_AREA,
    )
    safeDelete(gray)
    grayWork = resized
  }

  var grayHeight = grayWork.rows,
    grayWidth = grayWork.cols
  var top = (grayHeight * 0.04) | 0
  var bottom = (grayHeight * 0.96) | 0
  var left = (grayWidth * 0.04) | 0
  var right = (grayWidth * 0.96) | 0
  var roi = grayWork.roi(new cv.Rect(left, top, right - left, bottom - top))
  if (roi.rows === 0 || roi.cols === 0) {
    safeDelete(grayWork)
    safeDelete(roi)
    return { dev: null, metadata: { status: "skipped", reason: "empty_roi" } }
  }

  var blurred = new cv.Mat()
  cv.GaussianBlur(roi, blurred, new cv.Size(3, 3), 0)
  var edges = new cv.Mat()
  cv.Canny(blurred, edges, 50, 150, 3)

  var minLineLength = Math.max(45, (grayHeight * 0.08) | 0)
  var maxLineGap = Math.max(8, (grayHeight * 0.015) | 0)
  var houghThreshold = Math.max(35, (grayHeight * 0.035) | 0)

  var lines
  try {
    lines = cv.HoughLinesP(
      edges,
      1,
      Math.PI / 180,
      houghThreshold,
      minLineLength,
      maxLineGap,
    )
  } catch (_e) {
    safeDelete(roi)
    safeDelete(blurred)
    safeDelete(edges)
    safeDelete(grayWork)
    return {
      dev: null,
      metadata: { status: "skipped", reason: "no_hough_lines", line_count: 0 },
    }
  }

  if (!lines || lines.rows === 0) {
    safeDelete(roi)
    safeDelete(blurred)
    safeDelete(edges)
    if (lines) safeDelete(lines)
    safeDelete(grayWork)
    return {
      dev: null,
      metadata: { status: "skipped", reason: "no_hough_lines", line_count: 0 },
    }
  }

  var weightedDevs = []
  for (i = 0; i < lines.rows; i++) {
    x1 = lines.data32S[i * 4]
    y1 = lines.data32S[i * 4 + 1]
    x2 = lines.data32S[i * 4 + 2]
    y2 = lines.data32S[i * 4 + 3]
    dx = x2 - x1
    dy = y2 - y1
    length = Math.hypot(dx, dy)
    if (length < minLineLength) continue
    angle = (Math.atan2(dy, dx) * 180) / Math.PI
    if (angle > 90) angle -= 180
    if (angle < -90) angle += 180
    if (Math.abs(Math.abs(angle) - 90) <= 8) {
      dev = angle > 0 ? angle - 90 : angle + 90
      weightedDevs.push({
        dev: dev,
        weight: Math.min(length, grayHeight * 0.45),
      })
    }
  }

  safeDelete(roi)
  safeDelete(blurred)
  safeDelete(edges)
  safeDelete(lines)
  safeDelete(grayWork)

  if (weightedDevs.length < 4) {
    return {
      dev: null,
      metadata: {
        status: "skipped",
        reason: "insufficient_vertical_lines",
        line_count: weightedDevs.length,
      },
    }
  }

  weightedDevs.sort((a, b) => a.dev - b.dev)
  var totalWeight = 0
  for (j = 0; j < weightedDevs.length; j++)
    totalWeight += weightedDevs[j].weight
  var midpointWeight = totalWeight / 2
  var accumulated = 0
  var medianDev = weightedDevs[(weightedDevs.length / 2) | 0].dev
  for (k = 0; k < weightedDevs.length; k++) {
    accumulated += weightedDevs[k].weight
    if (accumulated >= midpointWeight) {
      medianDev = weightedDevs[k].dev
      break
    }
  }

  var rawDevs = weightedDevs.map((w) => w.dev)
  rawDevs.sort((a, b) => a - b)
  var q1d = rawDevs[(rawDevs.length * 0.25) | 0]
  var q3d = rawDevs[(rawDevs.length * 0.75) | 0]
  var devIqr = q3d - q1d

  return {
    dev: medianDev,
    metadata: {
      status: "estimated",
      dev: Math.round(medianDev * 1000) / 1000,
      line_count: weightedDevs.length,
      dev_iqr: Math.round(devIqr * 1000) / 1000,
      scale: Math.round(scale * 10000) / 10000,
    },
  }
}

/**
 * Apply vertical shear correction.
 * Exact mirror of apply_vertical_shear().
 */
function applyVerticalShear(src, maxAbsDev) {
  const maxDev = maxAbsDev || 3.0
  var started = Date.now()
  var estimate = estimateVerticalLineSkew(src)
  var dev = estimate.dev
  var metadata = Object.assign({}, estimate.metadata, {
    applied_factor: 0.0,
    elapsed_ms: 0,
  })

  if (dev === null || dev === undefined) {
    metadata.elapsed_ms = Date.now() - started
    return { sheared: src.clone(), metadata: metadata }
  }
  if (Math.abs(dev) < 0.35) {
    metadata.status = "already_plumb"
    metadata.elapsed_ms = Date.now() - started
    return { sheared: src.clone(), metadata: metadata }
  }
  if (Math.abs(dev) > maxDev) {
    metadata.status = "rejected"
    metadata.reason = "dev_out_of_range"
    metadata.elapsed_ms = Date.now() - started
    return { sheared: src.clone(), metadata: metadata }
  }

  var factor = Math.tan((dev * Math.PI) / 180)
  var height = src.rows,
    width = src.cols
  var newWidth = ((width + Math.abs(factor) * height) | 0) + 10

  var matData = [1.0, factor, 0.0, 0.0, 1.0, 0.0]
  if (factor < 0) {
    matData[2] = Math.abs(factor) * height
  }
  var matrix = cv.matFromArray(2, 3, cv.CV_64F, matData)

  var sheared = new cv.Mat()
  cv.warpAffine(
    src,
    sheared,
    matrix,
    new cv.Size(newWidth, height),
    cv.INTER_CUBIC,
    cv.BORDER_CONSTANT,
    new cv.Scalar(255, 255, 255),
  )

  safeDelete(matrix)
  metadata.status = "applied"
  metadata.applied_factor = Math.round(factor * 100000) / 100000
  metadata.elapsed_ms = Date.now() - started
  return { sheared: sheared, metadata: metadata }
}

/**
 * Full fine deskew pipeline.
 * Exact mirror of fine_deskew_page().
 */
function fineDeskewPage(src) {
  var started = Date.now()
  var candidates, candidateAngles, c, candAngle, candMat, residual, residualAbs
  var best, d, e
  var houghResult = estimateHorizontalTextSkew(src)
  var projectionResult = estimateProjectionDeskewAngle(src, houghResult.angle)

  var metadata = {}
  for (var key in houghResult.metadata) {
    metadata[key] = houghResult.metadata[key]
  }
  metadata.projection = projectionResult.metadata
  metadata.applied_angle = 0.0
  metadata.elapsed_ms = 0

  var chosenAngle =
    projectionResult.angle !== null ? projectionResult.angle : houghResult.angle
  metadata.chosen_angle_source =
    projectionResult.angle !== null ? "projection" : "hough"

  var rotated = src
  if (chosenAngle === null || chosenAngle === undefined) {
    metadata.rotation_status = "skipped"
  } else if (Math.abs(chosenAngle) < 0.35) {
    metadata.rotation_status = "already_level"
  } else if (Math.abs(chosenAngle) > 6) {
    metadata.status = "rejected"
    metadata.reason = "angle_out_of_range"
    metadata.elapsed_ms = Date.now() - started
    return { deskewed: src, metadata: metadata }
  } else {
    candidates = [{ angle: 0.0, mat: src, residual: Math.abs(chosenAngle) }]
    candidateAngles = [chosenAngle]
    if (Math.abs(chosenAngle) >= 0.8) {
      candidateAngles.push(chosenAngle * 0.5)
    }
    for (c = 0; c < candidateAngles.length; c++) {
      candAngle = candidateAngles[c]
      candMat = rotateBoundWithBackground(src, candAngle)
      residual = estimateHorizontalTextSkew(candMat)
      residualAbs =
        residual.angle !== null ? Math.abs(residual.angle) : Math.abs(candAngle)
      candidates.push({ angle: candAngle, mat: candMat, residual: residualAbs })
    }

    // Find best (lowest residual)
    best = candidates[0]
    for (d = 1; d < candidates.length; d++) {
      if (candidates[d].residual < best.residual) {
        best = candidates[d]
      }
    }

    if (best.angle === 0.0 || best.residual > Math.abs(chosenAngle) - 0.2) {
      rotated = src
      metadata.rotation_status = "kept_original"
      metadata.residual_abs = Math.round(best.residual * 1000) / 1000
    } else {
      rotated = best.mat
      metadata.rotation_status = "applied"
      metadata.applied_angle = Math.round(best.angle * 1000) / 1000
      metadata.residual_abs = Math.round(best.residual * 1000) / 1000
    }

    // Clean up unused candidates
    for (e = 0; e < candidates.length; e++) {
      if (candidates[e].mat !== rotated && candidates[e].mat !== src) {
        safeDelete(candidates[e].mat)
      }
    }
  }

  var shearResult = applyVerticalShear(rotated)
  if (rotated !== src && rotated !== shearResult.sheared) {
    safeDelete(rotated)
  }

  metadata.shear = shearResult.metadata
  metadata.elapsed_ms = Date.now() - started
  metadata.status = "applied"
  return { deskewed: shearResult.sheared, metadata: metadata }
}

/**
 * Estimate image sharpness (Laplacian variance).
 * Exact mirror of estimate_sharpness().
 */
function estimateSharpness(src) {
  var gray = new cv.Mat()
  cv.cvtColor(src, gray, cv.COLOR_BGR2GRAY)
  var laplacian = new cv.Mat()
  cv.Laplacian(gray, laplacian, cv.CV_64F)

  var mean = new cv.Mat(),
    stddev = new cv.Mat()
  cv.meanStdDev(laplacian, mean, stddev)
  var variance = stddev.data64F[0] * stddev.data64F[0]

  safeDelete(gray)
  safeDelete(laplacian)
  safeDelete(mean)
  safeDelete(stddev)

  return variance
}

// ---- Main preprocessing pipeline -------------------------------------------

/**
 * Preprocess a single page with a given quad.
 * Mirrors build_manual_quad_pages() — single page path — skipping
 * normalize_reading_orientation() which needs Gemini.
 */
function preprocessPage(
  srcImage,
  quad,
  pageIndex,
  pageCount,
  splitAxis,
  marginMode,
  applyDeskew,
) {
  var imageHeight = srcImage.rows,
    imageWidth = srcImage.cols

  // 1. Expand quad with margin (matches expand_page_quad)
  var expandedQuad = expandPageQuad(
    quad,
    imageWidth,
    imageHeight,
    pageIndex,
    pageCount,
    splitAxis,
    marginMode,
  )

  // 2. Perspective transform (matches four_point_transform_with_matrix)
  var transformResult = fourPointTransformWithMatrix(srcImage, expandedQuad)
  var warped = transformResult.warped

  // 3. Enhance (matches enhance_page)
  var enhanced = enhancePage(warped)
  safeDelete(warped)
  safeDelete(transformResult.matrix)

  // 4. Fine deskew (matches fine_deskew_page)
  var deskewed, deskewMetadata, deskewResult
  if (applyDeskew !== false) {
    deskewResult = fineDeskewPage(enhanced)
    deskewed = deskewResult.deskewed
    deskewMetadata = deskewResult.metadata
    safeDelete(enhanced)
  } else {
    deskewed = enhanced
    deskewMetadata = { status: "skipped", reason: "deskew_disabled" }
  }

  // 5. Estimate sharpness
  var sharpness = estimateSharpness(deskewed)

  return {
    mat: deskewed,
    width: deskewed.cols,
    height: deskewed.rows,
    sharpness: Math.round(sharpness * 100) / 100,
    deskew: deskewMetadata,
    sourceQuad: expandedQuad.map((p) => [
      Math.round(p[0] * 100) / 100,
      Math.round(p[1] * 100) / 100,
    ]),
  }
}

/**
 * Full preprocessing pipeline: decode → preprocess pages → encode.
 */
function preprocess(imageBuffer, quads, options) {
  const opts = options || {}
  var marginMode = opts.marginMode || "conservative"
  var applyDeskew = opts.applyDeskew !== false
  var jpegQuality = opts.jpegQuality || 92
  var pageCount = quads.length
  var splitAxis = opts.splitAxis || "horizontal"
  var i, result, jpegBuf

  // Decode image
  var buf = new Uint8Array(imageBuffer)
  var srcImage = cv.imdecode(buf, cv.IMREAD_COLOR)
  if (!srcImage || srcImage.rows === 0) {
    throw new Error("Could not decode image")
  }

  var pages = []
  try {
    for (i = 0; i < quads.length; i++) {
      result = preprocessPage(
        srcImage,
        quads[i],
        i,
        pageCount,
        splitAxis,
        marginMode,
        applyDeskew,
      )

      // Encode to JPEG
      try {
        jpegBuf = encodeJPEG(result.mat, jpegQuality)

        pages.push({
          name: `page_${i + 1}.jpg`,
          buffer: jpegBuf,
          width: result.width,
          height: result.height,
          sharpness: result.sharpness,
          deskew: result.deskew,
          sourceQuad: result.sourceQuad,
        })
      } finally {
        safeDelete(result.mat)
      }
    }
  } finally {
    safeDelete(srcImage)
  }

  return {
    pages: pages,
    metadata: {
      engine: "opencvjs_homography_v1",
      page_count: pages.length,
      margin_mode: marginMode,
      split_axis: splitAxis,
      applied_deskew: applyDeskew,
    },
  }
}

// ---- Message handler -------------------------------------------------------

self.onmessage = (event) => {
  var msg = event.data
  if (!msg?.id) return

  var id = msg.id

  if (msg.type === "preprocess") {
    waitForCV()
      .then(() => {
        var result, transferList
        try {
          result = preprocess(msg.imageBuffer, msg.quads, msg.options)
          // Transfer the page ArrayBuffers
          transferList = result.pages.map((p) => p.buffer)
          self.postMessage(
            {
              id: id,
              type: "result",
              pages: result.pages,
              metadata: result.metadata,
            },
            transferList,
          )
        } catch (err) {
          self.postMessage({
            id: id,
            type: "error",
            message: err.message || "Unknown preprocessing error",
          })
        }
      })
      .catch((err) => {
        self.postMessage({
          id: id,
          type: "error",
          message: `OpenCV.js not available: ${err.message || err}`,
        })
      })
  } else if (msg.type === "ping") {
    waitForCV()
      .then(() => {
        self.postMessage({ id: id, type: "pong", cvReady: true })
      })
      .catch(() => {
        self.postMessage({ id: id, type: "pong", cvReady: false })
      })
  } else {
    self.postMessage({
      id: id,
      type: "error",
      message: `Unknown message type: ${msg.type}`,
    })
  }
}
