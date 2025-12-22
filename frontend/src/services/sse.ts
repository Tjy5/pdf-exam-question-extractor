/**
 * Minimal SSE ("text/event-stream") reader that yields parsed JSON payloads from "data:" lines.
 *
 * - Supports standard event framing via a blank line ("\n\n").
 * - Supports multi-line "data:" payloads (joined with "\n").
 * - Ignores non-JSON payloads and incomplete trailing data.
 */
export async function* readSseJson<T = unknown>(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<T> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const extractData = (rawEvent: string): string => {
    const dataLines = rawEvent.split('\n').filter(l => l.startsWith('data:'))
    if (dataLines.length === 0) return ''
    return dataLines
      .map(l => l.slice(5).trimStart())
      .join('\n')
      .trim()
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r/g, '')

      while (true) {
        const boundaryIndex = buffer.indexOf('\n\n')
        if (boundaryIndex === -1) break

        const rawEvent = buffer.slice(0, boundaryIndex)
        buffer = buffer.slice(boundaryIndex + 2)

        const dataStr = extractData(rawEvent)
        if (!dataStr) continue

        try {
          yield JSON.parse(dataStr) as T
        } catch {
          // Ignore parse errors for non-JSON or partial payloads
        }
      }
    }

    // Flush: stream ended without trailing blank line.
    const trailing = extractData(buffer)
    if (trailing) {
      try {
        yield JSON.parse(trailing) as T
      } catch {
        // Ignore
      }
    }
  } finally {
    try {
      await reader.cancel()
    } catch {
      // Ignore
    }
    try {
      reader.releaseLock()
    } catch {
      // Ignore
    }
  }
}

