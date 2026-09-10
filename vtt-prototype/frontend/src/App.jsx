import { useCallback, useEffect, useRef, useState } from 'react'

const DICE = [4, 6, 8, 10, 12, 20, 100]
const TOKEN_COLORS = ['#00ff88', '#3b82f6', '#f97316', '#e11d48', '#a855f7', '#eab308']

function wsUrl(room) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/${encodeURIComponent(room)}`
}

function rollDice(count, size) {
  const results = Array.from({ length: count }, () => 1 + Math.floor(Math.random() * size))
  return { results, total: results.reduce((a, b) => a + b, 0) }
}

export default function App() {
  const [room, setRoom] = useState(() => localStorage.getItem('vtt_room') || 'table1')
  const [playerName, setPlayerName] = useState(() => localStorage.getItem('vtt_name') || 'Player')
  const [connected, setConnected] = useState(false)
  const [tokens, setTokens] = useState({})
  const [chat, setChat] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [diceCount, setDiceCount] = useState(1)
  const [newTokenLabel, setNewTokenLabel] = useState('')
  const [newTokenColor, setNewTokenColor] = useState(TOKEN_COLORS[0])

  const wsRef = useRef(null)
  const boardRef = useRef(null)
  const dragRef = useRef(null)
  const chatEndRef = useRef(null)

  useEffect(() => localStorage.setItem('vtt_room', room), [room])
  useEffect(() => localStorage.setItem('vtt_name', playerName), [playerName])

  useEffect(() => {
    const ws = new WebSocket(wsUrl(room))
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      switch (msg.type) {
        case 'state':
          setTokens(msg.tokens)
          setChat(msg.chat)
          break
        case 'token_added':
          setTokens((t) => ({ ...t, [msg.token.id]: msg.token }))
          break
        case 'token_moved':
          setTokens((t) => (t[msg.id] ? { ...t, [msg.id]: { ...t[msg.id], x: msg.x, y: msg.y } } : t))
          break
        case 'token_removed':
          setTokens((t) => {
            const next = { ...t }
            delete next[msg.id]
            return next
          })
          break
        case 'chat':
          setChat((c) => [...c, { author: msg.author, text: msg.text }])
          break
      }
    }

    return () => ws.close()
  }, [room])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

  const send = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  const addToken = () => {
    if (!newTokenLabel.trim()) return
    send({ type: 'add_token', label: newTokenLabel.trim(), color: newTokenColor, x: 450, y: 300 })
    setNewTokenLabel('')
  }

  const removeToken = (id) => send({ type: 'remove_token', id })

  const onTokenPointerDown = (e, id) => {
    e.stopPropagation()
    e.target.setPointerCapture(e.pointerId)
    dragRef.current = { id }
  }

  const onBoardPointerMove = (e) => {
    if (!dragRef.current) return
    const rect = boardRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
    const y = Math.max(0, Math.min(rect.height, e.clientY - rect.top))
    const { id } = dragRef.current
    setTokens((t) => (t[id] ? { ...t, [id]: { ...t[id], x, y } } : t))
  }

  const onBoardPointerUp = () => {
    if (!dragRef.current) return
    const { id } = dragRef.current
    const token = tokens[id]
    if (token) send({ type: 'move_token', id, x: token.x, y: token.y })
    dragRef.current = null
  }

  const sendChat = () => {
    if (!chatInput.trim()) return
    send({ type: 'chat', author: playerName, text: chatInput.trim() })
    setChatInput('')
  }

  const roll = (size) => {
    const { results, total } = rollDice(diceCount, size)
    send({ type: 'roll', author: playerName, formula: `${diceCount}d${size}`, results, total })
  }

  return (
    <div style={styles.app}>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; background: #050810; }
        button { cursor: pointer; font-family: inherit; }
        input { font-family: inherit; }
      `}</style>

      <header style={styles.header}>
        <span style={styles.title}>VTT Prototype</span>
        <label style={styles.headerField}>
          Room
          <input style={styles.headerInput} value={room} onChange={(e) => setRoom(e.target.value)} />
        </label>
        <label style={styles.headerField}>
          Name
          <input style={styles.headerInput} value={playerName} onChange={(e) => setPlayerName(e.target.value)} />
        </label>
        <span style={{ color: connected ? '#00ff88' : '#e11d48', marginLeft: 'auto', fontSize: 13 }}>
          {connected ? '● connected' : '○ disconnected'}
        </span>
      </header>

      <main style={styles.main}>
        <div
          ref={boardRef}
          style={styles.board}
          onPointerMove={onBoardPointerMove}
          onPointerUp={onBoardPointerUp}
        >
          {Object.values(tokens).map((token) => (
            <div
              key={token.id}
              onPointerDown={(e) => onTokenPointerDown(e, token.id)}
              onDoubleClick={() => removeToken(token.id)}
              title="Drag to move, double-click to remove"
              style={{
                ...styles.token,
                left: token.x,
                top: token.y,
                background: token.color,
              }}
            >
              {token.label.slice(0, 2).toUpperCase()}
            </div>
          ))}
        </div>

        <aside style={styles.sidebar}>
          <section style={styles.panel}>
            <h3 style={styles.panelTitle}>Add token</h3>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                style={{ ...styles.headerInput, flex: 1 }}
                placeholder="Label"
                value={newTokenLabel}
                onChange={(e) => setNewTokenLabel(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addToken()}
              />
              <select
                style={styles.headerInput}
                value={newTokenColor}
                onChange={(e) => setNewTokenColor(e.target.value)}
              >
                {TOKEN_COLORS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <button style={styles.button} onClick={addToken}>Add</button>
            </div>
          </section>

          <section style={styles.panel}>
            <h3 style={styles.panelTitle}>Dice</h3>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <span style={{ color: '#94a3b8', fontSize: 13 }}>Count</span>
              <input
                type="number"
                min={1}
                max={20}
                style={{ ...styles.headerInput, width: 50 }}
                value={diceCount}
                onChange={(e) => setDiceCount(Math.max(1, Number(e.target.value) || 1))}
              />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {DICE.map((size) => (
                <button key={size} style={styles.diceButton} onClick={() => roll(size)}>
                  d{size}
                </button>
              ))}
            </div>
          </section>

          <section style={{ ...styles.panel, flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <h3 style={styles.panelTitle}>Chat</h3>
            <div style={styles.chatLog}>
              {chat.map((m, i) => (
                <div key={i} style={styles.chatLine}>
                  <span style={{ color: '#00ff88' }}>{m.author}: </span>
                  <span style={{ color: '#e2e8f0' }}>{m.text}</span>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              <input
                style={{ ...styles.headerInput, flex: 1 }}
                placeholder="Say something..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendChat()}
              />
              <button style={styles.button} onClick={sendChat}>Send</button>
            </div>
          </section>
        </aside>
      </main>
    </div>
  )
}

const styles = {
  app: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: '"IBM Plex Mono", monospace',
    color: '#e2e8f0',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    padding: '10px 16px',
    borderBottom: '1px solid #1e293b',
    background: '#0a0f1c',
  },
  title: { fontFamily: '"Syne", sans-serif', fontWeight: 700, color: '#00ff88' },
  headerField: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#94a3b8' },
  headerInput: {
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 4,
    color: '#e2e8f0',
    padding: '4px 8px',
    fontSize: 13,
  },
  main: { display: 'flex', flex: 1, minHeight: 0, gap: 16, padding: 16 },
  board: {
    position: 'relative',
    flex: 1,
    background:
      'repeating-linear-gradient(0deg, #0d1424, #0d1424 39px, #1e293b 40px), repeating-linear-gradient(90deg, #0d1424, #0d1424 39px, #1e293b 40px)',
    border: '1px solid #334155',
    borderRadius: 8,
    overflow: 'hidden',
    touchAction: 'none',
  },
  token: {
    position: 'absolute',
    width: 40,
    height: 40,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transform: 'translate(-50%, -50%)',
    fontSize: 12,
    fontWeight: 700,
    color: '#050810',
    border: '2px solid rgba(255,255,255,0.4)',
    cursor: 'grab',
    userSelect: 'none',
  },
  sidebar: { width: 300, display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 },
  panel: {
    background: '#0a0f1c',
    border: '1px solid #1e293b',
    borderRadius: 8,
    padding: 12,
  },
  panelTitle: {
    fontFamily: '"Syne", sans-serif',
    fontSize: 13,
    textTransform: 'uppercase',
    letterSpacing: 1,
    color: '#475569',
    margin: '0 0 10px',
  },
  button: {
    background: '#00ff88',
    border: 'none',
    borderRadius: 4,
    padding: '4px 12px',
    fontSize: 13,
    fontWeight: 700,
    color: '#050810',
  },
  diceButton: {
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 4,
    padding: '6px 10px',
    fontSize: 13,
    color: '#e2e8f0',
  },
  chatLog: { flex: 1, overflowY: 'auto', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 },
  chatLine: { wordBreak: 'break-word' },
}
