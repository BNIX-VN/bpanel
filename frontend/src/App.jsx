import React, { useEffect, useState, useCallback, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { basicSetup } from 'codemirror';
import { indentWithTab } from '@codemirror/commands';
import { css } from '@codemirror/lang-css';
import { html } from '@codemirror/lang-html';
import { javascript } from '@codemirror/lang-javascript';
import { json } from '@codemirror/lang-json';
import { php } from '@codemirror/lang-php';
import { yaml } from '@codemirror/lang-yaml';
import { Compartment, EditorState } from '@codemirror/state';
import { EditorView, keymap } from '@codemirror/view';
import { Archive, Clock, Code2, Cpu, Database, FileText, FolderOpen, Globe, HardDrive, Home, Image, KeyRound, Lock, LogIn, LogOut, MemoryStick, Menu, Network, Server, Settings as SettingsIcon, Shield, Trash2, Users, X, RefreshCw, Plus, Download, Upload, Play, Square, RotateCcw, AlertCircle } from 'lucide-react';
import './style.css';
import './brand.css';
import './file-manager.css';

const API = import.meta.env.VITE_API_URL || '/api';
const SERVICE_NAMES = ['bpanel-api', 'nginx', 'php8.3-fpm', 'php8.4-fpm', 'mariadb', 'redis-server'];

function editorParamsFromLocation() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('view') !== 'editor') return null;
  const websiteId = params.get('website_id');
  const path = params.get('path') || 'public/index.html';
  if (!websiteId) return null;
  return { websiteId: String(websiteId), path };
}

const editorTheme = EditorView.theme({
  '&': { height: '100%', backgroundColor: '#ffffff', color: '#0f172a' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: "Consolas, 'SFMono-Regular', 'Liberation Mono', Menlo, monospace", fontSize: '13px', lineHeight: '1.55' },
  '.cm-content': { minHeight: '100%', padding: '14px 0' },
  '.cm-line': { padding: '0 16px' },
  '.cm-gutters': { backgroundColor: '#f6f8fb', color: '#64748b', borderRight: '1px solid #dbe4f0' },
  '.cm-lineNumbers .cm-gutterElement': { minWidth: '44px', padding: '0 12px 0 8px' },
  '.cm-activeLine': { backgroundColor: '#eef6ff' },
  '.cm-activeLineGutter': { backgroundColor: '#e2efff', color: '#0b5fbd' },
  '.cm-selectionBackground': { backgroundColor: '#bfdbfe !important' },
  '.cm-cursor': { borderLeftColor: '#0b5fbd' },
  '.cm-matchingBracket, .cm-nonmatchingBracket': { backgroundColor: '#dbeafe', outline: '1px solid #93c5fd' },
});

function languageExtension(mode) {
  if (mode === 'PHP') return php();
  if (mode === 'JavaScript') return javascript({ jsx: true, typescript: true });
  if (mode === 'CSS') return css();
  if (mode === 'HTML') return html();
  if (mode === 'JSON') return json();
  if (mode === 'YAML') return yaml();
  return [];
}

