import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

const turn = (over: Record<string, unknown> = {}) => ({
  answer: '',
  durationMs: 1,
  isAborted: false,
  turnId: 't1',
  reason: 'answer' as const,
  ...over,
})

const usage = (input: number, output: number, read: number, write: number) => ({
  model: 'm',
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: write,
})

const MAIN = usage(1000, 880, 200, 20) // output 880, all 2100
const A1 = usage(500, 60, 900, 40) // output 60, all 1500
const A2 = usage(300, 60, 600, 40) // output 60, all 1000

const EXPLORE = [
  { id: 'a1', description: 'scan', type: 'Explore', status: 'running' },
  { id: 'a2', description: 'scan', type: 'Explore', status: 'running' },
]

const LINE = 'subagents 2x · 12% of output · 54% of all tokens · top Explore'

// The engine's own answers beneath the plugin, and a recorder for the status line.
const beneath = (on: On, agents: unknown = EXPLORE, options: { statusThrows?: boolean } = {}) => {
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    if (options.statusThrows) {
      throw new Error('status failed')
    }
  })
  on('turn.complete', () => ({ text: 'answered' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('agent.list', () => ({ value: typeof agents === 'function' ? agents() : agents }) as never)
  return {
    lines,
    shown: () => lines.filter((line): line is string => line !== undefined),
    last: () => lines[lines.length - 1],
  }
}

const END = { reason: 'clear', sessionId: 's1', resume: { id: 's1' } } as const
const START = { cwd: '/', surface: null, isInteractive: true } as const

describe('subagent-meter hooks', () => {
  test('a session with only main-thread turns shows no line', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    expect(seen.shown()).toEqual([])
  })

  test('main and subagent turns produce the line', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    expect(seen.last()).toBe(LINE)
  })

  test('the turn passes through unchanged', async ($, on) => {
    beneath(on)
    const result = await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(result).toEqual({ text: 'answered' })
  })

  test('a turn without usage adds nothing and shows nothing', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', reason: 'aborted', isAborted: true }))
    expect(seen.shown()).toEqual([])
  })

  test('an agent with zero tokens still counts as a spawn', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: usage(0, 0, 0, 0) }))
    expect(seen.last()).toBe('subagents 1x · 0% of output · 0% of all tokens · top Explore')
  })

  test('a failing agent lookup still counts the turn, as unknown, and does not break it', async ($, on) => {
    const seen = beneath(on, () => {
      throw new Error('no list')
    })
    const result = await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(result).toEqual({ text: 'answered' })
    expect(seen.last()).toMatch(/top unknown$/)
  })

  test('a failing state write does not break the event', async ($, on) => {
    beneath(on)
    on('state.set', () => {
      throw new Error('write failed')
    })
    const result = await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(result).toEqual({ text: 'answered' })
  })

  test('a failing status call does not break the event', async ($, on) => {
    const seen = beneath(on, EXPLORE, { statusThrows: true })
    const result = await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(result).toEqual({ text: 'answered' })
    expect(seen.last()).toMatch(/^subagents 1x /)
  })

  test('an agent that is not listed is unknown', async ($, on) => {
    const seen = beneath(on, [])
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(seen.last()).toMatch(/top unknown$/)
  })

  test('two turns finishing at the same moment are both counted', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    await Promise.all([
      $.turn.complete(turn({ agentId: 'a1', usage: A1 })),
      $.turn.complete(turn({ agentId: 'a2', usage: A2 })),
    ])
    expect(seen.last()).toBe(LINE)
  })

  test('session.end with clear removes the line and resets the counts', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.session.end(END)
    expect(seen.last()).toBeUndefined()
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    expect(seen.last()).toMatch(/^subagents 1x /)
  })

  test('after a clear a main-only turn draws no line', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.session.end(END)
    const before = seen.lines.length
    await $.turn.complete(turn({ usage: MAIN }))
    expect(seen.lines.slice(before).filter(line => line !== undefined)).toEqual([])
  })

  test('session.end with resume also resets: the process goes on under another session', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.session.end({ ...END, reason: 'resume' })
    expect(seen.last()).toBeUndefined()
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    expect(seen.last()).toMatch(/^subagents 1x /)
  })

  test('another session.end reason leaves the counts alone', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    const before = seen.lines.length
    await $.session.end({ ...END, reason: 'other' })
    expect(seen.lines.length).toBe(before)
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    expect(seen.last()).toMatch(/^subagents 2x /)
  })

  test('session.start redraws the line from saved state', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    const before = seen.lines.length
    await $.session.start(START)
    expect(seen.lines.length).toBe(before + 1)
    expect(seen.last()).toBe(LINE)
  })

  test('session.start with nothing counted draws no line', async ($, on) => {
    const seen = beneath(on)
    await $.session.start(START)
    expect(seen.shown()).toEqual([])
  })
})
