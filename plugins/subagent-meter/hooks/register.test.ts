import { describe, expect, test } from 'claude-code/testing'

const turn = (over: Record<string, unknown> = {}) => ({
  answer: '',
  durationMs: 1,
  isAborted: false,
  turnId: 't1',
  reason: 'answer' as const,
  ...over,
})

describe('harness spike', () => {
  test('a subagent turn.complete reaches the plugin and its status line is observable', async ($, on) => {
    const lines: (string | undefined)[] = []
    on('ui.status', (_, e) => {
      lines.push(e.text)
    })
    on('turn.complete', () => ({ text: 'answered' }))
    on('agent.list', () => [{ id: 'a1', description: 'scan', type: 'Explore', status: 'running' }])

    const result = await $.turn.complete(
      turn({
        agentId: 'a1',
        usage: {
          model: 'm',
          input_tokens: 1,
          output_tokens: 2,
          cache_read_input_tokens: 3,
          cache_creation_input_tokens: 4,
        },
      }),
    )

    expect(result).toEqual({ text: 'answered' })
    expect(lines).toEqual(['agent a1'])
  })
})