function CodeEditor({ value, mode, disabled, onChange, onCursorChange }) {
  const hostRef = useRef(null);
  const viewRef = useRef(null);
  const onChangeRef = useRef(onChange);
  const onCursorChangeRef = useRef(onCursorChange);
  const languageCompartmentRef = useRef(new Compartment());
  const editableCompartmentRef = useRef(new Compartment());

  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  useEffect(() => { onCursorChangeRef.current = onCursorChange; }, [onCursorChange]);

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const languageCompartment = languageCompartmentRef.current;
    const editableCompartment = editableCompartmentRef.current;
    const view = new EditorView({
      parent: hostRef.current,
      state: EditorState.create({
        doc: value || '',
        extensions: [
          basicSetup,
          keymap.of([indentWithTab]),
          editorTheme,
          languageCompartment.of(languageExtension(mode)),
          editableCompartment.of([EditorState.readOnly.of(!!disabled), EditorView.editable.of(!disabled)]),
          EditorView.updateListener.of(update => {
            if (update.docChanged) onChangeRef.current(update.state.doc.toString());
            if (update.docChanged || update.selectionSet) {
              const pos = update.state.selection.main.head;
              const line = update.state.doc.lineAt(pos);
              onCursorChangeRef.current({ line: line.number, column: pos - line.from + 1 });
            }
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => { view.destroy(); viewRef.current = null; };
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (value !== current) view.dispatch({ changes: { from: 0, to: current.length, insert: value || '' } });
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({ effects: languageCompartmentRef.current.reconfigure(languageExtension(mode)) });
  }, [mode]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: editableCompartmentRef.current.reconfigure([EditorState.readOnly.of(!!disabled), EditorView.editable.of(!disabled)]),
    });
  }, [disabled]);

  return <div className="code-editor-host" ref={hostRef}></div>;
}

function App() {
  // Auth is now cookie-based (HttpOnly bpanel_session). The SPA does not see
  // the JWT at all. We track only whether the user is authenticated in memory.
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [standaloneEditor] = useState(() => editorParamsFromLocation());
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [needsTwoFactor, setNeedsTwoFactor] = useState(false);
  const [page, setPage] = useState('dashboard');
  const [domain, setDomain] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [wpAdminUser, setWpAdminUser] = useState('admin');
  const [wpAdminPassword, setWpAdminPassword] = useState('');
  const [phpVersion, setPhpVersion] = useState('8.3');
  const [siteType, setSiteType] = useState('wordpress');
  const [installSslAfterCreate, setInstallSslAfterCreate] = useState(false);
  const [installWordPress, setInstallWordPress] = useState(true);
  const [nginxCustomEditing, setNginxCustomEditing] = useState(null); // {id, domain, content}
  const [websites, setWebsites] = useState([]);
  const [databases, setDatabases] = useState([]);
  const [newDatabase, setNewDatabase] = useState({ website_id: '', db_name: '' });
  const [users, setUsers] = useState([]);
  const [resourceUsage, setResourceUsage] = useState(null);
  const [serviceStates, setServiceStates] = useState({});
  const [backups, setBackups] = useState([]);
  const [userBackups, setUserBackups] = useState([]);
  const [restoreBackups, setRestoreBackups] = useState([]);
  const [restoreBackupDir, setRestoreBackupDir] = useState('');
  const [selectedBackupUserId, setSelectedBackupUserId] = useState('');
  const [backupSchedules, setBackupSchedules] = useState([]);
  const [newBackupSchedule, setNewBackupSchedule] = useState({ user_ids: [], all_users: false, schedule: '0 2 * * *', target_id: '', retention: 7 });
  const [sftpTargets, setSftpTargets] = useState([]);
  const [selectedSftpTargetId, setSelectedSftpTargetId] = useState('');
  const [newSftpTarget, setNewSftpTarget] = useState({ name: '', host: '', port: 22, username: '', password: '', private_key: '', remote_path: '/backups/bpanel' });
  const [selectedWebsiteId, setSelectedWebsiteId] = useState(() => standaloneEditor?.websiteId || '');
  const [cronSchedule, setCronSchedule] = useState('0 2 * * *');
  const [cronCommand, setCronCommand] = useState('wp cron event run --due-now --allow-root');
  const [filePath, setFilePath] = useState(() => standaloneEditor?.path || 'public/index.html');
  const [fileListPath, setFileListPath] = useState('public');
  const [fileUploadDir, setFileUploadDir] = useState('public');
  const [files, setFiles] = useState([]);
  const [fileContent, setFileContent] = useState('');
  const [selectedFilePaths, setSelectedFilePaths] = useState([]);
  const [archiveFormat, setArchiveFormat] = useState('zip');
  const [editorCursor, setEditorCursor] = useState({ line: 1, column: 1 });
  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'end_user', website_limit: 5, storage_limit_mb: 1024 });
  const [phpConfig, setPhpConfig] = useState({ php_version: '8.3', display_errors: 'Off', max_execution_time: 300, max_input_time: 600, max_input_vars: 10000, memory_limit: '512M', post_max_size: '1024M', upload_max_filesize: '1024M' });
  const [firewallStatus, setFirewallStatus] = useState(null);
  const [firewallPort, setFirewallPort] = useState('80');
  const [firewallProtocol, setFirewallProtocol] = useState('tcp');
  const [firewallAllowIp, setFirewallAllowIp] = useState('');
  const [firewallAllowPort, setFirewallAllowPort] = useState('');
  const [firewallAllowProtocol, setFirewallAllowProtocol] = useState('tcp');
  const [firewallBlockIp, setFirewallBlockIp] = useState('');
  const [firewallBlockPort, setFirewallBlockPort] = useState('');
  const [firewallBlockProtocol, setFirewallBlockProtocol] = useState('tcp');
  const [firewallDeleteNumber, setFirewallDeleteNumber] = useState('');
  const [websitePhpVersions, setWebsitePhpVersions] = useState({});
  const [assignUserId, setAssignUserId] = useState('');
  const [assignWebsiteId, setAssignWebsiteId] = useState('');
  const [twoFactorStatus, setTwoFactorStatus] = useState(null);
  const [twoFactorSetup, setTwoFactorSetup] = useState(null);
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [panelSettings, setPanelSettings] = useState({ app_name: 'BPanel', panel_url: '', logo_url: '', favicon_url: '/favicon.png', ssl_enabled: false });
  const [panelSettingsForm, setPanelSettingsForm] = useState({ app_name: 'BPanel', panel_url: '' });
  const [panelLogoFile, setPanelLogoFile] = useState(null);
  const [panelFaviconFile, setPanelFaviconFile] = useState(null);
  const [panelSslEmail, setPanelSslEmail] = useState('');
  const [updatesStatus, setUpdatesStatus] = useState(null);
  const [osAutoUpdate, setOsAutoUpdate] = useState({ enabled: true, mode: 'security', auto_reboot: false });
  const [panelAutoUpdate, setPanelAutoUpdate] = useState({ enabled: true, time: '03:30' });
  const [wafStatus, setWafStatus] = useState(null);
  const noticeTimer = useRef(null);

  // Auto-dismiss notices after 6 seconds
  useEffect(() => {
    if (notice) {
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
      noticeTimer.current = setTimeout(() => setNotice(''), 6000);
    }
    return () => { if (noticeTimer.current) clearTimeout(noticeTimer.current); };
  }, [notice]);

  function readCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/[$()*+./?[\\\]^{|}]/g, '\\$&') + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : '';
  }

  function clearSession(message = 'Your session expired. Please log in again.') {
    // Old localStorage token from a previous deploy: nuke it for safety.
    try { localStorage.removeItem('token'); } catch {}
    setIsAuthenticated(false);
    setCurrentUser(null);
    setNeedsTwoFactor(false);
    setOtpCode('');
    setWebsites([]);
    setDatabases([]);
    setUsers([]);
    setResourceUsage(null);
    setServiceStates({});
    setBackups([]);
    setUserBackups([]);
    setRestoreBackups([]);
    setRestoreBackupDir('');
    setSelectedBackupUserId('');
    setBackupSchedules([]);
    setSftpTargets([]);
    setSelectedSftpTargetId('');
    setTwoFactorStatus(null);
    setTwoFactorSetup(null);
    setTwoFactorCode('');
    setUpdatesStatus(null);
    setWafStatus(null);
    setSelectedWebsiteId('');
    setMobileMenuOpen(false);
    setPage('dashboard');
    setError('');
    setNotice(message);
  }

  function handleAuthExpired(status, detail = '') {
    if (status === 401 || detail === 'Could not validate credentials' || detail === 'Not authenticated') {
      clearSession();
      return true;
    }
    return false;
  }

  async function request(path, options = {}, label = '') {
    try {
      setError('');
      if (label) setLoading(label);
      const method = (options.method || 'GET').toUpperCase();
      const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
      const headers = isFormData ? { ...(options.headers || {}) } : {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      };
      // CSRF: echo the bpanel_csrf cookie back in a header for mutating
      // requests. The backend rejects mismatches when the request was
      // authenticated via cookie.
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const csrf = readCookie('bpanel_csrf');
        if (csrf) headers['X-CSRF-Token'] = csrf;
      }
      const res = await fetch(`${API}${path}`, {
        ...options,
        credentials: 'include',
        headers,
      });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text || `HTTP ${res.status}` }; }
      if (!res.ok && handleAuthExpired(res.status, data.detail)) return null;
      if (!res.ok) setError(data.detail || `Request failed with status ${res.status}`);
      if (res.ok && data?.message) setNotice(data.message);
      return res.ok ? data : null;
    } catch (err) {
      setError(`Cannot connect to the ${panelSettings.app_name || 'BPanel'} API at ${API}. Check bpanel-api and the panel port.`);
      return null;
    } finally {
      if (label) setLoading('');
    }
  }

  async function login() {
    try {
      setError('');
      setLoading('Logging in...');
      const body = new URLSearchParams({ username, password });
      if (needsTwoFactor || otpCode) body.set('otp', otpCode);
      const res = await fetch(`${API}/auth/login`, {
        method: 'POST',
        body,
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.requires_2fa) {
        setNeedsTwoFactor(true);
        setNotice('Enter your authentication code.');
      } else if (res.ok && data.access_token) {
        // Don't keep the token anywhere: the HttpOnly cookie just got set by
        // the response. JS code MUST NOT touch the JWT.
        setIsAuthenticated(true);
        setNeedsTwoFactor(false);
        setOtpCode('');
        setNotice('Login successful.');
        await loadCurrentUser();
      } else {
        setError(data.detail || `Login failed with status ${res.status}`);
      }
    } catch (err) {
      setError(`Cannot connect to the ${panelSettings.app_name || 'BPanel'} API at ${API}. Check bpanel-api and the panel port.`);
    } finally {
      setLoading('');
    }
  }

  async function logout() {
    try {
      // Best-effort server logout: clears cookies and bumps token_version.
      await fetch(`${API}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: (() => {
          const csrf = readCookie('bpanel_csrf');
          return csrf ? { 'X-CSRF-Token': csrf } : {};
        })(),
      });
    } catch {}
    clearSession('Logged out.');
  }

  async function loadCurrentUser() {
    try {
      const res = await fetch(`${API}/users/me`, { credentials: 'include' });
      if (!res.ok) {
        if (res.status === 401) clearSession('Session expired.');
        return;
      }
      const data = await res.json();
      setCurrentUser(data);
      setIsAuthenticated(true);
    } catch {
      setCurrentUser(null);
    }
  }

  async function loadPanelSettings() {
    try {
      const res = await fetch(`${API}/panel-settings/public`, { credentials: 'include' });
      if (!res.ok) return null;
      const data = await res.json();
      const panelUrl = data.panel_url || `${window.location.protocol}//${window.location.host}`;
      setPanelSettings(data);
      setPanelSettingsForm({ app_name: data.app_name || 'BPanel', panel_url: panelUrl });
      return data;
    } catch {
      return null;
    }
  }

  async function savePanelSettings() {
    const data = await request('/panel-settings', {
      method: 'PATCH',
      body: JSON.stringify(panelSettingsForm),
    }, 'Saving panel settings...');
    if (data) {
      setPanelSettings(data);
      setPanelSettingsForm({ app_name: data.app_name || 'BPanel', panel_url: data.panel_url || `${window.location.protocol}//${window.location.host}` });
      setNotice('Panel settings updated. The panel may restart if the URL changed.');
    }
  }

  async function uploadPanelAsset(kind) {
    const file = kind === 'logo' ? panelLogoFile : panelFaviconFile;
    if (!file) return;
    const body = new FormData();
    body.append('file', file);
    const data = await request(`/panel-settings/${kind}`, { method: 'POST', body }, `Uploading ${kind}...`);
    if (data) {
      setPanelSettings(data);
      setPanelSettingsForm({ app_name: data.app_name || 'BPanel', panel_url: data.panel_url || `${window.location.protocol}//${window.location.host}` });
      if (kind === 'logo') setPanelLogoFile(null);
      if (kind === 'favicon') setPanelFaviconFile(null);
    }
  }

  async function installPanelSsl() {
    const data = await request('/panel-settings/ssl', {
      method: 'POST',
      body: JSON.stringify({ panel_url: panelSettingsForm.panel_url, email: panelSslEmail }),
    }, 'Installing panel SSL...');
    if (data) {
      setPanelSettings(data);
      setPanelSettingsForm({ app_name: data.app_name || 'BPanel', panel_url: data.panel_url || `${window.location.protocol}//${window.location.host}` });
      setNotice(data.message || 'Panel SSL installed. The panel may restart in a moment.');
    }
  }

  function brandInitials(value = panelSettings.app_name) {
    const words = String(value || 'BPanel').trim().split(/\s+/).filter(Boolean);
    const initials = words.length > 1 ? `${words[0][0]}${words[1][0]}` : words[0]?.slice(0, 2);
    return (initials || 'BP').toUpperCase();
  }

  function renderBrandMark(extraClass = '') {
    const classes = ['brand-mark', panelSettings.logo_url ? 'has-logo' : '', extraClass].filter(Boolean).join(' ');
    return <span className={classes}>{panelSettings.logo_url ? <img src={panelSettings.logo_url} alt="" /> : brandInitials()}</span>;
  }

  // Bootstrap: try to restore session from the HttpOnly cookie (set previously
  // and still valid). If /users/me returns 200 we are authenticated.
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/users/me`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setCurrentUser(data);
          setIsAuthenticated(true);
        }
      } catch {}
      finally { setBootstrapping(false); }
    })();
  }, []);

  useEffect(() => { loadPanelSettings(); }, []);

  useEffect(() => {
    const appName = panelSettings.app_name || 'BPanel';
    document.title = appName;
    let link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.href = panelSettings.favicon_url || '/favicon.png';
  }, [panelSettings]);

  useEffect(() => {
    if (!panelSslEmail && currentUser?.email) setPanelSslEmail(currentUser.email);
  }, [currentUser?.email, panelSslEmail]);

  async function refreshAll() {
    await loadCurrentUser();
    const siteData = await request('/websites');
    if (siteData) {
      setWebsites(siteData);
      if (!selectedWebsiteId && siteData[0]) setSelectedWebsiteId(String(siteData[0].id));
      if (!newDatabase.website_id && siteData[0]) setNewDatabase(prev => ({ ...prev, website_id: String(siteData[0].id) }));
    }
    const dbData = await request('/databases');
    if (dbData) setDatabases(dbData);
  }

  async function loadUsers() {
    const data = await request('/users');
    if (data) {
      setUsers(data);
      if (!selectedBackupUserId && data[0]) setSelectedBackupUserId(String(data[0].id));
      setNewBackupSchedule(prev => (!prev.all_users && (!prev.user_ids || prev.user_ids.length === 0) && data[0]) ? ({ ...prev, user_ids: [String(data[0].id)] }) : prev);
    }
  }

  async function loadResourceUsage() {
    const data = await request('/services/resource-usage');
    if (data) setResourceUsage(data);
  }

  async function createUser() {
    const data = await request('/users', { method: 'POST', body: JSON.stringify({ ...newUser, website_limit: Number(newUser.website_limit), storage_limit_mb: Number(newUser.storage_limit_mb) }) }, 'Creating user...');
    if (data) {
      setNotice(`Created user ${data.username}`);
      setNewUser({ username: '', email: '', password: '', role: 'end_user', website_limit: 5, storage_limit_mb: 1024 });
      await loadUsers();
    }
  }

  async function changeUserPassword(user) {
    const password = prompt(`Enter a new password for ${user.username} (minimum 12 characters):`);
    if (!password) return;
    if (password.length < 12) { setError('Password must be at least 12 characters.'); return; }
    const data = await request(`/users/${user.id}/password`, { method: 'POST', body: JSON.stringify({ password }) }, `Changing password for ${user.username}...`);
    if (data?.message) setNotice(data.message);
  }

  async function deletePanelUser(user) {
    if (!user || user.id === currentUser?.id) return;
    if (!confirm(`Delete panel user ${user.username} and permanently delete all owned websites, files, databases, and Linux user data?`)) return;
    const data = await request(`/users/${user.id}`, { method: 'DELETE' }, `Deleting user ${user.username}...`);
    if (data) {
      const count = data.deleted_websites?.length || 0;
      setNotice(`Deleted user ${user.username}${count ? ` and ${count} website(s)` : ''}`);
      await loadUsers();
      await loadWebsites();
    }
  }

  async function quickLoginUser(user) {
    if (!user) return;
    if (!confirm(`Login as ${user.username}? New websites will belong to this user.`)) return;
    const data = await request(`/auth/impersonate/${user.id}`, { method: 'POST' }, `Logging in as ${user.username}...`);
    if (data?.access_token) {
      setNotice(`Logged in as ${user.username}.`);
      await loadCurrentUser();
      setPage('websites');
      await refreshAll();
    }
  }

  async function changeMyPassword() { if (!currentUser) return; await changeUserPassword(currentUser); }

  async function loadTwoFactorStatus() {
    const data = await request('/auth/2fa/status');
    if (data) setTwoFactorStatus(data);
  }

  async function setupTwoFactorAuth() {
    const data = await request('/auth/2fa/setup', { method: 'POST' }, 'Preparing 2FA...');
    if (data) {
      setTwoFactorSetup(data);
      setTwoFactorStatus({ enabled: false });
    }
  }

  async function enableTwoFactorAuth() {
    const data = await request('/auth/2fa/enable', { method: 'POST', body: JSON.stringify({ code: twoFactorCode }) }, 'Enabling 2FA...');
    if (data) {
      setTwoFactorStatus(data);
      setTwoFactorSetup(null);
      setTwoFactorCode('');
      await loadCurrentUser();
      setNotice('2FA enabled.');
    }
  }

  async function disableTwoFactorAuth() {
    const data = await request('/auth/2fa/disable', { method: 'POST', body: JSON.stringify({ code: twoFactorCode }) }, 'Disabling 2FA...');
    if (data) {
      setTwoFactorStatus(data);
      setTwoFactorCode('');
      await loadCurrentUser();
      setNotice('2FA disabled.');
    }
  }

  async function resetUserTwoFactor(user) {
    if (!confirm(`Reset 2FA for ${user.username}?`)) return;
    const data = await request(`/users/${user.id}/2fa/reset`, { method: 'POST' }, `Resetting 2FA for ${user.username}...`);
    if (data?.message) { setNotice(data.message); await loadUsers(); }
  }

  async function assignDomainToUser() {
    if (!assignWebsiteId || !assignUserId) return;
    const data = await request(`/websites/${assignWebsiteId}`, { method: 'PATCH', body: JSON.stringify({ owner_id: Number(assignUserId) }) }, 'Assigning domain to user...');
    if (data) { setNotice(`Assigned domain ${data.domain} to user ID ${assignUserId}`); await refreshAll(); }
  }

  async function createWordPress() {
    if (!domain) { setError('Please enter a domain name.'); return; }
    const installWp = siteType === 'wordpress' && installWordPress;
    const body = {
      domain,
      php_version: phpVersion,
      app_type: siteType,
      install_wordpress: installWp,
      title: domain,
      admin_user: wpAdminUser,
      admin_email: adminEmail || `admin@${domain}`,
      admin_password: wpAdminPassword || (installWp ? 'StrongPass123!' : ''),
    };
    const data = await request('/websites', { method: 'POST', body: JSON.stringify(body) },
      installWp ? 'Creating WordPress website...' : 'Creating website...');
    if (data) {
      if (installWp) {
        setNotice(`Created WordPress site: https://${domain}\nAdmin: ${wpAdminUser} | Password: ${wpAdminPassword || 'StrongPass123!'}`);
      } else {
        setNotice(`Created site ${domain}. Upload your files to public/ folder.`);
      }
      if (installSslAfterCreate) await enableSsl(data.id);
      refreshAll();
    }
  }

  async function deleteWebsite(id) {
    if (!confirm('Delete this website including files, vhost, and database?')) return;
    const data = await request(`/websites/${id}?delete_files=true&delete_database=true`, { method: 'DELETE' }, 'Deleting website...');
    if (data) refreshAll();
  }

  async function enableSsl(id) {
    const data = await request(`/websites/${id}/ssl`, { method: 'POST' }, "Installing Let's Encrypt SSL...");
    if (data) refreshAll();
  }

  async function openNginxCustom(site) {
    const data = await request(`/websites/${site.id}/nginx-config`, {}, 'Loading Nginx config...');
    if (data !== null) {
      setNginxCustomEditing({ id: site.id, domain: site.domain, content: data?.nginx_config || '' });
    }
  }

  async function saveNginxCustom() {
    if (!nginxCustomEditing) return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-config`, {
      method: 'PUT',
      body: JSON.stringify({ nginx_config: nginxCustomEditing.content }),
    }, 'Applying Nginx config and reloading...');
    if (data) {
      setNotice(`Updated Nginx config for ${nginxCustomEditing.domain}`);
      setNginxCustomEditing(null);
      refreshAll();
    }
  }

  async function toggleWebsiteWaf(site) {
    const next = !site.waf_enabled;
    const data = await request(`/websites/${site.id}/waf`, {
      method: 'PATCH',
      body: JSON.stringify({ waf_enabled: next }),
    }, `${next ? 'Enabling' : 'Disabling'} WAF for ${site.domain}...`);
    if (data) {
      setNotice(`${next ? 'Enabled' : 'Disabled'} WAF for ${site.domain}.`);
      await refreshAll();
    }
  }

  async function fixWordPressPermissions(id) {
    const data = await request(`/maintenance/wordpress/${id}/fix-permissions`, { method: 'POST' }, 'Fixing permissions...');
    if (data?.message) setNotice(data.message);
  }

  async function fixNginxSecurity(id) {
    const data = await request(`/websites/${id}/fix-nginx-security`, { method: 'POST' }, 'Rewriting Nginx security template...');
    if (data?.message) setNotice(data.message);
  }

  async function changeWebsitePhpVersion(site) {
    const next = websitePhpVersions[site.id] || site.php_version || '8.3';
    if (next === site.php_version) return;
    const data = await request(`/websites/${site.id}`, { method: 'PATCH', body: JSON.stringify({ php_version: next }) }, `Changing ${site.domain} to PHP ${next}...`);
    if (data) { setNotice(`Changed ${site.domain} to PHP ${next} and reloaded Nginx.`); await refreshAll(); }
  }

  async function changeDbPassword(id) {
    const newPass = prompt('Enter a new database password, minimum 12 characters:');
    if (!newPass) return;
    await request(`/databases/${id}/password`, { method: 'POST', body: JSON.stringify({ password: newPass }) }, 'Changing database password...');
  }

  async function createDatabase() {
    if (!newDatabase.website_id) { setError('Please select a website.'); return; }
    const body = {
      website_id: Number(newDatabase.website_id),
      db_name: newDatabase.db_name.trim() || null,
    };
    const data = await request('/databases', { method: 'POST', body: JSON.stringify(body) }, 'Creating database...');
    if (data) {
      setNotice(`Created database ${data.db_name}\nUser: ${data.db_user}${data.db_password ? ` | Password: ${data.db_password}` : ''}`);
      setNewDatabase(prev => ({ ...prev, db_name: '' }));
      await refreshAll();
    }
  }

  async function addCron() {
    await request('/maintenance/cron', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), schedule: cronSchedule, command: cronCommand }) }, 'Adding cron job...');
  }

  async function deleteCron() {
    const index = Number(prompt('Enter the cron index to delete, starting from 0:'));
    if (Number.isNaN(index)) return;
    await request('/maintenance/cron', { method: 'DELETE', body: JSON.stringify({ website_id: Number(selectedWebsiteId), index }) }, 'Deleting cron job...');
  }

  async function listFiles(path = fileListPath, websiteId = selectedWebsiteId) {
    if (!websiteId) return;
    const data = await request(`/maintenance/files/${websiteId}?path=${encodeURIComponent(path)}`, {}, 'Loading file list...');
    if (data?.items) { setFiles(data.items); setFileListPath(path); setFileUploadDir(path || 'public'); setSelectedFilePaths([]); }
  }

  async function readFile(pathOverride = filePath, websiteId = selectedWebsiteId) {
    const targetPath = pathOverride || filePath;
    if (!websiteId || !targetPath) return;
    if (pathOverride) setFilePath(pathOverride);
    const data = await request(`/maintenance/files/${websiteId}/read?path=${encodeURIComponent(targetPath)}`, {}, 'Reading file...');
    if (data?.content !== undefined) {
      setFileContent(data.content);
      setEditorCursor({ line: 1, column: 1 });
    }
  }

  async function writeFile() {
    const data = await request('/maintenance/files/write', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: filePath, content: fileContent }) }, 'Saving file...');
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function deleteFileAction(path) {
    if (!confirm(`Delete file ${path}?`)) return;
    const data = await request('/maintenance/files/delete', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), paths: [path] }) }, 'Deleting file...');
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function downloadFile(path) {
    if (!selectedWebsiteId || !path) return;
    try {
      setError(''); setLoading('Downloading file...');
      const res = await fetch(`${API}/maintenance/files/${selectedWebsiteId}/download?path=${encodeURIComponent(path)}`, { credentials: 'include' });
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Download failed.'); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = path.split('/').pop() || 'download';
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
    } catch (err) { setError('File download failed.'); }
    finally { setLoading(''); }
  }

  function fileEditorUrl(websiteId, path) {
    const url = new URL(window.location.href);
    url.search = '';
    url.hash = '';
    url.searchParams.set('view', 'editor');
    url.searchParams.set('website_id', String(websiteId));
    url.searchParams.set('path', path);
    return url.toString();
  }

  function openFileEditorTab(path, websiteId = selectedWebsiteId) {
    if (!websiteId || !path) return;
    window.open(fileEditorUrl(websiteId, path), '_blank', 'noopener,noreferrer');
  }

  async function makeFileDirectory() {
    if (!selectedWebsiteId) return;
    const name = prompt('Folder name:');
    if (!name) return;
    const data = await request('/maintenance/files/mkdir', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: fileListPath || 'public', name }) }, 'Creating folder...');
    if (data) await listFiles(fileListPath);
  }

  async function renameFileItem(item) {
    if (!item) return;
    const newName = prompt('New name:', item.name);
    if (!newName || newName === item.name) return;
    const data = await request('/maintenance/files/rename', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: item.path, new_name: newName }) }, 'Renaming...');
    if (data) await listFiles(fileListPath);
  }

  async function deleteSelectedFiles() {
    if (selectedFilePaths.length === 0) return;
    if (!confirm(`Delete ${selectedFilePaths.length} selected item(s)?`)) return;
    const data = await request('/maintenance/files/delete', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), paths: selectedFilePaths }) }, 'Deleting selected files...');
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function archiveSelectedFiles() {
    if (selectedFilePaths.length === 0) return;
    const ext = archiveFormat === 'tar.gz' ? 'tar.gz' : 'zip';
    const outputName = prompt('Archive file name:', `archive-${Date.now()}.${ext}`);
    if (!outputName) return;
    const data = await request('/maintenance/files/archive', {
      method: 'POST',
      body: JSON.stringify({ website_id: Number(selectedWebsiteId), base_path: fileListPath || 'public', paths: selectedFilePaths, output_name: outputName, format: archiveFormat }),
    }, 'Creating archive...');
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function extractArchiveFile(path) {
    if (!path) return;
    const destination = prompt('Extract to folder:', fileListPath || 'public');
    if (destination === null) return;
    const data = await request('/maintenance/files/extract', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), archive_path: path, destination_path: destination || fileListPath || 'public' }) }, 'Extracting archive...');
    if (data) { await listFiles(destination || fileListPath); await loadCurrentUser(); }
  }

  async function openWebsiteFileManager(site) {
    setSelectedWebsiteId(String(site.id));
    setPage('files');
    setFileListPath('public');
    setFileUploadDir('public');
    await listFiles('public', site.id);
  }

  async function uploadSiteFile(file) {
    if (!file) return;
    if (!selectedWebsiteId) { setError('Please select a website first.'); return; }
    const uploadDir = fileUploadDir.trim() || 'public';
    const form = new FormData();
    form.append('file', file);
    try {
      setError('');
      setLoading('Uploading file...');
      const csrfToken = readCookie('bpanel_csrf');
      const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
      const res = await fetch(`${API}/maintenance/files/${selectedWebsiteId}/upload?path=${encodeURIComponent(uploadDir)}`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: form,
      });
      const responseText = await res.text();
      let data;
      try { data = responseText ? JSON.parse(responseText) : {}; } catch { data = { detail: responseText || `HTTP ${res.status}` }; }
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Upload failed.'); return; }
      setNotice(`Uploaded ${file.name} to ${uploadDir}.`);
      if (String(fileListPath || 'public') === uploadDir) await listFiles(uploadDir);
      await loadCurrentUser();
    } catch (err) { setError('File upload failed.'); }
    finally { setLoading(''); }
  }

  async function createBackup() {
    const data = await request('/maintenance/backup', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId) }) }, 'Creating backup...');
    if (data?.backup_file) { setNotice(`Created backup: ${data.backup_file}`); await listBackups(); }
  }

  async function listBackups() {
    const data = await request(`/maintenance/backups/${selectedWebsiteId}`);
    if (data?.items) setBackups(data.items);
  }

  async function listUserBackups(userId = selectedBackupUserId) {
    if (!userId) return;
    const data = await request(`/maintenance/user-backups/${userId}`);
    if (data?.items) setUserBackups(data.items);
  }

  async function createUserBackup() {
    if (!selectedBackupUserId) return;
    const body = {
      user_id: Number(selectedBackupUserId),
      target_id: selectedSftpTargetId ? Number(selectedSftpTargetId) : null,
    };
    const data = await request('/maintenance/user-backup', { method: 'POST', body: JSON.stringify(body) }, 'Creating full user backup...');
    if (data?.backup_file) {
      setNotice(data.remote_file ? `Full user backup uploaded: ${data.remote_file}` : `Created full user backup: ${data.backup_file}`);
      await listUserBackups();
    }
  }

  async function loadBackupSchedules() {
    const data = await request('/maintenance/backup-schedules');
    if (data) setBackupSchedules(data);
  }

  async function loadRestoreBackups() {
    const data = await request('/maintenance/user-restore-backups');
    if (data?.items) setRestoreBackups(data.items);
    if (data?.directory) setRestoreBackupDir(data.directory);
  }

  async function createBackupSchedule() {
    const selectedUserIds = (newBackupSchedule.user_ids || []).map(Number).filter(Boolean);
    if (!newBackupSchedule.all_users && selectedUserIds.length === 0) return;
    const body = {
      user_id: selectedUserIds[0] || null,
      user_ids: newBackupSchedule.all_users ? [] : selectedUserIds,
      all_users: !!newBackupSchedule.all_users,
      schedule: newBackupSchedule.schedule,
      target_id: newBackupSchedule.target_id ? Number(newBackupSchedule.target_id) : null,
      retention: Number(newBackupSchedule.retention || 7),
      is_active: true,
    };
    const data = await request('/maintenance/backup-schedules', { method: 'POST', body: JSON.stringify(body) }, 'Saving backup schedule...');
    if (data) {
      setNotice('Backup schedule saved.');
      await loadBackupSchedules();
    }
  }

  async function deleteBackupSchedule(id) {
    if (!confirm('Delete this backup schedule?')) return;
    const data = await request(`/maintenance/backup-schedules/${id}`, { method: 'DELETE' }, 'Deleting backup schedule...');
    if (data) await loadBackupSchedules();
  }

  async function loadSftpTargets() {
    const data = await request('/maintenance/sftp-targets');
    if (data) {
      setSftpTargets(data);
      if (!selectedSftpTargetId && data[0]) setSelectedSftpTargetId(String(data[0].id));
    }
  }

  async function createSftpTarget() {
    const body = {
      ...newSftpTarget,
      port: Number(newSftpTarget.port || 22),
      password: newSftpTarget.password || null,
      private_key: newSftpTarget.private_key || null,
    };
    const data = await request('/maintenance/sftp-targets', { method: 'POST', body: JSON.stringify(body) }, 'Saving SFTP target...');
    if (data) {
      setNotice(`Saved SFTP target ${data.name}`);
      setNewSftpTarget({ name: '', host: '', port: 22, username: '', password: '', private_key: '', remote_path: '/backups/bpanel' });
      await loadSftpTargets();
    }
  }

  async function deleteSftpTarget(id) {
    if (!confirm('Delete this SFTP target?')) return;
    const data = await request(`/maintenance/sftp-targets/${id}`, { method: 'DELETE' }, 'Deleting SFTP target...');
    if (data) await loadSftpTargets();
  }

  async function createSftpBackup() {
    if (!selectedWebsiteId || !selectedSftpTargetId) return;
    const data = await request('/maintenance/backup-sftp', {
      method: 'POST',
      body: JSON.stringify({ website_id: Number(selectedWebsiteId), target_id: Number(selectedSftpTargetId) }),
    }, 'Creating and uploading SFTP backup...');
    if (data?.remote_file) {
      setNotice(`SFTP backup uploaded: ${data.remote_file}`);
      await listBackups();
    }
  }

  async function restoreBackup(file) {
    if (!confirm(`Restore this backup to the current website?\n${file}`)) return;
    await request('/maintenance/restore', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), backup_file: file }) }, 'Restoring backup...');
  }

  async function downloadBackup(file) {
    if (!selectedWebsiteId) return;
    try {
      setError(''); setLoading('Downloading backup...');
      const res = await fetch(`${API}/maintenance/backups/${selectedWebsiteId}/download?backup_file=${encodeURIComponent(file)}`, { credentials: 'include' });
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Download failed.'); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = file.split('/').pop() || 'backup.tar.gz';
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
      setNotice('Backup downloaded.');
    } catch (err) { setError('Backup download failed.'); }
    finally { setLoading(''); }
  }

  async function downloadUserBackup(file) {
    try {
      setError(''); setLoading('Downloading full user backup...');
      const res = await fetch(`${API}/maintenance/user-backups-download?backup_file=${encodeURIComponent(file)}`, { credentials: 'include' });
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Download failed.'); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = file.split('/').pop() || 'user-backup.tar.gz';
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
      setNotice('Full user backup downloaded.');
    } catch (err) { setError('Full user backup download failed.'); }
    finally { setLoading(''); }
  }

  async function restoreUserBackup(file) {
    if (!confirm(`Restore this full user backup? Missing panel user and websites will be created.\n${file}`)) return;
    const data = await request('/maintenance/user-restore', { method: 'POST', body: JSON.stringify({ backup_file: file }) }, 'Restoring full user backup...');
    if (data) {
      setNotice(`Restored user ${data.username}. Websites: ${data.websites?.length || 0}`);
      await refreshAll();
      await loadUsers();
      await listUserBackups();
      await loadRestoreBackups();
    }
  }

  async function deleteUserBackup(file) {
    if (!confirm(`Delete this full user backup?\n${file}`)) return;
    const data = await request(`/maintenance/user-backups?backup_file=${encodeURIComponent(file)}`, { method: 'DELETE' }, 'Deleting full user backup...');
    if (data) {
      await listUserBackups();
      await loadRestoreBackups();
    }
  }

  async function deleteRestoreBackup(file) {
    if (!confirm(`Delete this restore backup?\n${file}`)) return;
    const data = await request(`/maintenance/user-restore-backups?backup_file=${encodeURIComponent(file)}`, { method: 'DELETE' }, 'Deleting restore backup...');
    if (data) {
      await loadRestoreBackups();
      await listUserBackups();
    }
  }

  async function uploadUserBackups(files) {
    const selectedFiles = Array.from(files || []);
    if (selectedFiles.length === 0) return;
    const form = new FormData();
    selectedFiles.forEach(file => form.append('files', file));
    try {
      setError(''); setLoading('Uploading full user backups...');
      const csrfToken = readCookie('bpanel_csrf');
      const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
      const res = await fetch(`${API}/maintenance/user-restore-backups/upload`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: form,
      });
      const responseText = await res.text();
      let data;
      try { data = responseText ? JSON.parse(responseText) : {}; } catch { data = { detail: responseText || `HTTP ${res.status}` }; }
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Upload failed.'); return; }
      setNotice(`Uploaded ${data.items?.length || selectedFiles.length} full user backup file(s).`);
      await loadRestoreBackups();
      await listUserBackups();
    } catch (err) { setError('Full user backup upload failed.'); }
    finally { setLoading(''); }
  }

  async function openPhpMyAdmin(databaseId) {
    try {
      setError(''); setLoading('Opening phpMyAdmin...');
      const csrfToken = readCookie('bpanel_csrf');
      const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
      const res = await fetch(`${API}/databases/${databaseId}/phpmyadmin-sso`, {
        method: 'POST',
        credentials: 'include',
        headers,
      });
      const data = await res.json().catch(() => ({}));
      if (handleAuthExpired(res.status, data.detail)) return;
      if (!res.ok || !data.url) { setError(data.detail || 'Cannot open phpMyAdmin.'); return; }
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } catch (err) { setError('Cannot open phpMyAdmin.'); }
    finally { setLoading(''); }
  }

  async function downloadDatabase(databaseId, databaseName) {
    try {
      setError(''); setLoading('Downloading database...');
      const res = await fetch(`${API}/databases/${databaseId}/download`, { credentials: 'include' });
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Download failed.'); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `${databaseName || 'database'}.sql`;
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
      setNotice('Database SQL downloaded.');
    } catch (err) { setError('Database download failed.'); }
    finally { setLoading(''); }
  }

  async function deleteBackup(file) {
    if (!confirm(`Delete this backup?\n${file}`)) return;
    const data = await request(`/maintenance/backups/${selectedWebsiteId}?backup_file=${encodeURIComponent(file)}`, { method: 'DELETE' }, 'Deleting backup...');
    if (data) await listBackups();
  }

  async function uploadBackup(file) {
    if (!file || !selectedWebsiteId) return;
    const form = new FormData();
    form.append('file', file);
    try {
      setError(''); setLoading('Uploading backup...');
      const csrfToken = readCookie('bpanel_csrf');
      const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
      const res = await fetch(`${API}/maintenance/backups/${selectedWebsiteId}/upload`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: form,
      });
      const responseText = await res.text();
      let data;
      try { data = responseText ? JSON.parse(responseText) : {}; } catch { data = { detail: responseText || `HTTP ${res.status}` }; }
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(data.detail || 'Upload failed.'); return; }
      if (data.backup_file) { setNotice(`Uploaded backup: ${data.backup_file}`); await listBackups(); }
    } catch (err) { setError('Upload backup failed.'); }
    finally { setLoading(''); }
  }

  async function checkService(name) {
    const data = await request('/services/action', { method: 'POST', body: JSON.stringify({ name, action: 'status' }) });
    setServiceStates(prev => ({ ...prev, [name]: data || { stdout: '', stderr: error || 'Cannot check', returncode: 1 } }));
    return data;
  }

  async function checkAllServices() {
    setLoading('Checking services...');
    for (const name of SERVICE_NAMES) { await checkService(name); }
    setLoading('');
  }

  async function runServiceAction(name, action) {
    await request('/services/action', { method: 'POST', body: JSON.stringify({ name, action }) }, `${action} ${name}...`);
    await checkService(name);
  }

  async function loadPhpConfig(version = phpConfig.php_version) {
    const data = await request(`/maintenance/php-config?php_version=${encodeURIComponent(version)}`, {}, 'Loading PHP config...');
    if (data) setPhpConfig(prev => ({ ...prev, ...data, php_version: version }));
  }

  async function updatePhpConfig() {
    const data = await request('/maintenance/php-config', {
      method: 'POST',
      body: JSON.stringify({ ...phpConfig, max_execution_time: Number(phpConfig.max_execution_time), max_input_time: Number(phpConfig.max_input_time), max_input_vars: Number(phpConfig.max_input_vars) }),
    }, 'Updating PHP config...');
    if (data?.target) { setNotice(`Updated PHP config: ${data.target}`); await loadPhpConfig(phpConfig.php_version); }
  }

  async function loadFirewall() {
    const data = await request('/firewall/status', {}, 'Loading firewall...');
    if (data) setFirewallStatus(data);
  }

  async function runFirewallAction(path, options = {}, label = 'Updating firewall...') {
    const data = await request(path, options, label);
    if (data) { setNotice((data.stdout || data.stderr || 'Firewall updated.').trim()); await loadFirewall(); }
  }

  async function enableFirewall() {
    if (!confirm('Enable UFW firewall now? Make sure SSH and web ports are allowed.')) return;
    await runFirewallAction('/firewall/enable', { method: 'POST' }, 'Enabling firewall...');
  }
  async function disableFirewall() {
    if (!confirm('Disable UFW firewall?')) return;
    await runFirewallAction('/firewall/disable', { method: 'POST' }, 'Disabling firewall...');
  }
  async function reloadFirewall() { await runFirewallAction('/firewall/reload', { method: 'POST' }, 'Reloading firewall...'); }
  async function openFirewallPort() { await runFirewallAction('/firewall/allow-port', { method: 'POST', body: JSON.stringify({ port: firewallPort, protocol: firewallProtocol }) }, 'Opening port...'); }
  async function allowFirewallIp() { await runFirewallAction('/firewall/allow-ip', { method: 'POST', body: JSON.stringify({ ip: firewallAllowIp, port: firewallAllowPort || null, protocol: firewallAllowProtocol }) }, 'Allowing IP...'); }
  async function blockFirewallIp() {
    if (!confirm(`Block ${firewallBlockIp || 'this IP'}?`)) return;
    await runFirewallAction('/firewall/block-ip', { method: 'POST', body: JSON.stringify({ ip: firewallBlockIp, port: firewallBlockPort || null, protocol: firewallBlockProtocol }) }, 'Blocking IP...');
  }
  async function deleteFirewallRule() {
    if (!firewallDeleteNumber) return;
    if (!confirm(`Delete UFW rule #${firewallDeleteNumber}?`)) return;
    await runFirewallAction(`/firewall/rules/${encodeURIComponent(firewallDeleteNumber)}`, { method: 'DELETE' }, 'Deleting rule...');
    setFirewallDeleteNumber('');
  }

  async function loadUpdates() {
    const data = await request('/updates/status', {}, 'Loading update status...');
    if (data) setUpdatesStatus(data);
  }

  async function runOsUpdate() {
    if (!confirm('Run apt-get update && apt-get upgrade now?')) return;
    const data = await request('/updates/os/run', { method: 'POST' }, 'Updating OS packages...');
    if (data) { setNotice((data.stdout || data.stderr || 'OS update finished.').trim()); await loadUpdates(); }
  }

  async function saveOsAutoUpdate() {
    const data = await request('/updates/os/auto', { method: 'POST', body: JSON.stringify(osAutoUpdate) }, 'Saving OS auto update...');
    if (data) { setNotice((data.stdout || data.stderr || 'OS auto update saved.').trim()); await loadUpdates(); }
  }

  async function runPanelUpdate() {
    if (!confirm('Update BPanel from GitHub now? The API may restart.')) return;
    const data = await request('/updates/panel/run', { method: 'POST' }, 'Updating BPanel...');
    if (data) setNotice((data.stdout || data.stderr || 'Panel update finished.').trim());
  }

  async function savePanelAutoUpdate() {
    const data = await request('/updates/panel/auto', { method: 'POST', body: JSON.stringify(panelAutoUpdate) }, 'Saving panel auto update...');
    if (data) { setNotice((data.stdout || data.stderr || 'Panel auto update saved.').trim()); await loadUpdates(); }
  }

  async function loadWafStatus() {
    const data = await request('/waf/status', {}, 'Loading WAF status...');
    if (data) setWafStatus(data);
  }

  async function installWaf() {
    const data = await request('/waf/install', { method: 'POST' }, 'Installing WAF engine...');
    if (data) { setNotice((data.stdout || data.stderr || 'WAF installed.').trim()); await loadWafStatus(); }
  }

  async function updateWafRules() {
    const data = await request('/waf/update-rules', { method: 'POST' }, 'Updating WAF rules...');
    if (data) { setNotice((data.stdout || data.stderr || 'WAF rules updated.').trim()); await loadWafStatus(); }
  }

  useEffect(() => {
    if (isAuthenticated) {
      refreshAll();
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated || !standaloneEditor) return;
    setSelectedWebsiteId(standaloneEditor.websiteId);
    setFilePath(standaloneEditor.path);
    readFile(standaloneEditor.path, standaloneEditor.websiteId);
  }, [isAuthenticated, standaloneEditor]);

  useEffect(() => {
    if (!standaloneEditor || !isAuthenticated) return undefined;
    const handler = event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        writeFile();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [standaloneEditor, isAuthenticated, selectedWebsiteId, filePath, fileContent]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'dashboard') return undefined;
    loadResourceUsage();
    const timer = setInterval(loadResourceUsage, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'services') return undefined;
    checkAllServices();
    const timer = setInterval(checkAllServices, 10000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page]);

  useEffect(() => { if (selectedWebsiteId && page === 'backups') listBackups(); }, [selectedWebsiteId, page]);

  useEffect(() => { if (selectedWebsiteId && page === 'files') listFiles('public'); }, [selectedWebsiteId, page]);

  useEffect(() => { if (selectedBackupUserId && page === 'backups') listUserBackups(selectedBackupUserId); }, [selectedBackupUserId, page]);

  useEffect(() => {
    if (isAuthenticated && page === 'users') loadUsers();
    if (isAuthenticated && page === 'php') loadPhpConfig();
    if (isAuthenticated && page === 'firewall') loadFirewall();
    if (isAuthenticated && page === 'security') loadTwoFactorStatus();
    if (isAuthenticated && page === 'settings') loadPanelSettings();
    if (isAuthenticated && page === 'updates' && currentUser?.role === 'admin') loadUpdates();
    if (isAuthenticated && page === 'waf' && currentUser?.role === 'admin') loadWafStatus();
    if (isAuthenticated && page === 'backups' && currentUser?.role === 'admin') { loadUsers(); loadSftpTargets(); loadBackupSchedules(); loadRestoreBackups(); }
  }, [isAuthenticated, page, currentUser?.role]);

  useEffect(() => { setMobileMenuOpen(false); }, [page]);

  const isAdmin = currentUser?.role === 'admin';

  function roleLabel(role) {
    return role === 'admin' ? 'Admin' : 'End user';
  }

  const navItems = [
    ['dashboard', 'Dashboard', Home],
    ['websites', 'Websites', Globe],
    ['ssl', 'SSL', Lock],
    ['databases', 'Database', Database],
    ['cron', 'Cron', Clock],
    ['files', 'File manager', FolderOpen],
    ['backups', 'Backups', Archive],
    ['security', 'Security', Shield],
    ...(isAdmin ? [['php', 'PHP config', Code2]] : []),
    ...(isAdmin ? [['firewall', 'Firewall', Shield]] : []),
    ...(isAdmin ? [['waf', 'WAF', Shield]] : []),
    ...(isAdmin ? [['updates', 'Updates', RefreshCw]] : []),
    ['services', 'Services Status', Server],
    ...(isAdmin ? [['users', 'Panel users', Users]] : []),
    ...(isAdmin ? [['settings', 'Settings', SettingsIcon]] : []),
  ];

  const currentSite = websites.find(site => String(site.id) === String(selectedWebsiteId));
  const activeNavItem = navItems.find(([key]) => key === page) || navItems[0];

  function websiteUrl(site) {
    const value = (site?.domain || '').trim();
    if (/^https?:\/\//i.test(value)) return value;
    return `${site?.ssl_enabled ? 'https' : 'http'}://${value}`;
  }

  function parentFilePath(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    parts.pop();
    return parts.join('/') || 'public';
  }

  function fileBreadcrumbs(path) {
    const parts = String(path || 'public').split('/').filter(Boolean);
    let current = '';
    return parts.map(part => {
      current = current ? `${current}/${part}` : part;
      return { label: part, path: current };
    });
  }

  function isArchiveFile(item) {
    const name = (item?.name || '').toLowerCase();
    return !item?.is_dir && (name.endsWith('.zip') || name.endsWith('.tar.gz') || name.endsWith('.tgz'));
  }

  function isTextEditable(item) {
    if (!item || item.is_dir) return false;
    const name = (item.name || '').toLowerCase();
    return /\.(txt|md|json|css|js|jsx|ts|tsx|html|htm|xml|yml|yaml|ini|conf|log|php)$/.test(name) || !name.includes('.');
  }

  function toggleFileSelection(path) {
    setSelectedFilePaths(prev => prev.includes(path) ? prev.filter(item => item !== path) : [...prev, path]);
  }

  function toggleAllFiles() {
    setSelectedFilePaths(prev => prev.length === files.length ? [] : files.map(item => item.path));
  }

  function editorLanguage(path) {
    const name = String(path || '').toLowerCase();
    if (/\.php\d?$/.test(name) || name.endsWith('.phtml')) return 'PHP';
    if (/\.(js|jsx|ts|tsx)$/.test(name)) return 'JavaScript';
    if (/\.css$/.test(name)) return 'CSS';
    if (/\.html?$/.test(name)) return 'HTML';
    if (/\.json$/.test(name)) return 'JSON';
    if (/\.ya?ml$/.test(name)) return 'YAML';
    if (/\.(conf|ini|env|htaccess)$/.test(name)) return 'Config';
    return 'Text';
  }

  function WebsiteSelect() {
    return <select value={selectedWebsiteId} onChange={e => setSelectedWebsiteId(e.target.value)}>
      <option value="">-- Select website --</option>
      {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
    </select>;
  }

  function EmptyState({ icon: Icon = AlertCircle, message = 'No data yet' }) {
    return <div className="empty-state"><Icon size={40} /><p>{message}</p></div>;
  }

  function formatBytes(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount) || amount < 0) return '--';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = amount;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
    return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
  }

  function formatPercent(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return '--';
    return `${Math.round(amount)}%`;
  }

  function clampPercent(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return 0;
    return Math.max(0, Math.min(100, amount));
  }

  function storageLimitBytes(user) {
    if (!user) return null;
    if (user.storage_limit_bytes === null) return null;
    if (user.storage_limit_bytes !== undefined) return user.storage_limit_bytes;
    return Number(user.storage_limit_mb || 0) * 1024 * 1024;
  }

  function storageUsageText(user) {
    const used = Number(user?.storage_used_bytes || 0);
    const limit = storageLimitBytes(user);
    return limit === null ? `${formatBytes(used)} / Unlimited` : `${formatBytes(used)} / ${formatBytes(limit)}`;
  }

  function ResourceCard({ icon: Icon, label, value, detail, percent }) {
    const safePercent = percent == null ? null : clampPercent(percent);
    return <article className="resource-card">
      <div className="resource-head"><span className="resource-icon"><Icon size={16}/></span><span>{label}</span></div>
      <strong>{value}</strong>
      {safePercent !== null && <div className="resource-track"><span style={{ width: `${safePercent}%` }}></span></div>}
      <small>{detail}</small>
    </article>;
  }

  function renderDashboard() {
    const cpu = resourceUsage?.cpu || {};
    const memory = resourceUsage?.memory || {};
    const disk = resourceUsage?.disk || {};
    const network = resourceUsage?.network || {};
    const networkTotal = (Number(network.rx_per_sec) || 0) + (Number(network.tx_per_sec) || 0);
    return <>
      <section className="resource-grid">
        <ResourceCard icon={Cpu} label="CPU" value={formatPercent(cpu.percent)} percent={cpu.percent} detail={cpu.load?.length ? `Load ${cpu.load.join(' / ')}` : `${cpu.cores || '--'} cores`} />
        <ResourceCard icon={MemoryStick} label="RAM" value={formatPercent(memory.percent)} percent={memory.percent} detail={`${formatBytes(memory.used)} / ${formatBytes(memory.total)}`} />
        <ResourceCard icon={HardDrive} label="Disk" value={formatPercent(disk.percent)} percent={disk.percent} detail={`${formatBytes(disk.used)} / ${formatBytes(disk.total)}`} />
        <ResourceCard icon={Network} label="Network" value={`${formatBytes(networkTotal)}/s`} detail={`Down ${formatBytes(network.rx_per_sec)}/s / Up ${formatBytes(network.tx_per_sec)}/s`} />
      </section>
      <section className="stats-grid">
        <div className="stat-card"><strong>{websites.length}</strong><span>Websites</span></div>
        <div className="stat-card"><strong>{databases.length}</strong><span>Databases</span></div>
        <div className="stat-card"><strong>{websites.filter(s => s.ssl_enabled).length}</strong><span>SSL active</span></div>
        {currentUser && !isAdmin && <div className="stat-card"><strong>{formatBytes(currentUser.storage_used_bytes)}</strong><span>Storage / {formatBytes(storageLimitBytes(currentUser))}</span></div>}
      </section>
      {websites.length > 0 && <section className="section">
        <h2>Quick overview</h2>
        <div className="site-grid">
          {websites.slice(0, 4).map(site => <article className="site-card" key={site.id}>
            <div className="site-head">
              <div><a className="site-link" href={websiteUrl(site)} target="_blank" rel="noopener noreferrer">{site.domain}</a></div>
            </div>
            <div className="site-meta">
              <span className={`badge site-ssl-badge ${site.ssl_enabled ? 'ok' : ''}`}>{site.ssl_enabled ? 'SSL' : 'No SSL'}</span>
              <span>PHP <strong>{site.php_version}</strong></span>
              <span>Status <strong>{site.status}</strong></span>
            </div>
          </article>)}
        </div>
        {websites.length > 4 && <p className="hint" style={{marginTop:8}}>Showing 4 of {websites.length} websites. Go to Websites for full list.</p>}
      </section>}
      {websites.length === 0 && <section className="section">
        <EmptyState icon={Globe} message="No websites yet. Create your first WordPress site from the Websites menu." />
      </section>}
    </>;
  }

  function renderWebsites() {
    const wpFieldsEnabled = siteType === 'wordpress' && installWordPress;
    return <>
      <section className="section">
        <h2>Create website</h2>
        <div className="form-row create-site-row">
          <input value={domain} onChange={e => setDomain(e.target.value)} placeholder="domain.com" />
          <select value={siteType} onChange={e => setSiteType(e.target.value)}>
            <option value="wordpress">WordPress</option>
            <option value="php">Static/PHP</option>
            <option value="static">Static only</option>
          </select>
          <select value={phpVersion} onChange={e => setPhpVersion(e.target.value)}>
            <option value="8.3">PHP 8.3</option>
            <option value="8.4">PHP 8.4</option>
          </select>
          <input value={adminEmail} onChange={e => setAdminEmail(e.target.value)} placeholder="admin@domain.com" disabled={!wpFieldsEnabled} />
          <input value={wpAdminUser} onChange={e => setWpAdminUser(e.target.value)} placeholder="WP admin user" disabled={!wpFieldsEnabled} />
          <input value={wpAdminPassword} onChange={e => setWpAdminPassword(e.target.value)} placeholder="WP admin password" type="password" disabled={!wpFieldsEnabled} />
          <button disabled={!!loading || !domain} onClick={createWordPress}><Plus size={15}/> Create</button>
        </div>
        {siteType === 'wordpress' && <label className="check-line">
          <input type="checkbox" checked={installWordPress} onChange={e => setInstallWordPress(e.target.checked)} />
          Install WordPress (creates database, downloads WP, configures vhost)
        </label>}
        <label className="check-line">
          <input type="checkbox" checked={installSslAfterCreate} onChange={e => setInstallSslAfterCreate(e.target.checked)} />
          Install SSL after creating
        </label>
        <p className="hint">{wpFieldsEnabled
          ? 'WordPress will be installed and the panel will show the URL, admin account, and password after creation.'
          : siteType === 'php'
            ? 'A PHP-FPM vhost will be created with public/ folder. Upload your PHP or static files via File Manager.'
            : 'A static-only Nginx vhost will be created. PHP files can be uploaded but will not execute.'}</p>
      </section>
      <section className="section">
        <div className="section-title">
          <h2>Website list</h2>
          <button disabled={!!loading} onClick={refreshAll}><RefreshCw size={15}/> Refresh</button>
        </div>
        {websites.length === 0 && <EmptyState icon={Globe} message="No websites yet." />}
        <div className="site-grid">
          {websites.map(site => <article className="site-card" key={site.id}>
            <div className="site-head">
              <div>
                <a className="site-link" href={websiteUrl(site)} target="_blank" rel="noopener noreferrer">{site.domain}</a>
                <small>{site.root_path}</small>
              </div>
            </div>
            <div className="site-meta">
              <span className={`badge site-ssl-badge ${site.ssl_enabled ? 'ok' : ''}`}>{site.ssl_enabled ? 'SSL OK' : 'No SSL'}</span>
              <span>Type <strong>{site.app_type || 'wordpress'}</strong></span>
              <span>PHP <strong>{site.php_version}</strong></span>
              <span>Status <strong>{site.status}</strong></span>
              {site.nginx_custom && <span className="badge ok">Custom Nginx</span>}
              {site.waf_enabled && <span className="badge ok">WAF</span>}
            </div>
            <div className="actions">
              {site.app_type !== 'static' && <select value={websitePhpVersions[site.id] || site.php_version || '8.3'} onChange={e => setWebsitePhpVersions(prev => ({ ...prev, [site.id]: e.target.value }))}>
                <option value="8.3">PHP 8.3</option><option value="8.4">PHP 8.4</option>
              </select>}
              {site.app_type !== 'static' && <button disabled={!!loading || (websitePhpVersions[site.id] || site.php_version) === site.php_version} onClick={() => changeWebsitePhpVersion(site)}>Change PHP</button>}
              <button disabled={!!loading} onClick={() => openWebsiteFileManager(site)}><FolderOpen size={14}/> Files</button>
              {isAdmin && <button disabled={!!loading} onClick={() => openNginxCustom(site)}><Code2 size={14}/> Nginx</button>}
              {isAdmin && <button disabled={!!loading} onClick={() => toggleWebsiteWaf(site)}><Shield size={14}/> {site.waf_enabled ? 'WAF off' : 'WAF on'}</button>}
              {site.app_type === 'wordpress' && <button disabled={!!loading} onClick={() => fixWordPressPermissions(site.id)}>Fix permissions</button>}
              <button className="danger" disabled={!!loading} onClick={() => deleteWebsite(site.id)}><Trash2 size={14}/> Delete</button>
            </div>
          </article>)}
        </div>
      </section>
      {nginxCustomEditing && <section className="section nginx-modal">
        <div className="section-title">
          <div className="nginx-config-title">
            <h2>Nginx config - {nginxCustomEditing.domain}</h2>
            <h2>Custom Nginx — {nginxCustomEditing.domain}</h2>
            <p className="hint">Edit the full vhost file. BPanel tests Nginx and rolls back if validation fails.</p>
          </div>
          <button className="secondary-light" onClick={() => setNginxCustomEditing(null)}><X size={14}/> Close</button>
        </div>
        <textarea
          className="code-editor"
          value={nginxCustomEditing.content}
          onChange={e => setNginxCustomEditing(prev => ({ ...prev, content: e.target.value }))}
          placeholder={`server {\n    listen 80;\n    server_name ${nginxCustomEditing.domain};\n}`}
          spellCheck={false}
          rows={14}
        />
        <p className="hint">Use care with <code>listen</code>, <code>root</code>, SSL paths, and upstream directives; this editor writes the production vhost.</p>
        <div className="actions">
          <button disabled={!!loading} onClick={saveNginxCustom}>Save and reload Nginx</button>
          <button className="secondary-light" disabled={!!loading} onClick={() => setNginxCustomEditing(null)}>Cancel</button>
        </div>
      </section>}
    </>;
  }

  function renderSsl() {
    return <section className="section">
      <h2>SSL Certificate</h2>
      <WebsiteSelect />
      {currentSite && <div className="info-box" style={{marginTop:8}}>
        <strong>{currentSite.domain}</strong>
        <span className={currentSite.ssl_enabled ? 'badge ok' : 'badge'} style={{justifySelf:'start'}}>{currentSite.ssl_enabled ? 'SSL Enabled' : 'SSL Disabled'}</span>
      </div>}
      <button disabled={!selectedWebsiteId || !!loading} onClick={() => enableSsl(selectedWebsiteId)} style={{marginTop:8}}><Lock size={15}/> Install / Renew SSL</button>
      <p className="hint">The domain must point to the correct VPS IP before issuing SSL.</p>
    </section>;
  }

  function renderDatabases() {
    return <section className="section">
      <div className="section-title">
        <h2>Databases</h2>
        <button disabled={!!loading} onClick={refreshAll}><RefreshCw size={15}/> Refresh</button>
      </div>
      <div className="form-row">
        <select value={newDatabase.website_id} onChange={e => setNewDatabase(prev => ({ ...prev, website_id: e.target.value }))}>
          <option value="">Select website</option>
          {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
        </select>
        <input value={newDatabase.db_name} onChange={e => setNewDatabase(prev => ({ ...prev, db_name: e.target.value }))} placeholder="database_name (optional)" />
        <button disabled={!!loading || !newDatabase.website_id} onClick={createDatabase}><Plus size={15}/> Create database</button>
      </div>
      {databases.length === 0 && <EmptyState icon={Database} message="No databases found." />}
      <div className="table">
        {databases.map(db => {
          const site = websites.find(item => item.id === db.website_id);
          return <div className="row db-row" key={db.id}>
          <span><strong>{db.db_name}</strong>{site && <small>{site.domain}</small>}</span>
          <span style={{color:'var(--text-muted)'}}>{db.db_user}</span>
          <button disabled={!!loading} onClick={() => openPhpMyAdmin(db.id)}>phpMyAdmin</button>
          <button disabled={!!loading} onClick={() => downloadDatabase(db.id, db.db_name)}><Download size={14}/> SQL</button>
          <button disabled={!!loading} onClick={() => changeDbPassword(db.id)}><KeyRound size={14}/> Password</button>
        </div>})}
      </div>
      <p className="hint">Click phpMyAdmin to sign in directly. Token expires after 60s.</p>
    </section>;
  }

  function renderCron() {
    return <section className="section">
      <h2>Cron manager</h2>
      <WebsiteSelect />
      <input value={cronSchedule} onChange={e => setCronSchedule(e.target.value)} placeholder="0 2 * * *" />
      <input value={cronCommand} onChange={e => setCronCommand(e.target.value)} placeholder="wp cron event run --due-now --allow-root" />
      <div className="actions">
        <button disabled={!selectedWebsiteId || !!loading} onClick={addCron}><Plus size={14}/> Add cron</button>
        <button disabled={!selectedWebsiteId || !!loading} onClick={deleteCron}><Trash2 size={14}/> Delete cron</button>
        <button disabled={!selectedWebsiteId || !!loading} onClick={() => request(`/maintenance/cron/${selectedWebsiteId}`)}>View cron</button>
      </div>
    </section>;
  }

  function renderFiles() {
    const allSelected = files.length > 0 && selectedFilePaths.length === files.length;
    return <section className="section">
      <div className="section-title">
        <div><h2>File manager</h2></div>
        <button disabled={!selectedWebsiteId || !!loading} onClick={() => listFiles(fileListPath)}><RefreshCw size={14}/> Refresh</button>
      </div>
      <div className="file-manager">
        <div className="file-panel">
          <div className="file-controls">
            <WebsiteSelect />
            {currentSite && <div className="file-meta">
              <span>Website: <strong>{currentSite.domain}</strong></span>
              <span>Root: <strong>{currentSite.root_path}/{fileListPath}</strong></span>
              {currentUser && !isAdmin && <span>Storage: <strong>{storageUsageText(currentUser)}</strong></span>}
            </div>}
            <div className="path-pill breadcrumb-line">
              <button className="crumb" disabled={!selectedWebsiteId || fileListPath === 'public'} onClick={() => listFiles('public')}>public</button>
              {fileBreadcrumbs(fileListPath).filter(crumb => crumb.path !== 'public').map(crumb => <button className="crumb" key={crumb.path} onClick={() => listFiles(crumb.path)}>{crumb.label}</button>)}
            </div>
            <div className="file-toolbar">
              <button disabled={!selectedWebsiteId || fileListPath === 'public' || !!loading} onClick={() => listFiles(parentFilePath(fileListPath))}>Up</button>
              <button disabled={!selectedWebsiteId || !!loading} onClick={makeFileDirectory}><Plus size={14}/> Folder</button>
              <label className={`upload-button ${(!selectedWebsiteId || !!loading) ? 'disabled' : ''}`}>
                <Upload size={14}/> Upload
                <input type="file" disabled={!selectedWebsiteId || !!loading} onChange={e => { uploadSiteFile(e.target.files?.[0]); e.target.value = ''; }} />
              </label>
              <select value={archiveFormat} onChange={e => setArchiveFormat(e.target.value)} disabled={!selectedWebsiteId || !!loading}>
                <option value="zip">zip</option>
                <option value="tar.gz">tar.gz</option>
              </select>
              <button disabled={selectedFilePaths.length === 0 || !!loading} onClick={archiveSelectedFiles}><Archive size={14}/> Archive</button>
              <button className="danger" disabled={selectedFilePaths.length === 0 || !!loading} onClick={deleteSelectedFiles}><Trash2 size={14}/> Delete</button>
            </div>
          </div>
          <div className="file-list-header">
            <label><input type="checkbox" checked={allSelected} onChange={toggleAllFiles} disabled={files.length === 0} /> Select</label>
            <span>{files.length} item(s)</span>
          </div>
          <div className="file-list">
            {files.length === 0 && <div className="empty-box">No files in this folder.</div>}
            {files.map(item => <div className={`file-item ${selectedFilePaths.includes(item.path) ? 'selected' : ''}`} key={item.path}>
              <input type="checkbox" checked={selectedFilePaths.includes(item.path)} onChange={() => toggleFileSelection(item.path)} />
              <button className="file-name" onClick={() => item.is_dir ? listFiles(item.path) : (isTextEditable(item) ? openFileEditorTab(item.path) : downloadFile(item.path))}>
                {item.is_dir ? <FolderOpen size={16}/> : <FileText size={16}/>} <strong>{item.name}</strong>
              </button>
              <span className="file-size">{item.is_dir ? 'Folder' : formatBytes(item.size)}</span>
              <div className="file-row-actions">
                {!item.is_dir && isTextEditable(item) && <button className="mini secondary-light" disabled={!!loading} onClick={() => openFileEditorTab(item.path)}>Edit</button>}
                {!item.is_dir && <button className="mini secondary-light" disabled={!!loading} onClick={() => downloadFile(item.path)}><Download size={13}/></button>}
                {isArchiveFile(item) && <button className="mini secondary-light" disabled={!!loading} onClick={() => extractArchiveFile(item.path)}>Extract</button>}
                <button className="mini secondary-light" disabled={!!loading} onClick={() => renameFileItem(item)}>Rename</button>
                <button className="mini danger" disabled={!!loading} onClick={() => deleteFileAction(item.path)}><Trash2 size={13}/></button>
              </div>
            </div>)}
          </div>
        </div>
      </div>
    </section>;
  }

  function renderBackups() {
    const selectedBackupUser = users.find(user => String(user.id) === String(selectedBackupUserId));
    const userNameById = id => users.find(user => String(user.id) === String(id))?.username || `User #${id}`;
    const scheduleUserLabel = item => {
      if (item.all_users) return 'All users';
      const ids = (item.user_ids && item.user_ids.length > 0) ? item.user_ids : (item.user_id ? [item.user_id] : []);
      return ids.length ? ids.map(userNameById).join(', ') : 'No users';
    };
    return <section className="section backups-page">
      <h2>Backups</h2>
      <WebsiteSelect />
      <p className="hint">Backups include website source files and a database SQL export.</p>
      <div className="actions backup-toolbar">
        <button disabled={!selectedWebsiteId || !!loading} onClick={createBackup}><Plus size={14}/> Create backup</button>
        <button disabled={!selectedWebsiteId || !!loading} onClick={listBackups}><RefreshCw size={14}/> Refresh</button>
        <label className="upload-button">
          <Upload size={14}/> Upload backup
          <input type="file" accept=".tar.gz,application/gzip" onChange={e => { uploadBackup(e.target.files?.[0]); e.target.value = ''; }} />
        </label>
      </div>
      {backups.length === 0 && selectedWebsiteId && <EmptyState icon={Archive} message="No backups found for this website." />}
      <div className="backup-list">
        {backups.map(file => <div className="backup-item" key={file}>
          <span>{file.split('/').pop()}</span>
          <div className="actions">
            <button disabled={!!loading} onClick={() => downloadBackup(file)}><Download size={14}/> Download</button>
            <button disabled={!!loading} onClick={() => restoreBackup(file)}><RotateCcw size={14}/> Restore</button>
            <button className="danger" disabled={!!loading} onClick={() => deleteBackup(file)}><Trash2 size={14}/></button>
          </div>
        </div>)}
      </div>
      {isAdmin && <div className="sftp-panel backup-admin-panel">
        <div className="section-title backup-panel-heading">
          <div><h2>Full user backup</h2><p className="hint">Includes the panel user, all owned websites, source files, database dumps, and restore metadata.</p></div>
          <button disabled={!!loading} onClick={() => { loadUsers(); loadBackupSchedules(); loadRestoreBackups(); }}><RefreshCw size={14}/> Refresh</button>
        </div>
        <div className="sftp-run-row user-backup-row backup-run-row">
          <select value={selectedBackupUserId} onChange={e => setSelectedBackupUserId(e.target.value)}>
            <option value="">Select user</option>
            {users.map(user => <option key={user.id} value={user.id}>{user.username}</option>)}
          </select>
          <select value={selectedSftpTargetId} onChange={e => setSelectedSftpTargetId(e.target.value)}>
            <option value="">Local only</option>
            {sftpTargets.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}
          </select>
          <button disabled={!selectedBackupUserId || !!loading} onClick={createUserBackup}><Archive size={14}/> Full backup</button>
        </div>
        {selectedBackupUser && <p className="hint">Current user: <strong>{selectedBackupUser.username}</strong></p>}
        <div className="actions backup-subactions">
          <button disabled={!selectedBackupUserId || !!loading} onClick={() => listUserBackups()}><RefreshCw size={14}/> Backups</button>
        </div>
        <div className="backup-list">
          {userBackups.map(file => <div className="backup-item" key={file}>
            <span>{file.split('/').pop()}</span>
            <div className="actions">
              <button disabled={!!loading} onClick={() => downloadUserBackup(file)}><Download size={14}/> Download</button>
              <button disabled={!!loading} onClick={() => restoreUserBackup(file)}><RotateCcw size={14}/> Restore user</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteUserBackup(file)}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>
        <div className="section-title restore-title backup-panel-heading">
          <div><h2>Restore folder</h2><p className="hint">{restoreBackupDir || '/var/backups/bpanel/users/restore'}</p></div>
          <div className="actions">
            <button disabled={!!loading} onClick={loadRestoreBackups}><RefreshCw size={14}/> Refresh</button>
            <label className="upload-button">
              <Upload size={14}/> Upload backups
              <input type="file" multiple accept=".tar.gz,application/gzip" onChange={e => { uploadUserBackups(e.target.files); e.target.value = ''; }} />
            </label>
          </div>
        </div>
        <div className="backup-list">
          {restoreBackups.map(item => <div className="backup-item" key={item.backup_file}>
            <span>{item.filename || item.backup_file.split('/').pop()}<small>{item.valid ? `${item.username || 'unknown user'} - ${item.websites || 0} website(s)` : (item.error || 'Invalid backup')}</small></span>
            <div className="actions">
              <button disabled={!!loading} onClick={() => downloadUserBackup(item.backup_file)}><Download size={14}/> Download</button>
              <button disabled={!!loading || !item.valid} onClick={() => restoreUserBackup(item.backup_file)}><RotateCcw size={14}/> Restore user</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteRestoreBackup(item.backup_file)}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>
        <div className="sftp-form schedule-form backup-schedule-form">
          <label className="schedule-toggle">
            <input type="checkbox" checked={!!newBackupSchedule.all_users} onChange={e => setNewBackupSchedule(prev => ({ ...prev, all_users: e.target.checked }))} />
            <span>All users</span>
          </label>
          <select multiple value={newBackupSchedule.user_ids || []} disabled={!!newBackupSchedule.all_users} onChange={e => setNewBackupSchedule(prev => ({ ...prev, user_ids: Array.from(e.target.selectedOptions, option => option.value) }))}>
            {users.map(user => <option key={user.id} value={String(user.id)}>{user.username}</option>)}
          </select>
          <input value={newBackupSchedule.schedule} onChange={e => setNewBackupSchedule(prev => ({ ...prev, schedule: e.target.value }))} placeholder="0 2 * * *" />
          <select value={newBackupSchedule.target_id} onChange={e => setNewBackupSchedule(prev => ({ ...prev, target_id: e.target.value }))}>
            <option value="">Local only</option>
            {sftpTargets.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}
          </select>
          <input value={newBackupSchedule.retention} onChange={e => setNewBackupSchedule(prev => ({ ...prev, retention: e.target.value }))} placeholder="7" inputMode="numeric" />
          <button disabled={(!newBackupSchedule.all_users && (!newBackupSchedule.user_ids || newBackupSchedule.user_ids.length === 0)) || !!loading} onClick={createBackupSchedule}><Clock size={14}/> Schedule</button>
        </div>
        <div className="backup-list">
          {backupSchedules.map(item => {
            const scheduleTarget = sftpTargets.find(target => target.id === item.target_id);
            return <div className="backup-item" key={item.id}>
              <span>{scheduleUserLabel(item)} - {item.schedule} - keep {item.retention}{scheduleTarget ? ` - ${scheduleTarget.name}` : ''}<small>{item.last_status}: {item.last_message || 'not run yet'}</small></span>
              <button className="danger" disabled={!!loading} onClick={() => deleteBackupSchedule(item.id)}><Trash2 size={14}/></button>
            </div>;
          })}
        </div>
      </div>}
      {isAdmin && <div className="sftp-panel backup-admin-panel">
        <div className="section-title backup-panel-heading">
          <div><h2>SFTP backup</h2><p className="hint">Create a local archive and upload it to an SFTP target.</p></div>
          <button disabled={!!loading} onClick={loadSftpTargets}><RefreshCw size={14}/> Targets</button>
        </div>
        <div className="sftp-run-row backup-run-row">
          <select value={selectedSftpTargetId} onChange={e => setSelectedSftpTargetId(e.target.value)}>
            <option value="">Select SFTP target</option>
            {sftpTargets.map(target => <option key={target.id} value={target.id}>{target.name} - {target.host}</option>)}
          </select>
          <button disabled={!selectedWebsiteId || !selectedSftpTargetId || !!loading} onClick={createSftpBackup}><Upload size={14}/> Backup to SFTP</button>
        </div>
        <div className="sftp-form sftp-target-form">
          <input value={newSftpTarget.name} onChange={e => setNewSftpTarget(prev => ({ ...prev, name: e.target.value }))} placeholder="Target name" />
          <input value={newSftpTarget.host} onChange={e => setNewSftpTarget(prev => ({ ...prev, host: e.target.value }))} placeholder="Host" />
          <input value={newSftpTarget.port} onChange={e => setNewSftpTarget(prev => ({ ...prev, port: e.target.value }))} placeholder="22" inputMode="numeric" />
          <input value={newSftpTarget.username} onChange={e => setNewSftpTarget(prev => ({ ...prev, username: e.target.value }))} placeholder="Username" />
          <input value={newSftpTarget.password} onChange={e => setNewSftpTarget(prev => ({ ...prev, password: e.target.value }))} placeholder="Password" type="password" />
          <input value={newSftpTarget.remote_path} onChange={e => setNewSftpTarget(prev => ({ ...prev, remote_path: e.target.value }))} placeholder="/backups/bpanel" />
          <textarea value={newSftpTarget.private_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, private_key: e.target.value }))} placeholder="Private key (optional)" rows={4} />
          <button disabled={!!loading || !newSftpTarget.name || !newSftpTarget.host || !newSftpTarget.username || (!newSftpTarget.password && !newSftpTarget.private_key)} onClick={createSftpTarget}><Plus size={14}/> Save target</button>
        </div>
        <div className="backup-list">
          {sftpTargets.map(target => <div className="backup-item" key={target.id}>
            <span>{target.name} - {target.username}@{target.host}:{target.remote_path}</span>
            <button className="danger" disabled={!!loading} onClick={() => deleteSftpTarget(target.id)}><Trash2 size={14}/></button>
          </div>)}
        </div>
      </div>}
    </section>;
  }

  function renderServices() {
    return <section className="section">
      <div className="section-title">
        <h2>Services Status</h2>
        <button disabled={!!loading} onClick={checkAllServices}><RefreshCw size={15}/> Refresh</button>
      </div>
      <div className="service-grid">
        {SERVICE_NAMES.map(name => {
          const state = serviceStates[name];
          const text = `${state?.stdout || ''} ${state?.stderr || ''}`;
          const active = text.includes('active (running)');
          const inactive = text.includes('inactive') || text.includes('failed');
          return <div className="service-card" key={name}>
            <div><strong>{name}</strong><span className={active ? 'badge ok' : inactive ? 'badge bad' : 'badge'}>{active ? 'Running' : inactive ? 'Stopped' : '...'}</span></div>
            <small>Auto-refreshes every 10s</small>
            {isAdmin && <div className="service-actions">
              <button onClick={() => runServiceAction(name, 'start')}><Play size={13}/> Start</button>
              {name !== 'bpanel-api' && <button onClick={() => runServiceAction(name, 'stop')}><Square size={13}/> Stop</button>}
              <button onClick={() => runServiceAction(name, 'restart')}><RotateCcw size={13}/> Restart</button>
            </div>}
          </div>;
        })}
      </div>
    </section>;
  }

  function renderPhpConfig() {
    if (!isAdmin) return <section className="section"><h2>PHP config</h2><p className="hint">You do not have permission to edit PHP config.</p></section>;
    return <section className="section">
      <div className="section-title">
        <div><h2>PHP Configuration</h2><p className="hint">Edit <code>99-bpanel.ini</code> then restart the matching PHP-FPM service.</p></div>
      </div>
      <div className="user-create-card">
        <label><span>PHP version</span><select value={phpConfig.php_version} onChange={e => { const v = e.target.value; setPhpConfig(prev => ({ ...prev, php_version: v })); loadPhpConfig(v); }}>
          <option value="8.3">PHP 8.3</option><option value="8.4">PHP 8.4</option>
        </select></label>
        <label><span>display_errors</span><select value={phpConfig.display_errors} onChange={e => setPhpConfig(prev => ({ ...prev, display_errors: e.target.value }))}>
          <option value="Off">Off (production)</option><option value="On">On (debug)</option>
        </select></label>
        <label><span>max_execution_time</span><input type="number" value={phpConfig.max_execution_time} onChange={e => setPhpConfig(prev => ({ ...prev, max_execution_time: e.target.value }))} /></label>
        <label><span>max_input_time</span><input type="number" value={phpConfig.max_input_time} onChange={e => setPhpConfig(prev => ({ ...prev, max_input_time: e.target.value }))} /></label>
        <label><span>max_input_vars</span><input type="number" value={phpConfig.max_input_vars} onChange={e => setPhpConfig(prev => ({ ...prev, max_input_vars: e.target.value }))} /></label>
        <label><span>memory_limit</span><input value={phpConfig.memory_limit} onChange={e => setPhpConfig(prev => ({ ...prev, memory_limit: e.target.value }))} placeholder="512M" /></label>
        <label><span>post_max_size</span><input value={phpConfig.post_max_size} onChange={e => setPhpConfig(prev => ({ ...prev, post_max_size: e.target.value }))} placeholder="1024M" /></label>
        <label><span>upload_max_filesize</span><input value={phpConfig.upload_max_filesize} onChange={e => setPhpConfig(prev => ({ ...prev, upload_max_filesize: e.target.value }))} placeholder="1024M" /></label>
        <button disabled={!!loading} onClick={updatePhpConfig}>Save PHP config</button>
      </div>
      <p className="hint">Note: <code>post_max_size</code> should be ≥ <code>upload_max_filesize</code>.</p>
    </section>;
  }

  function renderFirewall() {
    if (!isAdmin) return <section className="section"><h2>Firewall</h2><p className="hint">No permission.</p></section>;
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>Firewall (UFW)</h2><p className="hint">Keep SSH and web ports allowed before enabling.</p></div>
        </div>
        <div className="actions">
          <button disabled={!!loading} onClick={loadFirewall}><RefreshCw size={14}/> Refresh</button>
          <button disabled={!!loading} onClick={enableFirewall}><Shield size={14}/> Enable</button>
          <button disabled={!!loading} onClick={disableFirewall}>Disable</button>
          <button disabled={!!loading} onClick={reloadFirewall}>Reload</button>
        </div>
        <div className="info-box firewall-status">
          <strong>UFW status</strong>
          <pre>{firewallStatus?.stdout || firewallStatus?.stderr || 'Click Refresh to load status.'}</pre>
        </div>
      </section>
      <section className="section">
        <h2>Open port</h2>
        <div className="firewall-form">
          <label><span>Port</span><input value={firewallPort} onChange={e => setFirewallPort(e.target.value)} placeholder="80" inputMode="numeric" /></label>
          <label><span>Protocol</span><select value={firewallProtocol} onChange={e => setFirewallProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label>
          <button disabled={!!loading || !firewallPort} onClick={openFirewallPort}>Open port</button>
        </div>
      </section>
      <section className="section">
        <h2>Allow IP</h2>
        <div className="firewall-form">
          <label><span>IP / CIDR</span><input value={firewallAllowIp} onChange={e => setFirewallAllowIp(e.target.value)} placeholder="1.2.3.4" /></label>
          <label><span>Port (optional)</span><input value={firewallAllowPort} onChange={e => setFirewallAllowPort(e.target.value)} placeholder="22" inputMode="numeric" /></label>
          <label><span>Protocol</span><select value={firewallAllowProtocol} onChange={e => setFirewallAllowProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label>
          <button disabled={!!loading || !firewallAllowIp} onClick={allowFirewallIp}>Allow</button>
        </div>
      </section>
      <section className="section">
        <h2>Block IP</h2>
        <div className="firewall-form">
          <label><span>IP / CIDR</span><input value={firewallBlockIp} onChange={e => setFirewallBlockIp(e.target.value)} placeholder="5.6.7.8" /></label>
          <label><span>Port (optional)</span><input value={firewallBlockPort} onChange={e => setFirewallBlockPort(e.target.value)} placeholder="All ports" inputMode="numeric" /></label>
          <label><span>Protocol</span><select value={firewallBlockProtocol} onChange={e => setFirewallBlockProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label>
          <button className="danger" disabled={!!loading || !firewallBlockIp} onClick={blockFirewallIp}>Block</button>
        </div>
      </section>
      <section className="section">
        <h2>Delete rule</h2>
        <div className="firewall-form">
          <label><span>Rule #</span><input value={firewallDeleteNumber} onChange={e => setFirewallDeleteNumber(e.target.value)} placeholder="1" inputMode="numeric" /></label>
          <button className="danger" disabled={!!loading || !firewallDeleteNumber} onClick={deleteFirewallRule}>Delete rule</button>
        </div>
        <p className="hint">Rule numbers change after each delete. Refresh status first.</p>
      </section>
    </>;
  }

  function renderUpdates() {
    if (!isAdmin) return <section className="section"><h2>Updates</h2><p className="hint">No permission.</p></section>;
    const statusText = updatesStatus?.stdout || updatesStatus?.stderr || 'Click Refresh to load update status.';
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>Updates</h2><p className="hint">OS packages use apt; panel updates use <code>installer/update.sh</code>.</p></div>
          <button disabled={!!loading} onClick={loadUpdates}><RefreshCw size={14}/> Refresh</button>
        </div>
        <div className="actions">
          <button disabled={!!loading} onClick={runOsUpdate}><RefreshCw size={14}/> Update OS now</button>
          <button disabled={!!loading} onClick={runPanelUpdate}><RotateCcw size={14}/> Update panel now</button>
        </div>
        <div className="info-box firewall-status"><strong>Status</strong><pre>{statusText}</pre></div>
      </section>
      <section className="section">
        <h2>Auto Update OS</h2>
        <div className="firewall-form">
          <label><span>Enabled</span><select value={osAutoUpdate.enabled ? 'on' : 'off'} onChange={e => setOsAutoUpdate(prev => ({ ...prev, enabled: e.target.value === 'on' }))}><option value="on">On</option><option value="off">Off</option></select></label>
          <label><span>Mode</span><select value={osAutoUpdate.mode} onChange={e => setOsAutoUpdate(prev => ({ ...prev, mode: e.target.value }))}><option value="security">Security</option><option value="all">All packages</option></select></label>
          <label><span>Auto reboot</span><select value={osAutoUpdate.auto_reboot ? 'on' : 'off'} onChange={e => setOsAutoUpdate(prev => ({ ...prev, auto_reboot: e.target.value === 'on' }))}><option value="off">Off</option><option value="on">On</option></select></label>
          <button disabled={!!loading} onClick={saveOsAutoUpdate}>Save OS auto update</button>
        </div>
      </section>
      <section className="section">
        <h2>Auto Update Panel</h2>
        <div className="firewall-form">
          <label><span>Enabled</span><select value={panelAutoUpdate.enabled ? 'on' : 'off'} onChange={e => setPanelAutoUpdate(prev => ({ ...prev, enabled: e.target.value === 'on' }))}><option value="on">On</option><option value="off">Off</option></select></label>
          <label><span>Daily time</span><input value={panelAutoUpdate.time} onChange={e => setPanelAutoUpdate(prev => ({ ...prev, time: e.target.value }))} placeholder="03:30" /></label>
          <button disabled={!!loading} onClick={savePanelAutoUpdate}>Save panel auto update</button>
        </div>
      </section>
    </>;
  }

  function renderWaf() {
    if (!isAdmin) return <section className="section"><h2>WAF</h2><p className="hint">No permission.</p></section>;
    const statusText = wafStatus?.stdout || wafStatus?.stderr || 'Click Refresh to load WAF status.';
    return <section className="section">
      <div className="section-title">
        <div><h2>WAF</h2><p className="hint">Installs ModSecurity for Nginx and loads rules from <code>/etc/nginx/modsec/bpanel-main.conf</code>.</p></div>
        <button disabled={!!loading} onClick={loadWafStatus}><RefreshCw size={14}/> Refresh</button>
      </div>
      <div className="actions">
        <button disabled={!!loading} onClick={installWaf}><Shield size={14}/> Install engine</button>
        <button disabled={!!loading} onClick={updateWafRules}><RefreshCw size={14}/> Update rules</button>
      </div>
      <div className="info-box firewall-status"><strong>WAF status</strong><pre>{statusText}</pre></div>
    </section>;
  }

  function renderSecurity() {
    const enabled = Boolean(twoFactorStatus?.enabled || currentUser?.totp_enabled);
    return <section className="section">
      <div className="section-title">
        <div><h2>Google Authenticator 2FA</h2><p className="hint">Current status: <strong>{enabled ? 'Enabled' : 'Disabled'}</strong></p></div>
        <button disabled={!!loading} onClick={loadTwoFactorStatus}><RefreshCw size={14}/> Refresh</button>
      </div>
      {!enabled && <div className="security-grid">
        <div className="info-box">
          <strong>Setup</strong>
          {twoFactorSetup?.qr_data_url ? <img className="qr-code" src={twoFactorSetup.qr_data_url} alt="2FA QR code" /> : <p className="hint">No setup code generated.</p>}
          {twoFactorSetup?.secret && <code className="secret-text">{twoFactorSetup.secret}</code>}
          <div className="actions">
            <button disabled={!!loading} onClick={setupTwoFactorAuth}><Shield size={14}/> Generate QR</button>
          </div>
        </div>
        <div className="info-box">
          <strong>Verify</strong>
          <input value={twoFactorCode} onChange={e => setTwoFactorCode(e.target.value)} placeholder="123456" inputMode="numeric" />
          <button disabled={!!loading || !twoFactorSetup || !twoFactorCode} onClick={enableTwoFactorAuth}><Lock size={14}/> Enable 2FA</button>
        </div>
      </div>}
      {enabled && <div className="security-grid one">
        <div className="info-box">
          <strong>Disable 2FA</strong>
          <input value={twoFactorCode} onChange={e => setTwoFactorCode(e.target.value)} placeholder="123456" inputMode="numeric" />
          <button className="danger" disabled={!!loading || !twoFactorCode} onClick={disableTwoFactorAuth}>Disable 2FA</button>
        </div>
      </div>}
    </section>;
  }

  function renderPanelSettings() {
    if (!isAdmin) return <section className="section"><h2>Settings</h2><p className="hint">No permission.</p></section>;
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>Panel settings</h2><p className="hint">Branding and public panel URL.</p></div>
          <button disabled={!!loading} onClick={loadPanelSettings}><RefreshCw size={14}/> Refresh</button>
        </div>
        <div className="panel-settings-grid">
          <label><span>Panel name</span><input value={panelSettingsForm.app_name} onChange={e => setPanelSettingsForm(prev => ({ ...prev, app_name: e.target.value }))} placeholder="BPanel" /></label>
          <label><span>Panel URL</span><input value={panelSettingsForm.panel_url} onChange={e => setPanelSettingsForm(prev => ({ ...prev, panel_url: e.target.value }))} placeholder="https://panel.domain.com:2222" /></label>
          <button disabled={!!loading || !panelSettingsForm.app_name} onClick={savePanelSettings}><SettingsIcon size={14}/> Save settings</button>
        </div>
      </section>
      <section className="section">
        <div className="section-title">
          <div><h2>Brand assets</h2><p className="hint">Upload PNG, JPG, WEBP, or ICO files up to 1 MB.</p></div>
        </div>
        <div className="brand-asset-grid">
          <div className="brand-asset-card">
            <div className="brand-preview">{renderBrandMark('settings-brand-mark')}</div>
            <label><span>Logo</span><input type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={e => setPanelLogoFile(e.target.files?.[0] || null)} /></label>
            <button disabled={!!loading || !panelLogoFile} onClick={() => uploadPanelAsset('logo')}><Upload size={14}/> Upload logo</button>
          </div>
          <div className="brand-asset-card">
            <div className="brand-preview favicon-preview">{panelSettings.favicon_url ? <img src={panelSettings.favicon_url} alt="" /> : <Image size={28}/>}</div>
            <label><span>Favicon</span><input type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={e => setPanelFaviconFile(e.target.files?.[0] || null)} /></label>
            <button disabled={!!loading || !panelFaviconFile} onClick={() => uploadPanelAsset('favicon')}><Upload size={14}/> Upload favicon</button>
          </div>
        </div>
      </section>
      <section className="section">
        <div className="section-title">
          <div><h2>Panel SSL</h2><p className="hint">Use a domain that already points to this VPS.</p></div>
          <span className={panelSettings.ssl_enabled ? 'badge ok' : 'badge'}>{panelSettings.ssl_enabled ? 'SSL enabled' : 'SSL not active'}</span>
        </div>
        <div className="panel-settings-grid panel-ssl-grid">
          <label><span>Panel URL</span><input value={panelSettingsForm.panel_url} onChange={e => setPanelSettingsForm(prev => ({ ...prev, panel_url: e.target.value }))} placeholder="https://panel.domain.com:2222" /></label>
          <label><span>Let's Encrypt email</span><input value={panelSslEmail} onChange={e => setPanelSslEmail(e.target.value)} placeholder="admin@domain.com" type="email" /></label>
          <button disabled={!!loading || !panelSettingsForm.panel_url || !panelSslEmail} onClick={installPanelSsl}><Lock size={14}/> Install SSL</button>
        </div>
      </section>
    </>;
  }

  function renderUsers() {
    if (!isAdmin) return <section className="section"><h2>Users</h2><p className="hint">No permission.</p></section>;
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>Add panel user</h2><p className="hint">Panel username is also the Linux user. Login as a user before creating websites for that account.</p></div>
        </div>
        <div className="user-create-card">
          <label><span>Username</span><input value={newUser.username} onChange={e => setNewUser(prev => ({ ...prev, username: e.target.value.toLowerCase() }))} placeholder="johndoe" /></label>
          <label><span>Email</span><input value={newUser.email} onChange={e => setNewUser(prev => ({ ...prev, email: e.target.value }))} placeholder="user@domain.com" /></label>
          <label><span>Password</span><input value={newUser.password} onChange={e => setNewUser(prev => ({ ...prev, password: e.target.value }))} placeholder="Min 12 characters" type="password" /></label>
          <label><span>Role</span><select value={newUser.role} onChange={e => setNewUser(prev => ({ ...prev, role: e.target.value }))}>
            <option value="end_user">End user</option><option value="admin">Admin</option>
          </select></label>
          <label><span>Site limit</span><input type="number" value={newUser.website_limit} onChange={e => setNewUser(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
          <label><span>Storage MB</span><input type="number" value={newUser.storage_limit_mb} onChange={e => setNewUser(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
          <button disabled={!!loading || !newUser.username || !newUser.password} onClick={createUser}><Plus size={14}/> Create user</button>
        </div>
      </section>
      <section className="section">
        <h2>Assign domain to user</h2>
        <div className="assign-row">
          <select value={assignWebsiteId} onChange={e => setAssignWebsiteId(e.target.value)}>
            <option value="">Select domain</option>
            {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
          </select>
          <select value={assignUserId} onChange={e => setAssignUserId(e.target.value)}>
            <option value="">Select user</option>
            {users.map(user => <option key={user.id} value={user.id}>{user.username} ({roleLabel(user.role)})</option>)}
          </select>
          <button disabled={!assignWebsiteId || !assignUserId || !!loading} onClick={assignDomainToUser}>Assign</button>
        </div>
      </section>
      <section className="section">
        <div className="section-title">
          <h2>Panel user list</h2>
          <button disabled={!!loading} onClick={loadUsers}><RefreshCw size={14}/> Refresh</button>
        </div>
        {users.length === 0 && <EmptyState icon={Users} message="No users found." />}
        <div className="table">
          {users.map(user => <div className="row user-row" key={user.id}>
            <div className="user-main"><strong>{user.username}</strong><small>{user.email}</small></div>
            <span className="badge">{roleLabel(user.role)}</span>
            <span className={user.totp_enabled ? 'badge ok' : 'badge'}>{user.totp_enabled ? '2FA' : 'No 2FA'}</span>
            <span className="user-metric"><Globe size={13}/>{user.website_limit} sites</span>
            <span className="user-metric"><HardDrive size={13}/>{storageUsageText(user)}</span>
            <div className="row-actions">
              <button className="mini secondary-light" disabled={!!loading} onClick={() => quickLoginUser(user)}><LogIn size={14}/> Login as</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => changeUserPassword(user)}><KeyRound size={14}/> Password</button>
              {user.totp_enabled && user.id !== currentUser?.id && <button className="mini secondary-light" disabled={!!loading} onClick={() => resetUserTwoFactor(user)}>Reset 2FA</button>}
              {user.id !== currentUser?.id && <button className="mini danger" disabled={!!loading} onClick={() => deletePanelUser(user)}><Trash2 size={14}/></button>}
            </div>
          </div>)}
        </div>
      </section>
    </>;
  }

  function renderStandaloneEditor() {
    const editorLineCount = Math.max(1, String(fileContent || '').split('\n').length);
    const editorMode = editorLanguage(filePath);
    const siteLabel = currentSite?.domain || (selectedWebsiteId ? `Website #${selectedWebsiteId}` : 'Website');
    return <main className="standalone-editor-page">
      <header className="standalone-editor-top">
        <div className="standalone-editor-title">
          <strong>{filePath || 'No file selected'}</strong>
          <span>{siteLabel}</span>
        </div>
        <div className="standalone-editor-actions">
          <span className="editor-chip">{editorMode}</span>
          <span className="editor-chip">{editorLineCount} line(s)</span>
          <span className="editor-chip">Ln {editorCursor.line}, Col {editorCursor.column}</span>
          <button disabled={!selectedWebsiteId || !!loading} onClick={() => readFile(filePath)}><RefreshCw size={14}/> Reload</button>
          <button disabled={!selectedWebsiteId || !!loading} onClick={writeFile}>Save</button>
          <button disabled={!selectedWebsiteId || !filePath || !!loading} onClick={() => downloadFile(filePath)}><Download size={14}/></button>
          <button className="secondary-light" onClick={() => window.close()}><X size={14}/> Close</button>
        </div>
      </header>
      {loading && <div className="loading">{loading}</div>}
      {error && <div className="error"><AlertCircle size={16} style={{display:'inline',verticalAlign:'middle',marginRight:6}}/>{error}</div>}
      {notice && <div className="notice">{notice}</div>}
      <section className="standalone-editor-body">
        <CodeEditor
          value={fileContent}
          mode={editorMode}
          disabled={!selectedWebsiteId}
          onChange={setFileContent}
          onCursorChange={setEditorCursor}
        />
      </section>
    </main>;
  }

  function renderPage() {
    if (page === 'websites') return renderWebsites();
    if (page === 'ssl') return renderSsl();
    if (page === 'databases') return renderDatabases();
    if (page === 'cron') return renderCron();
    if (page === 'files') return renderFiles();
    if (page === 'backups') return renderBackups();
    if (page === 'security') return renderSecurity();
    if (page === 'php') return renderPhpConfig();
    if (page === 'firewall') return renderFirewall();
    if (page === 'waf') return renderWaf();
    if (page === 'updates') return renderUpdates();
    if (page === 'services') return renderServices();
    if (page === 'settings') return renderPanelSettings();
    if (page === 'users') return renderUsers();
    return renderDashboard();
  }

  // Login screen
  if (bootstrapping) {
    return <main className="login-page">
      <section className="login-card">
        <div className="login-brand">{renderBrandMark('login-brand-mark')}<div><p className="eyebrow">{panelSettings.app_name || 'BPanel'}</p><h1>Loading…</h1></div></div>
      </section>
    </main>;
  }

  if (!isAuthenticated) {
    return <main className="login-page">
      <section className="login-card">
        <div className="login-brand">
          {renderBrandMark('login-brand-mark')}
          <div>
            <p className="eyebrow">Server Management Panel</p>
            <h1>{panelSettings.app_name || 'BPanel'}</h1>
            <p className="hint">Manage websites, databases, backups, SSL, and services.</p>
          </div>
        </div>
        <div className="login-form">
          <input value={username} onChange={e => setUsername(e.target.value)} placeholder="Username" autoComplete="username" />
          <input value={password} onChange={e => setPassword(e.target.value)} placeholder="Password" type="password" autoComplete="current-password" onKeyDown={e => { if (e.key === 'Enter') login(); }} />
          {needsTwoFactor && <input value={otpCode} onChange={e => setOtpCode(e.target.value)} placeholder="Authentication code" inputMode="numeric" autoComplete="one-time-code" onKeyDown={e => { if (e.key === 'Enter') login(); }} />}
          <button disabled={!!loading || !username || !password} onClick={login}>{loading ? 'Logging in...' : 'Login'}</button>
        </div>
        {error && <div className="error"><AlertCircle size={16} style={{display:'inline',verticalAlign:'middle',marginRight:6}}/>{error}</div>}
        {notice && <div className="notice">{notice}</div>}
      </section>
    </main>;
  }

  if (standaloneEditor) return renderStandaloneEditor();

  const ActiveIcon = activeNavItem?.[2] || Home;

  return <main className="app-shell">
    <section className="layout">
      {mobileMenuOpen && <div className="mobile-nav-backdrop" onClick={() => setMobileMenuOpen(false)} aria-hidden="true"></div>}
      <aside className={`sidebar ${mobileMenuOpen ? 'open' : ''}`} role="navigation" aria-label="Main navigation">
        <div className="sidebar-head">
          <div className="sidebar-brand">
            {renderBrandMark()}
            <div>
              <strong>{panelSettings.app_name || 'BPanel'}</strong>
              <small>Server Panel</small>
            </div>
          </div>
          <button className="sidebar-close" onClick={() => setMobileMenuOpen(false)} aria-label="Close menu"><X size={18}/></button>
        </div>
        <nav className="sidebar-nav">
          {navItems.map(([key, label, Icon]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => { setPage(key); setMobileMenuOpen(false); }} aria-current={page === key ? 'page' : undefined}>
            <Icon size={17}/>{label}
          </button>)}
        </nav>
      </aside>
      <div className="content">
        <section className="topbar">
          <button className="mobile-nav-toggle" onClick={() => setMobileMenuOpen(o => !o)} aria-expanded={mobileMenuOpen} aria-label="Toggle navigation">
            <Menu size={20}/><span><ActiveIcon size={17}/>{activeNavItem?.[1] || 'Menu'}</span>
          </button>
          <div className="page-title">
            <p className="eyebrow">Server Management Panel</p>
            <h1>{activeNavItem?.[1] || panelSettings.app_name || 'BPanel'}</h1>
          </div>
          <div className="login logged-in">
            <div className="account-pill"><span>Logged in as</span><strong>{currentUser?.username || username}</strong></div>
            <div className="top-actions">
              <button className="secondary compact-btn" onClick={changeMyPassword} aria-label="Change password" title="Change password"><KeyRound size={15}/><span className="btn-label">Password</span></button>
              <button className="secondary compact-btn" onClick={logout} aria-label="Logout" title="Logout"><LogOut size={15}/><span className="btn-label">Logout</span></button>
            </div>
          </div>
        </section>
        <div className="content-body">
          {renderPage()}
          {loading && <div className="loading"><span></span>{loading}</div>}
          {error && <div className="error">{error}</div>}
          {notice && <div className="notice">{notice}</div>}
        </div>
      </div>
    </section>
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
