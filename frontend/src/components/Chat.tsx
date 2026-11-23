import { type FormEvent, useState } from 'react'
import { askQuestion } from '../api'
import type { AskResponse } from '../types'
import './Chat.css'

const MAX_QUESTION_LENGTH = 500 // mirrors the backend limit

type Message =
  | { role: 'user'; text: string }
  | { role: 'assistant'; response: AskResponse }
  | { role: 'error'; text: string }

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)

  const question = draft.trim()
  const canSend = question.length > 0 && !pending

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSend) return
    setMessages((previous) => [...previous, { role: 'user', text: question }])
    setDraft('')
    setPending(true)
    try {
      const response = await askQuestion(question)
      setMessages((previous) => [...previous, { role: 'assistant', response }])
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      setMessages((previous) => [...previous, { role: 'error', text: `Something went wrong: ${reason}` }])
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="chat">
      <ol className="chat__messages" aria-live="polite">
        {messages.map((message, index) => (
          <li key={index} className={`chat__message chat__message--${message.role}`}>
            {message.role === 'assistant' ? <AssistantAnswer response={message.response} /> : message.text}
          </li>
        ))}
        {pending && <li className="chat__message chat__message--pending">Thinking…</li>}
      </ol>
      <form className="chat__form" onSubmit={handleSubmit}>
        <input
          aria-label="Question"
          placeholder="Ask about a MotoGP rider…"
          maxLength={MAX_QUESTION_LENGTH}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={!canSend}>
          Send
        </button>
      </form>
    </section>
  )
}

function AssistantAnswer({ response }: { response: AskResponse }) {
  return (
    <>
      <p>{response.answer}</p>
      {response.sources.length > 0 && (
        <>
          <h3>Sources</h3>
          <ul>
            {response.sources.map((source) => (
              <li key={source.url}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
      {response.sql !== null && (
        <>
          <h3>SQL</h3>
          <pre>{response.sql}</pre>
        </>
      )}
    </>
  )
}
