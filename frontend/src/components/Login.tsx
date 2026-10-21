import { useState } from 'react';
import { setCredentials } from '../api/auth';

interface LoginProps {
  onLoggedIn: () => void;
}

export function Login({ onLoggedIn }: LoginProps) {
  const [userName, setUserName] = useState('admin');
  const [userKey, setUserKey] = useState('admin');

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!userName || !userKey) return;
    setCredentials({ userName, userKey });
    onLoggedIn();
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>PapaClaude</h1>
        <p>Sign in with your user name and key.</p>
        <div className="field">
          <label>User name</label>
          <input
            value={userName}
            onChange={(e) => setUserName(e.target.value)}
            autoFocus
          />
        </div>
        <div className="field">
          <label>User key</label>
          <input
            type="password"
            value={userKey}
            onChange={(e) => setUserKey(e.target.value)}
          />
        </div>
        <button className="btn primary" style={{ width: '100%' }} type="submit">
          Sign in
        </button>
        <p className="hint" style={{ marginTop: 12 }}>
          Local default: admin / admin
        </p>
      </form>
    </div>
  );
}
