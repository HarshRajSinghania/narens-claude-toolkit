export type MeterAgent = { type: string; output: number; all: number }

export type MeterStats = {
  main: { output: number; all: number }
  agents: Record<string, MeterAgent>
}

declare module 'claude-code' {
  interface PluginState {
    'subagent-meter': { stats: MeterStats }
  }
}
