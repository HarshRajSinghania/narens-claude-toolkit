import { describe, expect, test } from 'claude-code/testing'

import type { MeterStats } from '../types'
import { addTurn, emptyStats, formatLine, statusLine, summarize, tokensOf } from './meter'

const usage = (input: number, output: number, read: number, write: number) => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: write,
})

const SESSION: MeterStats = {
  main: { output: 880, all: 2100 },
  agents: {
    a1: { type: 'Explore', output: 60, all: 1500 },
    a2: { type: 'Explore', output: 60, all: 1000 },
  },
}

describe('tokensOf', () => {
  test('output is output_tokens; all is the four counts added', () => {
    expect(tokensOf(usage(1, 2, 3, 4))).toEqual({ output: 2, all: 10 })
  })

  test('a missing count is 0', () => {
    expect(tokensOf({ output_tokens: 5 })).toEqual({ output: 5, all: 5 })
  })

  test('negative and non-finite counts are 0', () => {
    expect(
      tokensOf({
        input_tokens: -3,
        output_tokens: Number.NaN,
        cache_read_input_tokens: Number.POSITIVE_INFINITY,
        cache_creation_input_tokens: 7,
      }),
    ).toEqual({ output: 0, all: 7 })
  })
})

describe('addTurn', () => {
  test('a main-thread turn adds to main', () => {
    const next = addTurn(emptyStats(), { usage: usage(1, 2, 3, 4) })
    expect(next.main).toEqual({ output: 2, all: 10 })
    expect(next.agents).toEqual({})
  })

  test('an agent turn adds to that agent and records its type', () => {
    const next = addTurn(emptyStats(), { agentId: 'a1', type: 'Explore', usage: usage(1, 2, 3, 4) })
    expect(next.agents).toEqual({ a1: { type: 'Explore', output: 2, all: 10 } })
    expect(next.main).toEqual({ output: 0, all: 0 })
  })

  test('repeated turns of one agent add up and keep the first type', () => {
    const first = addTurn(emptyStats(), { agentId: 'a1', type: 'Explore', usage: usage(1, 2, 3, 4) })
    const second = addTurn(first, { agentId: 'a1', type: 'Plan', usage: usage(10, 20, 30, 40) })
    expect(second.agents.a1).toEqual({ type: 'Explore', output: 22, all: 110 })
  })

  test('an agent with no type is unknown', () => {
    const next = addTurn(emptyStats(), { agentId: 'a1', usage: usage(0, 1, 0, 0) })
    expect(next.agents.a1.type).toBe('unknown')
  })

  test('a turn without usage returns the same stats', () => {
    const stats = emptyStats()
    expect(addTurn(stats, { agentId: 'a1', type: 'Explore' })).toBe(stats)
  })

  test('an agent turn with zero tokens still counts as an agent', () => {
    const next = addTurn(emptyStats(), { agentId: 'a1', type: 'Explore', usage: usage(0, 0, 0, 0) })
    expect(Object.keys(next.agents)).toEqual(['a1'])
  })

  test('it does not change its input', () => {
    const stats = emptyStats()
    addTurn(stats, { agentId: 'a1', type: 'Explore', usage: usage(1, 2, 3, 4) })
    addTurn(stats, { usage: usage(1, 2, 3, 4) })
    expect(stats).toEqual(emptyStats())
  })
})

describe('summarize', () => {
  test('no agent seen is undefined', () => {
    expect(summarize(emptyStats())).toBeUndefined()
    expect(summarize(addTurn(emptyStats(), { usage: usage(1, 2, 3, 4) }))).toBeUndefined()
  })

  test('shares are agent-side tokens over main plus agent-side', () => {
    expect(summarize(SESSION)).toEqual({
      spawns: 2,
      outputShare: 120 / 1000,
      allShare: 2500 / 4600,
      topType: 'Explore',
    })
  })

  test('the top type is the one with the most all tokens, summed over its agents', () => {
    const stats: MeterStats = {
      main: { output: 0, all: 0 },
      agents: {
        a1: { type: 'a', output: 1, all: 60 },
        a2: { type: 'a', output: 1, all: 60 },
        b1: { type: 'b', output: 1, all: 100 },
      },
    }
    expect(summarize(stats)?.topType).toBe('a')
  })

  test('a tie goes to the name that sorts first', () => {
    const stats: MeterStats = {
      main: { output: 0, all: 0 },
      agents: {
        y: { type: 'b', output: 1, all: 100 },
        x: { type: 'a', output: 1, all: 100 },
      },
    }
    expect(summarize(stats)?.topType).toBe('a')
  })

  test('a zero total gives shares of 0, not NaN', () => {
    const stats: MeterStats = {
      main: { output: 0, all: 0 },
      agents: { a1: { type: 'x', output: 0, all: 0 } },
    }
    expect(summarize(stats)).toEqual({ spawns: 1, outputShare: 0, allShare: 0, topType: 'x' })
  })
})

describe('formatLine', () => {
  test('the line, with whole percents', () => {
    expect(formatLine({ spawns: 14, outputShare: 0.12, allShare: 0.54, topType: 'Explore' })).toBe(
      'subagents 14x · 12% of output · 54% of all tokens · top Explore',
    )
  })

  test('a share above 0 and below 1 percent is <1%; an exact 0 is 0%', () => {
    expect(formatLine({ spawns: 1, outputShare: 0.004, allShare: 0, topType: 'Explore' })).toBe(
      'subagents 1x · <1% of output · 0% of all tokens · top Explore',
    )
  })

  test('all of it is 100%', () => {
    expect(formatLine({ spawns: 3, outputShare: 1, allShare: 1, topType: 'Plan' })).toBe(
      'subagents 3x · 100% of output · 100% of all tokens · top Plan',
    )
  })

  test('a long type name is cut at 16 characters', () => {
    expect(formatLine({ spawns: 1, outputShare: 0.5, allShare: 0.5, topType: 'general-purpose-extra-long' })).toBe(
      'subagents 1x · 50% of output · 50% of all tokens · top general-purpose-',
    )
  })
})

describe('statusLine', () => {
  test('the session in the spec reads as the spec says', () => {
    expect(statusLine(SESSION)).toBe('subagents 2x · 12% of output · 54% of all tokens · top Explore')
  })

  test('no agents is undefined, so the line is removed', () => {
    expect(statusLine(emptyStats())).toBeUndefined()
  })
})
