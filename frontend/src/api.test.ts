import { afterEach, describe, expect, it, vi } from 'vitest'
import { askQuestion } from './api'
import type { AskResponse } from './types'

const body: AskResponse = { answer: 'Nine titles.', question_type: 'bio', sources: [], sql: null }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('askQuestion', () => {
  it('posts the question as JSON and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body })
    vi.stubGlobal('fetch', fetchMock)

    await expect(askQuestion('Rossi?')).resolves.toEqual(body)
    expect(fetchMock).toHaveBeenCalledWith('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'Rossi?' }),
    })
  })

  it('throws on a non-2xx response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }))

    await expect(askQuestion('Rossi?')).rejects.toThrow('Request failed with status 500')
  })
})
