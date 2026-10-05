import type { MeterStats } from '../types'

export type Usage = {
  input_tokens?: number
  output_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
}

export type Turn = { agentId?: string; type?: string; usage?: Usage }

export type Summary = {
  spawns: number
  outputShare: number
  allShare: number
  topType: string
}

const MAX_TYPE_LENGTH = 16

const count = (n: unknown): number =>
  typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : 0

const share = (part: number, whole: number): number => (whole > 0 ? part / whole : 0)

const compare = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

const percent = (ratio: number): string => {
  const value = ratio * 100
  return value > 0 && value < 1 ? '<1%' : `${Math.round(value)}%`
}

export const emptyStats = (): MeterStats => ({ main: { output: 0, all: 0 }, agents: {} })

export const tokensOf = (usage: Usage): { output: number; all: number } => {
  const output = count(usage.output_tokens)
  const all =
    count(usage.input_tokens) +
    count(usage.cache_read_input_tokens) +
    count(usage.cache_creation_input_tokens) +
    output
  return { output, all }
}

export const addTurn = (stats: MeterStats, turn: Turn): MeterStats => {
  if (turn.usage === undefined) {
    return stats
  }
  const { output, all } = tokensOf(turn.usage)
  if (turn.agentId === undefined) {
    return {
      ...stats,
      main: { output: stats.main.output + output, all: stats.main.all + all },
    }
  }
  const held = stats.agents[turn.agentId] ?? { type: turn.type ?? 'unknown', output: 0, all: 0 }
  return {
    ...stats,
    agents: {
      ...stats.agents,
      [turn.agentId]: { type: held.type, output: held.output + output, all: held.all + all },
    },
  }
}

export const summarize = (stats: MeterStats): Summary | undefined => {
  const agents = Object.values(stats.agents)
  if (agents.length === 0) {
    return undefined
  }
  const sum = agents.reduce(
    (total, agent) => ({ output: total.output + agent.output, all: total.all + agent.all }),
    { output: 0, all: 0 },
  )
  const perType = new Map<string, number>()
  for (const agent of agents) {
    perType.set(agent.type, (perType.get(agent.type) ?? 0) + agent.all)
  }
  const [topType] = [...perType.entries()].sort(
    (a, b) => b[1] - a[1] || compare(a[0], b[0]),
  )[0]
  return {
    spawns: agents.length,
    outputShare: share(sum.output, sum.output + stats.main.output),
    allShare: share(sum.all, sum.all + stats.main.all),
    topType,
  }
}

export const formatLine = (summary: Summary): string =>
  `subagents ${summary.spawns}x · ${percent(summary.outputShare)} of output · ` +
  `${percent(summary.allShare)} of all tokens · top ${summary.topType.slice(0, MAX_TYPE_LENGTH)}`

export const statusLine = (stats: MeterStats): string | undefined => {
  const summary = summarize(stats)
  return summary === undefined ? undefined : formatLine(summary)
}
