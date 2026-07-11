import { createInterface } from 'node:readline'
import { JSDOM } from 'jsdom'
import { convert } from 'poe2-build-converter/src/convert/index.ts'

const dom = new JSDOM('<root/>', { contentType: 'text/xml' })
globalThis.DOMParser = dom.window.DOMParser

type Request = {
  requestId: string
  sourceHash: string
  pobXml: string
  metadata?: {
    name?: string
    author?: string
    link?: string
    description?: string
  }
  singleStage?: boolean
}

function stripLevelIntervals(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripLevelIntervals)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => key !== 'level_interval')
      .map(([key, item]) => [key, stripLevelIntervals(item)]),
  )
}

function write(payload: unknown): void {
  process.stdout.write(`${JSON.stringify(payload)}\n`)
}

async function main(): Promise<void> {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
  for await (const line of lines) {
    if (!line.trim()) continue
    let request: Request
    try {
      request = JSON.parse(line) as Request
      if (!request.requestId || !request.sourceHash || !request.pobXml) throw new Error('invalid_request')
    } catch {
      write({ status: 'error', errorCode: 'invalid_request' })
      continue
    }
    try {
      const result = convert(request.pobXml, request.metadata ?? {})
      const build = request.singleStage === false ? result.build : stripLevelIntervals(result.build)
      write({
        status: 'ok',
        requestId: request.requestId,
        sourceHash: request.sourceHash,
        build,
        warnings: result.warnings,
        stats: result.stats,
      })
    } catch (error) {
      write({
        status: 'error',
        requestId: request.requestId,
        sourceHash: request.sourceHash,
        errorCode: 'provider_conversion_failed',
        errorType: error instanceof Error ? error.name : 'UnknownError',
      })
    }
  }
}

main().catch(() => {
  process.exitCode = 1
})
