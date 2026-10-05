import type { Register } from 'claude-code'

export const register: Register = on => {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    $.ui.status(e.agentId === undefined ? 'main turn' : `agent ${e.agentId}`)
    return result
  })
}
