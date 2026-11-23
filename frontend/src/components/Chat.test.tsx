import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { askQuestion } from '../api'
import type { AskResponse } from '../types'
import { Chat } from './Chat'

vi.mock('../api', () => ({ askQuestion: vi.fn() }))
const askMock = vi.mocked(askQuestion)

const plainAnswer: AskResponse = { answer: 'A nine-time world champion.', question_type: 'bio', sources: [], sql: null }

afterEach(() => {
  askMock.mockReset()
})

function setup() {
  const user = userEvent.setup()
  render(<Chat />)
  return { user, input: screen.getByRole('textbox'), send: screen.getByRole('button', { name: 'Send' }) }
}

describe('Chat', () => {
  it('sends the question and shows the answer', async () => {
    askMock.mockResolvedValue(plainAnswer)
    const { user, input } = setup()

    await user.type(input, 'Who is Rossi?{Enter}')

    expect(askMock).toHaveBeenCalledWith('Who is Rossi?')
    expect(screen.getByText('Who is Rossi?')).toBeInTheDocument()
    expect(await screen.findByText('A nine-time world champion.')).toBeInTheDocument()
    expect(input).toHaveValue('')
  })

  it('renders sources and SQL only when present', async () => {
    askMock.mockResolvedValueOnce({
      answer: 'He won 76 races.',
      question_type: 'stats',
      sources: [{ title: 'Valentino Rossi', url: 'https://en.wikipedia.org/wiki/Valentino_Rossi' }],
      sql: 'SELECT 1',
    })
    askMock.mockResolvedValueOnce(plainAnswer)
    const { user, input } = setup()

    await user.type(input, 'How many wins?{Enter}')
    expect(await screen.findByRole('link', { name: 'Valentino Rossi' })).toHaveAttribute(
      'href',
      'https://en.wikipedia.org/wiki/Valentino_Rossi',
    )
    expect(screen.getByText('SELECT 1').tagName).toBe('PRE')

    await user.type(input, 'Who is Rossi?{Enter}')
    await screen.findByText('A nine-time world champion.')
    expect(screen.getAllByText('Sources')).toHaveLength(1)
    expect(screen.getAllByText('SQL')).toHaveLength(1)
  })

  it('disables sending while a request is pending', async () => {
    askMock.mockReturnValue(new Promise<AskResponse>(() => {}))
    const { user, input, send } = setup()

    await user.type(input, 'Who is Rossi?{Enter}')
    await user.type(input, 'Another one')

    expect(send).toBeDisabled()
    await user.keyboard('{Enter}')
    expect(askMock).toHaveBeenCalledTimes(1)
  })

  it('shows an error and re-enables input when the request fails', async () => {
    askMock.mockRejectedValue(new Error('Request failed with status 500'))
    const { user, input, send } = setup()

    await user.type(input, 'Who is Rossi?{Enter}')

    expect(await screen.findByText(/Something went wrong/)).toBeInTheDocument()
    await user.type(input, 'Retry')
    expect(send).toBeEnabled()
  })

  it('does not send an empty question', async () => {
    const { user, input, send } = setup()

    expect(send).toBeDisabled()
    await user.type(input, '   {Enter}')
    expect(send).toBeDisabled()
    expect(askMock).not.toHaveBeenCalled()
  })
})
