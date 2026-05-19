import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Archive, Clock, Database, FileText, Globe, Lock, Server, Shield, Trash2 } from 'lucide-react';
import './style.css';

const API = import.meta.env.VITE_API_URL || '/api';

function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [domain, setDomain] = useState('example.com');
  const [adminEmail, setAdminEmail] = useState('admin@example.com');
  const [phpVersion, setPhpVersion] = useState('8.3');
  const [websites, setWebsites] = useState([]);
  const [databases, setDatabases] = useState([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState('');
  const [cronSchedule, setCronSchedule] = useState('0 2 * * *');
  const [cronCommand, setCronCommand] = useState('wp cron event run --due-now --allow-root');
  const [filePath, setFilePath] = useState('public/wp-config.php');
  const [fileContent, setFileContent] = useState('');
  const [output, setOutput] = useState('BPanel ready');
  const [error, setError] = useState('');

  async function request(path, options = {}) {
    try {
      setError('');
      const res = await fetch(`${API}${path}`, {
        ...options,
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '', ...(options.headers || {}) },
      });
      const text = await res.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        data = { detail: text || `HTTP ${res.status}` };
      }
      setOutput(JSON.stringify(data, null, 2));
      if (!res.ok) setError(data.detail || `Request failed with status ${res.status}`);
      return res.ok ? data : null;
    } catch (err) {
      setError(`Không kết nối được API backend tại ${API}. Kiểm tra bpanel-api và Nginx proxy.`);
      setOutput(String(err));
      return null;
    }
  }

  async function login() {
    try {
      setError('');
      const body = new URLSearchParams({ username, password });
      const res = await fetch(`${API}/auth/login`, { method: 'POST', body });
      const data = await res.json();
      if (data.access_token) {
        localStorage.setItem('token', data.access_token);
        setToken(data.access_token);
        setOutput('Đăng nhập thành công.');
      } else {
        setError(data.detail || `Đăng nhập thất bại với status ${res.status}`);
        setOutput(JSON.stringify(data, null, 2));
      }
    } catch (err) {
      setError(`Không kết nối được API backend tại ${API}. Kiểm tra bpanel-api và Nginx proxy.`);
      setOutput(String(err));
    }
  }

  function logout() {
    localStorage.removeItem('token');
    setToken('');
    setOutput('Đã đăng xuất.');
  }

  async function refreshAll() {
    const siteData = await request('/websites');
    if (siteData) {
      setWebsites(siteData);
      if (!selectedWebsiteId && siteData[0]) setSelectedWebsiteId(String(siteData[0].id));
    }
    const dbData = await request('/databases');
    if (dbData) setDatabases(dbData);
  }

  async function createWordPress() {
    const data = await request('/websites/wordpress', {
      method: 'POST',
      body: JSON.stringify({ domain, php_version: phpVersion, admin_email: adminEmail, admin_password: 'StrongPass123!', title: domain }),
    });
    if (data) refreshAll();
  }

  async function deleteWebsite(id) {
    if (!confirm('Xóa website này, gồm file, vhost và database?')) return;
    const data = await request(`/websites/${id}?delete_files=true&delete_database=true`, { method: 'DELETE' });
    if (data) refreshAll();
  }

  async function enableSsl(id) {
    const data = await request(`/websites/${id}/ssl`, { method: 'POST' });
    if (data) refreshAll();
  }

  async function changeDbPassword(id) {
    const newPass = prompt('Nhập mật khẩu database mới, tối thiểu 12 ký tự:');
    if (!newPass) return;
    await request(`/databases/${id}/password`, { method: 'POST', body: JSON.stringify({ password: newPass }) });
  }


  async function openPhpMyAdmin(databaseId) {
    try {
      setError('');
      setLoading?.('Opening phpMyAdmin...');
      const res = await fetch(`${API}/databases/${databaseId}/phpmyadmin-sso`, {
        method: 'POST',
        headers: { Authorization: token ? `Bearer ${token}` : '' },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.url) {
        setError(data.detail || `Cannot open phpMyAdmin with status ${res.status}.`);
        return;
      }
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setError('Cannot open phpMyAdmin.');
      if (typeof setNotice === 'function') setNotice(String(err));
      if (typeof setOutput === 'function') setOutput(String(err));
    } finally {
      if (typeof setLoading === 'function') setLoading('');
    }
  }

  async function downloadDatabase(id, name) {
    try {
      setError('');
      const res = await fetch(`${API}/databases/${id}/download`, { headers: { Authorization: token ? `Bearer ${token}` : '' } });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || 'Download database th?t b?i.');
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${name || 'database'}.sql`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setOutput('Downloaded database SQL.');
    } catch (err) {
      setError('Download database th?t b?i.');
      setOutput(String(err));
    }
  }

  async function addCron() {
    await request('/maintenance/cron', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), schedule: cronSchedule, command: cronCommand }) });
  }

  async function deleteCron() {
    const index = Number(prompt('Nhập số thứ tự cron cần xóa, bắt đầu từ 0:'));
    if (Number.isNaN(index)) return;
    await request('/maintenance/cron', { method: 'DELETE', body: JSON.stringify({ website_id: Number(selectedWebsiteId), index }) });
  }


  async function createBackup() {
    await request('/maintenance/backup', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId) }) });
  }

  async function uploadBackup(file) {
    if (!file || !selectedWebsiteId) return;
    const form = new FormData();
    form.append('file', file);
    try {
      setError('');
      const res = await fetch(`${API}/maintenance/backups/${selectedWebsiteId}/upload`, {
        method: 'POST',
        headers: { Authorization: token ? `Bearer ${token}` : '' },
        body: form,
      });
      const responseText = await res.text();
      let data;
      try {
        data = responseText ? JSON.parse(responseText) : {};
      } catch {
        data = { detail: responseText || `HTTP ${res.status}` };
      }
      setOutput(JSON.stringify(data, null, 2));
      if (!res.ok) setError(data.detail || `Upload backup failed with status ${res.status}.`);
    } catch (err) {
      setError('Upload backup failed.');
      setOutput(String(err));
    }
  }

  async function restoreBackup() {
    const backupFile = prompt('Enter backup .tar.gz path to restore:');
    if (!backupFile) return;
    await request('/maintenance/restore', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), backup_file: backupFile }) });
  }

  async function readFile() {
    const data = await request(`/maintenance/files/${selectedWebsiteId}/read?path=${encodeURIComponent(filePath)}`);
    if (data?.content !== undefined) setFileContent(data.content);
  }

  async function writeFile() {
    await request('/maintenance/files/write', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: filePath, content: fileContent }) });
  }

  useEffect(() => {
    if (token) refreshAll();
  }, [token]);

  const cards = [
    ['System', Server, () => request('/services/system-info')],
    ['Refresh', Globe, refreshAll],
    ['Databases', Database, () => request('/databases')],
    ['Install Stack', Shield, () => request('/services/install-wordpress-stack', { method: 'POST' })],
    ['Backups', Archive, () => selectedWebsiteId && request(`/maintenance/backups/${selectedWebsiteId}`)],
    ['Cron list', Clock, () => selectedWebsiteId && request(`/maintenance/cron/${selectedWebsiteId}`)],
  ];

  if (!token) {
    return <main className="login-page">
      <section className="login-card">
        <div>
          <p className="eyebrow">Ubuntu 24.04 WordPress Panel</p>
          <h1>BPanel</h1>
          <p className="hint">Login to manage the panel.</p>
        </div>
        <div className="login-form">
          <input value={username} onChange={e => setUsername(e.target.value)} placeholder="Username" autoComplete="username" />
          <input value={password} onChange={e => setPassword(e.target.value)} placeholder="Password" type="password" autoComplete="current-password" onKeyDown={e => { if (e.key === 'Enter') login(); }} />
          <button disabled={!username || !password} onClick={login}>Login</button>
        </div>
        {error && <div className="error">{error}</div>}
      </section>
    </main>;
  }

  return <main>
    <section className="hero">
      <div>
        <p className="eyebrow">Ubuntu 24.04 WordPress Panel</p>
        <h1>BPanel</h1>
        <p>Manage WordPress websites, SSL, databases, cron, PHP, and file manager.</p>
      </div>
      <div className="login">
        <strong>Logged in</strong>
        <button className="secondary" onClick={logout}>Logout</button>
      </div>
    </section>

    <section className="panel">
      <div className="form">
        <h2>Tạo WordPress</h2>
        <input value={domain} onChange={e => setDomain(e.target.value)} placeholder="domain.com" />
        <input value={adminEmail} onChange={e => setAdminEmail(e.target.value)} placeholder="admin@domain.com" />
        <select value={phpVersion} onChange={e => setPhpVersion(e.target.value)}>
          <option value="8.3">PHP 8.3</option>
          <option value="8.4">PHP 8.4</option>
        </select>
        <button onClick={createWordPress}>Tạo website</button>
      </div>
      <div className="grid">
        {cards.map(([label, Icon, action]) => <button className="card" key={label} onClick={action}>
          <Icon size={28} /><span>{label}</span>
        </button>)}
      </div>
    </section>

    <section className="section">
      <h2>Websites</h2>
      <div className="table">
        {websites.map(site => <div className="row" key={site.id}>
          <span>{site.domain}</span><span>PHP {site.php_version}</span><span>{site.status}</span>
          <button onClick={() => enableSsl(site.id)}><Lock size={16}/> SSL</button>
          <button onClick={() => deleteWebsite(site.id)}><Trash2 size={16}/> Xóa</button>
        </div>)}
      </div>
    </section>

    <section className="section two">
      <div>
        <h2>Database</h2>
        <div className="table">
          {databases.map(db => <div className="row" key={db.id}>
            <span>{db.db_name}</span><span>{db.db_user}</span>
            <button disabled={!!loading} onClick={() => openPhpMyAdmin(db.id)}>Open phpMyAdmin</button>
            <button onClick={() => downloadDatabase(db.id, db.db_name)}>Download SQL</button>
            <button onClick={() => changeDbPassword(db.id)}>Đổi pass</button>
          </div>)}
        </div>
        <p><a href="/phpmyadmin/" target="_blank" rel="noreferrer">Open phpMyAdmin</a></p>
      </div>
      <div>
        <h2>Cron</h2>
        <select value={selectedWebsiteId} onChange={e => setSelectedWebsiteId(e.target.value)}>
          <option value="">Chọn website</option>
          {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
        </select>
        <input value={cronSchedule} onChange={e => setCronSchedule(e.target.value)} placeholder="0 2 * * *" />
        <input value={cronCommand} onChange={e => setCronCommand(e.target.value)} placeholder="wp cron event run --due-now --allow-root" />
        <button onClick={addCron}>Thêm cron</button>
        <button onClick={deleteCron}>Xóa cron</button>
      </div>
    </section>


    <section className="section">
      <h2>Backups</h2>
      <select value={selectedWebsiteId} onChange={e => setSelectedWebsiteId(e.target.value)}>
        <option value="">Select website</option>
        {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
      </select>
      <button onClick={createBackup}>Create backup</button>
      <label className="upload-button">Upload backup<input type="file" accept=".tar.gz,application/gzip" onChange={e => { uploadBackup(e.target.files?.[0]); e.target.value = ''; }} /></label>
      <button onClick={restoreBackup}>Restore backup</button>
    </section>

    <section className="section">
      <h2>File manager</h2>
      <input value={filePath} onChange={e => setFilePath(e.target.value)} placeholder="public/wp-config.php" />
      <button onClick={readFile}><FileText size={16}/> Đọc file</button>
      <button onClick={writeFile}>Lưu file</button>
      <textarea value={fileContent} onChange={e => setFileContent(e.target.value)} rows={12} />
    </section>

    {error && <div className="error">{error}</div>}
    <pre>{output}</pre>
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
