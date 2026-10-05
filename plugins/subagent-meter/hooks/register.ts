import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import { addTurn, emptyStats, statusLine } from './meter'

const stats = atom({ plugin: 'subagent-meter', key: 'stats' } as const, emptyStats())

export const register: Register = on => {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)

    try {
      const { usage, agentId } = e
      if (usage !== undefined) {
        let type: string | undefined
        if (agentId !== undefined && (await read($, stats)).agents[agentId] === undefined) {
          try {
            type = (await $.agent.list()).find(agent => agent.id === agentId)?.type
          } catch {
            type = undefined
          }
        }
        await update($, stats, held => addTurn(held, { agentId, type, usage }))
        $.ui.status(statusLine(await read($, stats)))
      }
    } catch {
      // The meter only watches; a failure here must never reach the turn.
    }

    return result
  })

  on('session.start', async ($, e, next) => {
    const result = await next(e)

    try {
      $.ui.status(statusLine(await read($, stats)))
    } catch {
      // Same rule: never break the session.
    }

    return result
  })

  on('session.end', async ($, e, next) => {
    // /clear and /resume both end the conversation while the process goes on under another
    // session, and the counts in session state would otherwise carry over into it.
    if (e.reason === 'clear' || e.reason === 'resume') {
      try {
        await update($, stats, () => emptyStats())
        $.ui.status(undefined)
      } catch {
        // Same rule: never break the session.
      }
    }

    return next(e)
  })
}
