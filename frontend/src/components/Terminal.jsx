import { useEffect, useRef, useState } from 'react';
import { Terminal as XTerminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { t } from '../i18n';

// A real shell (bash on a PTY) in a sandbox of its own on the server; see
// backend/app/services/terminal.py. Keystrokes go up as binary frames, the
// window size as JSON; the output comes back as binary frames, the panel's
// own messages ("ready", "closed") as JSON. Leaving the page closes the
// socket, and the server ends the session with it.

function terminalWebSocketUrl(apiBase, websiteId, cols, rows) {
  const base = String(apiBase || '/api');
  const path = websiteId ? `/terminal/ws/${websiteId}` : '/terminal/ws';
  const query = `?cols=${cols}&rows=${rows}`;
  if (/^https?:\/\//i.test(base)) {
    const url = new URL(base);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = `${url.pathname.replace(/\/$/, '')}${path}`;
    url.search = query;
    url.hash = '';
    return url.toString();
  }
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${window.location.host}${base.replace(/\/$/, '')}${path}${query}`;
}

// Why a session ended or never started, in words.
function closedText(closed, rules) {
  const idle = rules?.idle_minutes || 30;
  const hours = rules?.max_hours || 8;
  switch (closed?.reason) {
    case 'exit': return closed.code ? t('The shell has ended (exit code {code}).', { code: closed.code }) : t('The shell has ended.');
    case 'idle': return t('Closed after {minutes} minutes without input.', { minutes: idle });
    case 'max-time': return t('Closed: a session lasts at most {hours} hours.', { hours });
    case 'access-changed': return t('Closed: this browser was signed out, or the account no longer has the terminal.');
    case 'account-deleted': return t('Closed: the account was deleted.');
    case 'too-many': return t('This account already has {n} terminals open. Close one first.', { n: rules?.max_sessions || 2 });
    case 'disabled': return t("The terminal is not part of this account's package.");
    case 'impersonate': return t("Administrators and resellers open a customer's terminal by logging in as the customer.");
    case 'demo': return t('The terminal is not available in the demo.');
    case 'signed-out': return t('Your session has ended. Sign in again.');
    case 'not-found': return t('Website not found.');
    case 'unavailable': return t('The terminal works on the server only.');
    case 'origin': return t('This address may not open the terminal.');
    case 'failed': return t('The terminal could not start.');
    case 'lost': return t('The connection was lost.');
    default: return t('Disconnected.');
  }
}

const XTERM_THEME = {
  // Always dark, the panel's console tokens (--console-* in style.css); xterm
  // needs literal colours. Neutral, with the cursor in brand blue.
  background: '#111111',
  foreground: '#f0f0f0',
  cursor: '#4d9ee6',
  selectionBackground: '#3a3a3a',
  black: '#111111',
  red: '#ef4444',
  green: '#22c55e',
  yellow: '#eab308',
  blue: '#60a5fa',
  magenta: '#c084fc',
  cyan: '#2dd4bf',
  white: '#e5e7eb',
  brightBlack: '#8b93a1',
  brightRed: '#f87171',
  brightGreen: '#4ade80',
  brightYellow: '#facc15',
  brightBlue: '#93c5fd',
  brightMagenta: '#d8b4fe',
  brightCyan: '#5eead4',
  brightWhite: '#ffffff',
};

export function Terminal({ websiteId = null, apiBase = '/api' }) {
  const containerRef = useRef(null);
  const socketRef = useRef(null);
  const [state, setState] = useState('connecting'); // connecting | open | closed
  const [info, setInfo] = useState(null);
  const [closed, setClosed] = useState(null);
  // A new attempt is a new session: a fresh terminal and a fresh socket.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    setState('connecting');
    setInfo(null);
    setClosed(null);

    const term = new XTerminal({
      cursorBlink: true,
      // A phone gets a few more columns.
      fontSize: window.innerWidth < 600 ? 12 : 14,
      fontFamily: 'Consolas, "Liberation Mono", Menlo, monospace',
      scrollback: 5000,
      theme: XTERM_THEME,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    try { fit.fit(); } catch {}

    const ws = new WebSocket(terminalWebSocketUrl(apiBase, websiteId, term.cols, term.rows));
    ws.binaryType = 'arraybuffer';
    socketRef.current = ws;
    const encoder = new TextEncoder();
    let told = false;

    ws.onmessage = (event) => {
      if (typeof event.data !== 'string') {
        term.write(new Uint8Array(event.data));
        return;
      }
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (message.type === 'ready') {
        setInfo(message);
        setState('open');
        term.focus();
      } else if (message.type === 'closed') {
        told = true;
        setClosed(message);
        setState('closed');
      }
    };
    ws.onclose = (event) => {
      if (!told) setClosed({ reason: event.code === 1000 ? 'closed' : 'lost', code: event.code });
      setState('closed');
    };

    const send = (bytes) => { if (ws.readyState === WebSocket.OPEN) ws.send(bytes); };
    const typed = term.onData(data => send(encoder.encode(data)));
    // Mouse reports in some programs: one byte per character.
    const binary = term.onBinary(data => send(Uint8Array.from(data, ch => ch.charCodeAt(0) & 255)));

    let frame = 0;
    const resize = () => {
      frame = 0;
      try { fit.fit(); } catch { return; }
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
    };
    const scheduleResize = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(resize);
    };
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(scheduleResize) : null;
    observer?.observe(containerRef.current);
    window.addEventListener('resize', scheduleResize);
    ws.onopen = scheduleResize;

    return () => {
      window.removeEventListener('resize', scheduleResize);
      observer?.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
      typed.dispose();
      binary.dispose();
      ws.onclose = null;
      ws.onmessage = null;
      ws.close(1000);
      socketRef.current = null;
      term.dispose();
    };
  }, [apiBase, websiteId, attempt]);

  const rules = info || closed;
  return (
    <div className="web-terminal">
      <div className="web-terminal-bar">
        <span className={`web-terminal-state is-${state}`}>
          {state === 'open' ? t('Connected') : state === 'connecting' ? t('Connecting…') : t('Closed')}
        </span>
        {info && <span className="web-terminal-where" title={info.cwd}>
          {info.user}<span aria-hidden="true">:</span>{info.cwd}{info.php ? ` · PHP ${info.php}` : ''}
        </span>}
        <span className="web-terminal-actions">
          {state === 'closed'
            ? <button type="button" className="mini" onClick={() => setAttempt(n => n + 1)}>{t('New session')}</button>
            : <button type="button" className="mini secondary-light" onClick={() => socketRef.current?.close(1000)}>{t('End session')}</button>}
        </span>
      </div>
      {state === 'closed' && <p className="web-terminal-closed" role="status">{closedText(closed, rules)}</p>}
      <div className="web-terminal-screen"><div ref={containerRef} className="web-terminal-fit" /></div>
      <p className="hint web-terminal-rules">
        {t('Closes after {minutes} minutes without input and after {hours} hours in any case. Leaving this page ends the session.', { minutes: info?.idle_minutes || 30, hours: info?.max_hours || 8 })}
      </p>
    </div>
  );
}
