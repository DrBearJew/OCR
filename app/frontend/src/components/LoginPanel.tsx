import { FormEvent, useState } from 'react'
import { Lock } from 'lucide-react'
import { login } from '../api/client'

export default function LoginPanel({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await login(username, password)
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    }
  }

  return (
    <main className="login-shell">
      <form className="login-panel" onSubmit={submit}>
        <div className="brand-row">
          <Lock size={22} />
          <h1>Dok OCR</h1>
        </div>
        <label>
          Username
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit">Sign in</button>
      </form>
    </main>
  )
}
