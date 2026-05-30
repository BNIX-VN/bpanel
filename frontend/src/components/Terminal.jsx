import { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal as XTerminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

export function Terminal({ websiteId }) {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const historyRef = useRef([]);
  const historyIndexRef = useRef(-1);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    // Use relative URL with cookies (browser sends cookies automatically)
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/terminal/ws/${websiteId}`;
    const ws = new WebSocket(wsUrl);
    // Important: for cross-origin WebSocket with cookies, we need credentials
    ws.withCredentials = true;
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setError(null);
      termRef.current?.write('\x1b[1;32mConnected to terminal\x1b[0m\r\n\r\n');
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'output') {
          termRef.current?.write(msg.data);
        } else if (msg.type === 'exit') {
          termRef.current?.write(`\r\n\x1b[33m[exit code: ${msg.code}]\x1b[0m\r\n`);
        } else if (msg.type === 'pong') {
          // Heartbeat response
        } else if (msg.type === 'error') {
          termRef.current?.write(`\x1b[31mError: ${msg.data}\x1b[0m\r\n`);
        }
      } catch {
        // Raw output (for non-JSON fallback)
        termRef.current?.write(e.data);
      }
    };

    ws.onclose = (e) => {
      setConnected(false);
      if (e.code !== 1000) {
        termRef.current?.write('\r\n\x1b[31mDisconnected\x1b[0m\r\n');
      }
    };

    ws.onerror = () => {
      setError('Connection failed');
      setConnected(false);
    };
  }, [websiteId, token]);

  const disconnect = useCallback(() => {
    wsRef.current?.close(1000);
    wsRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new XTerminal({
      cursorBlink: true,
      cursorStyle: 'block',
      fontSize: 14,
      fontFamily: '"Cascadia Code", "Fira Code", "Monaco", "Courier New", monospace',
      theme: {
        background: '#1e1e1e',
        foreground: '#d4d4d4',
        cursor: '#ffffff',
        cursorAccent: '#1e1e1e',
        selectionBackground: '#264f78',
        black: '#1e1e1e',
        red: '#f44747',
        green: '#6a9955',
        yellow: '#dcdcaa',
        blue: '#569cd6',
        magenta: '#c586c0',
        cyan: '#4ec9b0',
        white: '#d4d4d4',
        brightBlack: '#808080',
        brightRed: '#f44747',
        brightGreen: '#6a9955',
        brightYellow: '#dcdcaa',
        brightBlue: '#569cd6',
        brightMagenta: '#c586c0',
        brightCyan: '#4ec9b0',
        brightWhite: '#ffffff',
      },
      scrollback: 1000,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    fitAddon.fit();

    termRef.current = term;

    // Handle resize
    const handleResize = () => {
      fitAddon.fit();
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'resize',
          cols: term.cols,
          rows: term.rows,
        }));
      }
    };
    window.addEventListener('resize', handleResize);

    // Handle user input
    let currentLine = '';
    let cursorPos = 0;

    term.onData((data) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        // Not connected - try to connect
        if (data === '\r' || data === '\n') {
          term.write('\r\n\x1b[31mNot connected. Click Connect to start.\x1b[0m\r\n');
          currentLine = '';
          cursorPos = 0;
        }
        return;
      }

      const code = data.charCodeAt(0);

      if (code === 13) { // Enter
        const cmd = currentLine.trim();
        if (cmd) {
          historyRef.current = [cmd, ...historyRef.current.slice(0, 49)];
          historyIndexRef.current = -1;
        }
        wsRef.current.send(JSON.stringify({ type: 'input', data: cmd + '\n' }));
        currentLine = '';
        cursorPos = 0;
      } else if (code === 127 || code === 8) { // Backspace
        if (cursorPos > 0) {
          currentLine = currentLine.slice(0, cursorPos - 1) + currentLine.slice(cursorPos);
          cursorPos--;
          term.write('\b \b');
          if (cursorPos < currentLine.length) {
            term.write(currentLine.slice(cursorPos) + ' ');
            for (let i = 0; i <= currentLine.length - cursorPos; i++) {
              term.write('\b');
            }
          }
        }
      } else if (code === 27) { // Escape sequences (arrows)
        const seq = data;
        if (seq === '\x1b[A') { // Up - history
          if (historyIndexRef.current < historyRef.current.length - 1) {
            historyIndexRef.current++;
            const histCmd = historyRef.current[historyIndexRef.current];
            // Clear current line
            term.write('\r\x1b[K');
            term.write(`$ ${histCmd}`);
            currentLine = histCmd;
            cursorPos = currentLine.length;
          }
        } else if (seq === '\x1b[B') { // Down
          if (historyIndexRef.current > 0) {
            historyIndexRef.current--;
            const histCmd = historyRef.current[historyIndexRef.current];
            term.write('\r\x1b[K');
            term.write(`$ ${histCmd}`);
            currentLine = histCmd;
            cursorPos = currentLine.length;
          } else if (historyIndexRef.current === 0) {
            historyIndexRef.current = -1;
            term.write('\r\x1b[K');
            term.write('$ ');
            currentLine = '';
            cursorPos = 0;
          }
        }
      } else if (code >= 32) { // Printable characters
        currentLine = currentLine.slice(0, cursorPos) + data + currentLine.slice(cursorPos);
        cursorPos += data.length;
        term.write(data);
        if (cursorPos < currentLine.length) {
          term.write(currentLine.slice(cursorPos));
          for (let i = 0; i < currentLine.length - cursorPos; i++) {
            term.write('\b');
          }
        }
      }
    });

    // Cleanup
    return () => {
      window.removeEventListener('resize', handleResize);
      disconnect();
      term.dispose();
      termRef.current = null;
    };
  }, [connect, disconnect]);

  return (
    <div className="terminal-wrapper">
      <div className="terminal-toolbar">
        <span className="terminal-status">
          {connected ? (
            <span className="status-connected">● Connected</span>
          ) : error ? (
            <span className="status-error">✕ {error}</span>
          ) : (
            <span className="status-disconnected">○ Disconnected</span>
          )}
        </span>
        {connected ? (
          <button onClick={disconnect} className="terminal-btn disconnect">Disconnect</button>
        ) : (
          <button onClick={connect} className="terminal-btn connect">Connect</button>
        )}
      </div>
      <div ref={containerRef} className="terminal-container" />
      <style>{`
        .terminal-wrapper {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: #1e1e1e;
          border-radius: 8px;
          overflow: hidden;
        }
        .terminal-toolbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: #252526;
          border-bottom: 1px solid #3c3c3c;
        }
        .terminal-status {
          font-size: 13px;
          font-family: monospace;
        }
        .status-connected { color: #6a9955; }
        .status-disconnected { color: #808080; }
        .status-error { color: #f44747; }
        .terminal-btn {
          padding: 4px 12px;
          border: none;
          border-radius: 4px;
          font-size: 12px;
          cursor: pointer;
          transition: opacity 0.2s;
        }
        .terminal-btn:hover { opacity: 0.8; }
        .terminal-btn.connect {
          background: #0e639c;
          color: white;
        }
        .terminal-btn.disconnect {
          background: #c9392c;
          color: white;
        }
        .terminal-container {
          flex: 1;
          padding: 8px;
          overflow: hidden;
        }
        .terminal-container .xterm {
          height: 100%;
        }
        .terminal-container .xterm-viewport {
          overflow-y: auto !important;
        }
      `}</style>
    </div>
  );
}
