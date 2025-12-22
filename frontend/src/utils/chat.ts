export type ChatRole = 'user' | 'assistant' | 'system'

export function parseTimestamp(createdAt: string | null | undefined): number {
  if (!createdAt) return Date.now()
  const t = Date.parse(createdAt)
  return Number.isFinite(t) ? t : Date.now()
}

export function normalizeRole(role: string): ChatRole {
  if (role === 'user' || role === 'assistant' || role === 'system') return role
  return 'assistant'
}

export async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const data = await res.json()
    const detail = (data && typeof data === 'object' && 'detail' in data) ? (data as any).detail : null
    return typeof detail === 'string' && detail.trim() ? detail : null
  } catch {
    return null
  }
}

// 解析思考内容：提取 <think> 标签中的内容
// streaming=true 时支持未闭合的标签（流式传输中）
export function parseThinkingContent(
  text: string,
  trimContent = true,
  streaming = false
): { thinking: string; content: string } {
  if (!text) return { thinking: '', content: '' }

  const thinkingParts: string[] = []
  let mainContent = text

  // 支持多种思考标签格式（完整闭合的标签）
  const thinkingPatterns = [
    /<think(?:>|\s[^>]*>)([\s\S]*?)<\/think>/gi,
    /<thinking(?:>|\s[^>]*>)([\s\S]*?)<\/thinking>/gi,
    /<thought(?:>|\s[^>]*>)([\s\S]*?)<\/thought>/gi,
    /<reason(?:>|\s[^>]*>)([\s\S]*?)<\/reason>/gi,
    /<reasoning(?:>|\s[^>]*>)([\s\S]*?)<\/reasoning>/gi,
  ]

  for (const pattern of thinkingPatterns) {
    let match: RegExpExecArray | null
    while ((match = pattern.exec(mainContent)) !== null) {
      const thinkContent = match[1].trim()
      if (thinkContent) {
        thinkingParts.push(thinkContent)
      }
      mainContent = mainContent.replace(match[0], '')
      pattern.lastIndex = 0
    }
  }

  // 流式模式：处理未闭合的 <think> 标签
  if (streaming) {
    const unclosedPatterns = [
      { open: /<think(?:>|\s[^>]*>)/i, close: /<\/think>/i },
      { open: /<thinking(?:>|\s[^>]*>)/i, close: /<\/thinking>/i },
      { open: /<thought(?:>|\s[^>]*>)/i, close: /<\/thought>/i },
      { open: /<reason(?:>|\s[^>]*>)/i, close: /<\/reason>/i },
      { open: /<reasoning(?:>|\s[^>]*>)/i, close: /<\/reasoning>/i },
    ]

    for (const { open, close } of unclosedPatterns) {
      const openMatch = mainContent.match(open)
      if (openMatch && !close.test(mainContent)) {
        // 找到开始标签但没有结束标签 - 提取未闭合的思考内容
        const startIdx = mainContent.indexOf(openMatch[0]) + openMatch[0].length
        const unclosedThinking = mainContent.slice(startIdx)
        if (unclosedThinking.trim()) {
          thinkingParts.push(unclosedThinking)
        }
        // 从主内容中移除未闭合的思考部分
        mainContent = mainContent.slice(0, mainContent.indexOf(openMatch[0]))
        break
      }
    }
  }

  return {
    thinking: thinkingParts.join('\n\n'),
    content: trimContent ? mainContent.trim() : mainContent
  }
}

