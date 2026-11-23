import { Chat } from './components/Chat'

export default function App() {
  return (
    <main className="app">
      <header>
        <h1>Paddock</h1>
        <p>Ask anything about MotoGP riders</p>
      </header>
      <Chat />
    </main>
  )
}
