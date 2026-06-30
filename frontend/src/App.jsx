import React, { useEffect, useState, useCallback, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import ace from 'ace-builds/src-noconflict/ace';
import 'ace-builds/src-noconflict/ext-language_tools';
import 'ace-builds/src-noconflict/ext-searchbox';
import 'ace-builds/src-noconflict/mode-css';
import 'ace-builds/src-noconflict/mode-html';
import 'ace-builds/src-noconflict/mode-ini';
import 'ace-builds/src-noconflict/mode-javascript';
import 'ace-builds/src-noconflict/mode-json';
import 'ace-builds/src-noconflict/mode-php';
import 'ace-builds/src-noconflict/mode-text';
import 'ace-builds/src-noconflict/mode-yaml';
import 'ace-builds/src-noconflict/theme-textmate';
import { Archive, Check, ChevronDown, Clock, Code2, Copy, Cpu, Database, Dices, FileText, FolderOpen, Globe, HardDrive, Home, Image, KeyRound, Lock, LogIn, LogOut, MemoryStick, Menu, MoveRight, Network, Pencil, Save, Server, Settings as SettingsIcon, Shield, Trash2, TerminalIcon, Users, X, RefreshCw, Plus, Download, Upload, Play, Square, RotateCcw, AlertCircle } from 'lucide-react';
import { Terminal } from './components/Terminal';
import './style.css';
import './brand.css';
import './file-manager.css';

const API = import.meta.env.VITE_API_URL || '/api';
const DEFAULT_SERVICE_NAMES = ['bpanel-api', 'nginx', 'php8.3-fpm', 'php8.4-fpm', 'mariadb', 'redis-server'];
const HTTP_FLOOD_DEFAULTS = {
  access_limit_requests: 100,
  access_limit_window: 10,
  access_limit_burst: 100,
  connection_limit: 60,
};
const PHP_VERSION_ORDER = ['5.6', '7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5'];
const SETTINGS_PAGE_KEYS = ['settings', 'security', 'php', 'firewall', 'waf', 'updates', 'services'];
const PAGE_ROUTES = {
  dashboard: '/',
  websites: '/website',
  ssl: '/ssl',
  databases: '/database',
  cron: '/cron',
  files: '/filemanager',
  backups: '/backups',
  users: '/users',
  settings: '/settings',
  security: '/security',
  php: '/php',
  firewall: '/firewall',
  waf: '/waf',
  updates: '/updates',
  services: '/services',
};
const EDITOR_LINE_HEIGHT = 22;
const EDITOR_FONT_FAMILY = "Consolas, 'SFMono-Regular', 'Liberation Mono', Menlo, monospace";
const ROUTE_PAGES = new Map([
  ...Object.entries(PAGE_ROUTES).map(([pageName, path]) => [path, pageName]),
  ['/dashboard', 'dashboard'],
  ['/websites', 'websites'],
  ['/databases', 'databases'],
  ['/files', 'files'],
  ['/file-manager', 'files'],
  ['/website', 'websites'],
]);

function pageFromPathname(pathname) {
  const normalized = `/${String(pathname || '').replace(/^\/+|\/+$/g, '')}`.toLowerCase();
  return ROUTE_PAGES.get(normalized) || 'dashboard';
}

function routeForPage(pageName) {
  return PAGE_ROUTES[pageName] || PAGE_ROUTES.dashboard;
}

function sortPhpVersions(versions = []) {
  return [...versions].sort((a, b) => {
    const ai = PHP_VERSION_ORDER.indexOf(a);
    const bi = PHP_VERSION_ORDER.indexOf(b);
    if (ai !== -1 || bi !== -1) return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    return String(a).localeCompare(String(b), undefined, { numeric: true });
  });
}

function normalizeHttpFloodConfig(config = {}) {
  let value = config;
  if (typeof value === 'string') {
    try { value = value.trim() ? JSON.parse(value) : {}; } catch { value = {}; }
  }
  if (!value || typeof value !== 'object') value = {};
  return Object.fromEntries(Object.entries(HTTP_FLOOD_DEFAULTS).map(([key, fallback]) => {
    const number = value[key] === '' ? NaN : Number(value[key]);
    return [key, Number.isFinite(number) ? number : fallback];
  }));
}

function editorParamsFromLocation() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('view') !== 'editor') return null;
  const websiteId = params.get('website_id');
  const path = params.get('path') || 'public_html/index.html';
  if (!websiteId) return null;
  return { websiteId: String(websiteId), path };
}

function aceModeName(mode) {
  if (mode === 'PHP') return 'php';
  if (mode === 'JavaScript') return 'javascript';
  if (mode === 'CSS') return 'css';
  if (mode === 'HTML') return 'html';
  if (mode === 'JSON') return 'json';
  if (mode === 'YAML') return 'yaml';
  if (mode === 'Config') return 'ini'; // .env, .htaccess, .ini, .conf -> Ace's ini mode
  return 'text';
}

function formatApiError(detail, fallback = 'Request failed.') {
  if (detail === null || detail === undefined || detail === '') return fallback;
  if (typeof detail === 'string') return detail.replace(/^Value error,\s*/i, '') || fallback;
  if (typeof detail === 'number' || typeof detail === 'boolean') return String(detail);

  if (Array.isArray(detail)) {
    const messages = detail.map(item => formatApiErrorItem(item)).filter(Boolean);
    return messages.length ? messages.join('\n') : fallback;
  }

  if (typeof detail === 'object') {
    if (detail.detail !== undefined) return formatApiError(detail.detail, fallback);
    if (detail.message !== undefined) return formatApiError(detail.message, fallback);
    if (detail.msg !== undefined) return formatApiError(detail.msg, fallback);
    try { return JSON.stringify(detail); } catch { return fallback; }
  }

  return fallback;
}

function formatApiErrorItem(item) {
  if (!item || typeof item !== 'object') return formatApiError(item, '');
  const message = formatApiError(item.msg ?? item.message ?? item.detail, 'Invalid value');
  const loc = Array.isArray(item.loc)
    ? item.loc.filter(part => part !== 'body' && part !== 'query' && part !== 'path').join('.')
    : '';
  return loc ? `${loc}: ${message}` : message;
}

function NotificationToast({ type, message, onClose }) {
  if (!message) return null;
  const isError = type === 'error';
  const Icon = isError ? AlertCircle : Check;
  return <div className={`app-toast ${isError ? 'app-toast-error' : 'app-toast-success'}`} role={isError ? 'alert' : 'status'} aria-live={isError ? 'assertive' : 'polite'}>
    <Icon className="app-toast-icon" size={18}/>
    <div className="app-toast-content">
      <strong>{isError ? 'Action failed' : 'Completed'}</strong>
      <span>{message}</span>
    </div>
    <button className="app-toast-close" onClick={onClose} aria-label="Dismiss notification" title="Dismiss notification"><X size={16}/></button>
  </div>;
}

function isHostnameDomain(value = '') {
  return /^(?!-)([a-z0-9-]{1,63}\.)+[a-z]{2,}$/i.test(String(value).trim());
}

function defaultPanelSslEmail(hostname = '') {
  const host = String(hostname || '').trim().toLowerCase();
  return isHostnameDomain(host) ? `admin@${host}` : '';
}

function renderAceSelectionTextOverlay(editor, overlay) {
  if (!editor || !overlay) return;
  overlay.innerHTML = '';
  const ranges = editor.selection.getAllRanges?.() || [editor.selection.getRange()];
  const visibleFirst = editor.renderer.getFirstVisibleRow?.() ?? 0;
  const visibleLast = editor.renderer.getLastVisibleRow?.() ?? editor.session.getLength();
  const containerRect = editor.container.getBoundingClientRect();
  const lineHeight = editor.renderer.lineHeight || 20;
  const charWidth = editor.renderer.characterWidth || 8;

  ranges.forEach(range => {
    if (!range || range.isEmpty()) return;
    const startRow = Math.max(range.start.row, visibleFirst);
    const endRow = Math.min(range.end.row, visibleLast);
    for (let row = startRow; row <= endRow; row += 1) {
      const line = editor.session.getLine(row) || '';
      const fromColumn = row === range.start.row ? range.start.column : 0;
      const toColumn = row === range.end.row ? range.end.column : line.length;
      if (toColumn <= fromColumn) continue;

      const start = editor.renderer.textToScreenCoordinates(row, fromColumn);
      const end = editor.renderer.textToScreenCoordinates(row, toColumn);
      const left = start.pageX - containerRect.left;
      const top = start.pageY - containerRect.top;
      const width = Math.max(end.pageX - start.pageX, charWidth);

      const node = document.createElement('div');
      node.className = 'bpanel-ace-selected-text';
      node.textContent = line.slice(fromColumn, toColumn);
      node.style.left = `${left}px`;
      node.style.top = `${top}px`;
      node.style.width = `${width}px`;
      node.style.height = `${lineHeight}px`;
      overlay.appendChild(node);
    }
  });
}

function applyAceLineHeight(editor) {
  if (!editor?.renderer) return;
  const { renderer } = editor;
  const characterWidth = renderer.characterWidth || renderer.$textLayer?.getCharacterWidth?.() || 8;
  editor.container?.style.setProperty('font-family', EDITOR_FONT_FAMILY);
  editor.container?.style.setProperty('font-size', '13px');
  editor.container?.style.setProperty('line-height', `${EDITOR_LINE_HEIGHT}px`);
  renderer.$textLayer?.$fontMetrics?.checkForSizeChanges?.({ width: characterWidth, height: EDITOR_LINE_HEIGHT });
  renderer.updateFontSize?.();
  renderer.updateCharacterSize?.();
  renderer.lineHeight = EDITOR_LINE_HEIGHT;
  if (renderer.layerConfig) renderer.layerConfig.lineHeight = EDITOR_LINE_HEIGHT;
  if (renderer.scroller) renderer.scroller.style.lineHeight = `${EDITOR_LINE_HEIGHT}px`;
  renderer.updateFull?.(true);
  renderer.updateText?.();
  renderer.updateCursor?.();
}

function CodeEditor({ value, mode, disabled, onChange, onCursorChange }) {
  const hostRef = useRef(null);
  const editorRef = useRef(null);
  const suppressChangeRef = useRef(false);
  const onChangeRef = useRef(onChange);
  const onCursorChangeRef = useRef(onCursorChange);

  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  useEffect(() => { onCursorChangeRef.current = onCursorChange; }, [onCursorChange]);

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const editor = ace.edit(hostRef.current, {
      mode: `ace/mode/${aceModeName(mode)}`,
      theme: 'ace/theme/textmate',
      value: value || '',
      readOnly: !!disabled,
      showPrintMargin: false,
      highlightActiveLine: true,
      fontSize: 13,
      tabSize: 2,
      useSoftTabs: true,
      wrap: false,
      selectionStyle: 'text',
    });

    const selectionOverlay = document.createElement('div');
    selectionOverlay.className = 'bpanel-ace-selection-overlay';
    editor.container.appendChild(selectionOverlay);
    const refreshSelectionOverlay = () => renderAceSelectionTextOverlay(editor, selectionOverlay);

    editor.setOptions({
      enableBasicAutocompletion: true,
      enableLiveAutocompletion: true,
      enableMatchBrackets: true,
      enableSnippets: false,
      fontFamily: EDITOR_FONT_FAMILY,
    });
    applyAceLineHeight(editor);
    editor.session.setUseWorker(false);
    editor.session.setNewLineMode('unix');

    let destroyed = false;
    const reportCursor = () => {
      if (destroyed || !editorRef.current || !onCursorChangeRef.current) return;
      const pos = editorRef.current.getCursorPosition();
      onCursorChangeRef.current({ line: pos.row + 1, column: pos.column + 1 });
    };
    const handleChange = () => {
      if (destroyed || !editorRef.current) return;
      if (!suppressChangeRef.current) {
        if (onChangeRef.current) onChangeRef.current(editorRef.current.getValue());
      }
      // Only report cursor on explicit cursor moves, not on every content change
    };

    editor.session.on('change', handleChange);
    editor.selection.on('changeCursor', reportCursor);
    editor.selection.on('changeSelection', refreshSelectionOverlay);
    const afterRender = () => {
      if (Math.round(editor.renderer.lineHeight || 0) !== EDITOR_LINE_HEIGHT) {
        applyAceLineHeight(editor);
      }
      refreshSelectionOverlay();
    };
    editor.renderer.on('afterRender', afterRender);
    editorRef.current = editor;
    requestAnimationFrame(() => {
      if (destroyed) return;
      applyAceLineHeight(editor);
      refreshSelectionOverlay();
    });
    reportCursor();
    refreshSelectionOverlay();

    return () => {
      destroyed = true;
      editor.session.off('change', handleChange);
      editor.selection.off('changeCursor', reportCursor);
      editor.selection.off('changeSelection', refreshSelectionOverlay);
      editor.renderer.off('afterRender', afterRender);
      selectionOverlay.remove();
      editor.destroy();
      editorRef.current = null;
      if (hostRef.current) hostRef.current.textContent = '';
    };
  }, []);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const nextValue = value || '';
    if (nextValue === editor.getValue()) return;
    const cursor = editor.getCursorPosition();
    suppressChangeRef.current = true;
    editor.setValue(nextValue, -1);
    const newRow = Math.max(0, Math.min(cursor.row, editor.session.getLength() - 1));
    editor.moveCursorTo(newRow, cursor.column);
    suppressChangeRef.current = false;
  }, [value]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.session.setMode(`ace/mode/${aceModeName(mode)}`);
  }, [mode]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.setReadOnly(!!disabled);
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
  const [page, setPage] = useState(() => pageFromPathname(window.location.pathname));
  const [domain, setDomain] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [wpAdminUser, setWpAdminUser] = useState('admin');
  const [wpAdminPassword, setWpAdminPassword] = useState('');
  const [phpVersion, setPhpVersion] = useState('8.3');
  const [siteType, setSiteType] = useState('wordpress');
  const [installSslAfterCreate, setInstallSslAfterCreate] = useState(false);
  const [installWordPress, setInstallWordPress] = useState(true);
  const [nginxCustomEditing, setNginxCustomEditing] = useState(null); // {id, domain, mode, content}
  const [logViewer, setLogViewer] = useState(null); // {id, domain, kind, lines, path, content, exists}
  const [terminalViewer, setTerminalViewer] = useState(null); // {id, domain}
  const [websites, setWebsites] = useState([]);
  const [databases, setDatabases] = useState([]);
  const [newDatabase, setNewDatabase] = useState({ db_name: '', db_user: '', db_password: '' });
  const [createdDbInfo, setCreatedDbInfo] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [users, setUsers] = useState([]);
  const [resourceUsage, setResourceUsage] = useState(null);
  const [serviceStates, setServiceStates] = useState({});
  const [serviceNames, setServiceNames] = useState(DEFAULT_SERVICE_NAMES);
  const [backupTab, setBackupTab] = useState('website');
  const [backups, setBackups] = useState([]);
  const [backupJobs, setBackupJobs] = useState([]);
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
  const [cronSchedule, setCronSchedule] = useState('*/15 * * * *');
  const [cronCommand, setCronCommand] = useState('');
  const [cronItems, setCronItems] = useState([]);
  const [cronUser, setCronUser] = useState('');
  const [filePath, setFilePath] = useState(() => standaloneEditor?.path || 'public_html/index.html');
  const [fileListPath, setFileListPath] = useState('public_html');
  const [fileUploadDir, setFileUploadDir] = useState('public_html');
  const [files, setFiles] = useState([]);
  const [fileJobs, setFileJobs] = useState([]);
  const [fileContent, setFileContent] = useState('');
  const [selectedFilePaths, setSelectedFilePaths] = useState([]);
  const [archiveFormat, setArchiveFormat] = useState('zip');
  const [editorCursor, setEditorCursor] = useState({ line: 1, column: 1 });
  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'end_user', website_limit: 5, storage_limit_mb: 1024 });
  const [editingUser, setEditingUser] = useState(null);
  const [editingUserForm, setEditingUserForm] = useState({ email: '', role: 'end_user', website_limit: 5, storage_limit_mb: 1024 });
  const [phpConfig, setPhpConfig] = useState({ php_version: '8.3', display_errors: 'Off', max_execution_time: 300, max_input_time: 600, max_input_vars: 10000, memory_limit: '512M', post_max_size: '1024M', upload_max_filesize: '1024M' });
  const [phpVersions, setPhpVersions] = useState({ installed: ['8.3', '8.4'], supported: ['5.6', '7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5'] });
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
  const [firewallBlocklists, setFirewallBlocklists] = useState(null);
  const [firewallBlocklistUrl, setFirewallBlocklistUrl] = useState('');
  const [wafRules, setWafRules] = useState({ status: null, default_rules: '', custom_rules: '' });
  const [wafCustomRules, setWafCustomRules] = useState('');
  const [selectedWafWebsiteId, setSelectedWafWebsiteId] = useState('');
  const [wafSiteConfig, setWafSiteConfig] = useState(null);
  const [httpFloodForm, setHttpFloodForm] = useState({ http_flood_enabled: false, ...HTTP_FLOOD_DEFAULTS });
  const [websitePhpVersions, setWebsitePhpVersions] = useState({});
  const [websiteAppTypes, setWebsiteAppTypes] = useState({});
  const [websiteDocumentRoots, setWebsiteDocumentRoots] = useState({});
  const [assignUserId, setAssignUserId] = useState('');
  const [assignWebsiteId, setAssignWebsiteId] = useState('');
  const [twoFactorStatus, setTwoFactorStatus] = useState(null);
  const [twoFactorSetup, setTwoFactorSetup] = useState(null);
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [panelSettings, setPanelSettings] = useState({ app_name: 'BPanel', panel_url: '', panel_hostname: '', panel_port: 2222, logo_url: '', favicon_url: '/favicon.png', ssl_enabled: false });
  const [panelSettingsForm, setPanelSettingsForm] = useState({ app_name: 'BPanel', panel_hostname: '', panel_port: 2222, ssl_enabled: false });
  const [appVersion, setAppVersion] = useState('');
  const [panelLogoFile, setPanelLogoFile] = useState(null);
  const [panelFaviconFile, setPanelFaviconFile] = useState(null);
  const [panelSslEmail, setPanelSslEmail] = useState('');
  const [updatesStatus, setUpdatesStatus] = useState(null);
  const [showUpdateLog, setShowUpdateLog] = useState(false);
  const [osUpdating, setOsUpdating] = useState(false);
  const [panelUpdating, setPanelUpdating] = useState(false);
  const [osAutoUpdate, setOsAutoUpdate] = useState({ enabled: true, mode: 'security', auto_reboot: false });
  const [panelAutoUpdate, setPanelAutoUpdate] = useState({ enabled: true, time: '03:30' });
  const noticeTimer = useRef(null);

  const navigateToPage = useCallback((nextPage, options = {}) => {
    const route = routeForPage(nextPage);
    if (!route) return;
    const nextUrl = route;
    if (!options.replace && window.location.pathname !== route) {
      window.history.pushState({}, '', nextUrl);
    } else if (options.replace && window.location.pathname !== route) {
      window.history.replaceState({}, '', nextUrl);
    }
    setPage(nextPage);
  }, []);

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

  function currentPanelHost() {
    return window.location.hostname || '';
  }

  function currentPanelPort() {
    const port = Number(window.location.port || 2222);
    return Number.isFinite(port) && port > 0 ? port : 2222;
  }

  function formFromPanelSettings(data = {}) {
    let hostname = data.panel_hostname || currentPanelHost();
    let port = Number(data.panel_port || currentPanelPort());
    if ((!hostname || !port) && data.panel_url) {
      try {
        const parsed = new URL(data.panel_url);
        hostname = hostname || parsed.hostname;
        port = port || Number(parsed.port || 2222);
      } catch {}
    }
    return {
      app_name: data.app_name || 'BPanel',
      panel_hostname: hostname,
      panel_port: Number.isFinite(port) && port > 0 ? port : 2222,
      ssl_enabled: !!data.ssl_enabled,
    };
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
    setServiceNames(DEFAULT_SERVICE_NAMES);
    setBackupTab('website');
    setBackups([]);
    setBackupJobs([]);
    setCronItems([]);
    setCronUser('');
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
    setFirewallBlocklists(null);
    setWafRules({ status: null, default_rules: '', custom_rules: '' });
    setWafCustomRules('');
    setSelectedWafWebsiteId('');
    setWafSiteConfig(null);
    setLogViewer(null);
    setNginxCustomEditing(null);
    setTerminalViewer(null);
    setSelectedWebsiteId('');
    setMobileMenuOpen(false);
    navigateToPage('dashboard', { replace: true });
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
      if (!res.ok) setError(formatApiError(data.detail, `Request failed with status ${res.status}`));
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
        setError(formatApiError(data.detail, `Login failed with status ${res.status}`));
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
        return null;
      }
      const data = await res.json();
      setCurrentUser(data);
      setIsAuthenticated(true);
      return data;
    } catch {
      setCurrentUser(null);
      return null;
    }
  }

  async function loadPanelSettings() {
    try {
      const res = await fetch(`${API}/panel-settings/public`, { credentials: 'include' });
      if (!res.ok) return null;
      const data = await res.json();
      setPanelSettings(data);
      setPanelSettingsForm(formFromPanelSettings(data));
      return data;
    } catch {
      return null;
    }
  }

  async function loadAppVersion() {
    try {
      const res = await fetch(`${API}/health`, { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setAppVersion(data.version || '');
    } catch {}
  }

  async function savePanelSettings() {
    const wantsSsl = !!panelSettingsForm.ssl_enabled;
    const hasSsl = !!panelSettings.ssl_enabled;
    const hostname = String(panelSettingsForm.panel_hostname || '').trim();
    const port = Number(panelSettingsForm.panel_port || 2222);
    const currentHostname = panelSettings.panel_hostname || currentPanelHost();
    const hostnameChanged = hostname && hostname !== currentHostname;

    if (wantsSsl && (!hasSsl || hostnameChanged)) {
      const sslEmail = String(panelSslEmail || defaultPanelSslEmail(hostname) || currentUser?.email || '').trim();
      const nameData = await request('/panel-settings', {
        method: 'PATCH',
        body: JSON.stringify({ app_name: panelSettingsForm.app_name }),
      }, 'Saving panel settings...');
      if (!nameData) return;
      const sslData = await request('/panel-settings/ssl', {
        method: 'POST',
        body: JSON.stringify({ panel_hostname: hostname, panel_port: port, ...(sslEmail ? { email: sslEmail } : {}) }),
      }, 'Installing panel SSL...');
      if (sslData) {
        setPanelSettings(sslData);
        setPanelSettingsForm(formFromPanelSettings(sslData));
        setNotice(sslData.message || 'Panel SSL installed. The panel may restart in a moment.');
      }
      return;
    }

    const payload = hasSsl && !wantsSsl
      ? { app_name: panelSettingsForm.app_name, panel_url: `http://${hostname}:${port}` }
      : { app_name: panelSettingsForm.app_name, panel_hostname: hostname };
    const data = await request('/panel-settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }, 'Saving panel settings...');
    if (data) {
      setPanelSettings(data);
      setPanelSettingsForm(formFromPanelSettings(data));
      setNotice(hasSsl && !wantsSsl ? 'Panel SSL disabled. The panel remains reachable by IP and port over HTTP.' : 'Panel settings updated.');
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
      setPanelSettingsForm(formFromPanelSettings(data));
      if (kind === 'logo') setPanelLogoFile(null);
      if (kind === 'favicon') setPanelFaviconFile(null);
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

  useEffect(() => { loadPanelSettings(); loadAppVersion(); }, []);

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
    const refreshedUser = await loadCurrentUser();
    const siteData = await request('/websites');
    if (siteData) {
      setWebsites(siteData);
      if (!selectedWebsiteId && siteData[0]) setSelectedWebsiteId(String(siteData[0].id));
    }
    const dbData = await request('/databases');
    if (dbData) setDatabases(dbData);
    if (refreshedUser?.role === 'admin') await loadPhpVersions();
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

  function startEditingUser(user) {
    setEditingUser(user);
    setEditingUserForm({
      email: user.email || '',
      role: user.role || 'end_user',
      website_limit: user.website_limit ?? 5,
      storage_limit_mb: user.storage_limit_mb ?? 1024,
    });
  }

  function cancelEditingUser() {
    setEditingUser(null);
    setEditingUserForm({ email: '', role: 'end_user', website_limit: 5, storage_limit_mb: 1024 });
  }

  async function updatePanelUser() {
    if (!editingUser) return;
    const websiteLimit = Number(editingUserForm.website_limit);
    const storageLimitMb = Number(editingUserForm.storage_limit_mb);
    if (!editingUserForm.email.trim()) { setError('Email is required.'); return; }
    if (!Number.isInteger(websiteLimit) || websiteLimit < 0 || websiteLimit > 1000) {
      setError('Website limit must be between 0 and 1000.');
      return;
    }
    if (!Number.isInteger(storageLimitMb) || storageLimitMb < 0 || storageLimitMb > 1024 * 1024) {
      setError('Storage limit must be between 0 and 1048576 MB.');
      return;
    }
    const payload = {
      email: editingUserForm.email.trim(),
      website_limit: websiteLimit,
      storage_limit_mb: storageLimitMb,
    };
    if (editingUser.id !== currentUser?.id) payload.role = editingUserForm.role;
    const data = await request(`/users/${editingUser.id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }, `Updating ${editingUser.username}...`);
    if (data) {
      setNotice(`Updated user ${data.username}.`);
      if (data.id === currentUser?.id) setCurrentUser(prev => ({ ...prev, ...data }));
      cancelEditingUser();
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
    // Impersonation re-prompts TOTP when the calling admin has 2FA enabled.
    // Try without the code first; if the backend says one is required, ask
    // and resend. Sending the OTP via FormData keeps it out of the URL.
    let body;
    if (currentUser?.totp_enabled) {
      const code = prompt(`Enter the 6-digit code from your authenticator to confirm impersonation of ${user.username}:`);
      if (!code) return;
      body = new URLSearchParams({ otp: code.trim() });
    }
    const data = await request(
      `/auth/impersonate/${user.id}`,
      body
        ? { method: 'POST', body, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
        : { method: 'POST' },
      `Logging in as ${user.username}...`,
    );
    // Handle case where backend says 2FA is required (e.g., stale user object).
    if (data?.requires_2fa) {
      const code = prompt(`Enter the 6-digit code from your authenticator to confirm impersonation of ${user.username}:`);
      if (!code) return;
      const retryBody = new URLSearchParams({ otp: code.trim() });
      const retryData = await request(
        `/auth/impersonate/${user.id}`,
        { method: 'POST', body: retryBody, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
        `Logging in as ${user.username}...`,
      );
      if (retryData?.access_token) {
        setNotice(`Logged in as ${user.username}.`);
        await loadCurrentUser();
        navigateToPage('websites');
        await refreshAll();
      }
      return;
    }
    if (data?.access_token) {
      setNotice(`Logged in as ${user.username}.`);
      await loadCurrentUser();
      navigateToPage('websites');
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
    const cleanDomain = domain.trim().toLowerCase();
    const cleanAdminEmail = adminEmail.trim();
    if (!cleanDomain) { setError('Please enter a domain name.'); return; }
    const installWp = siteType === 'wordpress' && installWordPress;
    const body = {
      domain: cleanDomain,
      php_version: phpVersion,
      app_type: siteType,
      install_wordpress: installWp,
      title: cleanDomain,
    };
    if (installWp) {
      body.admin_user = wpAdminUser;
      body.admin_email = cleanAdminEmail || `admin@${cleanDomain}`;
      body.admin_password = wpAdminPassword || 'StrongPass123!';
    }
    const data = await request('/websites', { method: 'POST', body: JSON.stringify(body) },
      installWp ? 'Creating WordPress website...' : 'Creating website...');
    if (data) {
      if (installWp) {
        setNotice(`Created WordPress site: https://${cleanDomain}\nAdmin: ${wpAdminUser} | Password: ${wpAdminPassword || 'StrongPass123!'}`);
      } else {
        setNotice(`Created site ${cleanDomain}. Upload your files to public_html/ folder.`);
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
    setLogViewer(null);
    setTerminalViewer(null);
    const data = await request(`/websites/${site.id}/nginx-custom`, {}, 'Loading Custom Nginx...');
    if (data !== null) {
      setNginxCustomEditing({
        id: site.id,
        domain: site.domain,
        mode: 'custom',
        content: data?.nginx_custom || '',
      });
    }
  }

  async function viewFullNginxConfig() {
    if (!nginxCustomEditing) return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-config`, {}, 'Loading full Nginx config...');
    if (data !== null) {
      setNginxCustomEditing(prev => ({ ...prev, mode: 'full', content: data?.nginx_config || '' }));
    }
  }

  async function saveNginxCustom() {
    if (!nginxCustomEditing) return;
    if (nginxCustomEditing.mode === 'full') return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-custom`, {
      method: 'PUT',
      body: JSON.stringify({ nginx_custom: nginxCustomEditing.content }),
    }, 'Applying Custom Nginx and reloading...');
    if (data) {
      setNotice(`Updated Custom Nginx for ${nginxCustomEditing.domain}`);
      setNginxCustomEditing(null);
      refreshAll();
    }
  }

  async function resetNginxDefault() {
    if (!nginxCustomEditing) return;
    if (!confirm(`Clear Custom Nginx for ${nginxCustomEditing.domain}?`)) return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-custom`, {
      method: 'PUT',
      body: JSON.stringify({ nginx_custom: '' }),
    }, 'Clearing Custom Nginx...');
    if (data) {
      setNotice(`Cleared Custom Nginx for ${nginxCustomEditing.domain}.`);
      setNginxCustomEditing(null);
      await refreshAll();
    }
  }

  async function loadWebsiteLog(siteOrId = logViewer?.id, kind = logViewer?.kind || 'access', lines = logViewer?.lines || 200, domainLabel = logViewer?.domain || '') {
    const websiteId = typeof siteOrId === 'object' ? siteOrId.id : siteOrId;
    const domainName = typeof siteOrId === 'object' ? siteOrId.domain : domainLabel;
    if (!websiteId) return;
    const data = await request(`/websites/${websiteId}/logs?kind=${encodeURIComponent(kind)}&lines=${encodeURIComponent(lines)}`, {}, `Loading ${kind} log...`);
    if (data) {
      setLogViewer({
        id: websiteId,
        domain: data.domain || domainName,
        kind: data.kind || kind,
        lines: data.lines || lines,
        path: data.path || '',
        content: data.content || '',
        exists: !!data.exists,
      });
    }
  }

  async function openWebsiteLogs(site) {
    setNginxCustomEditing(null);
    setTerminalViewer(null);
    setLogViewer({ id: site.id, domain: site.domain, kind: 'access', lines: 200, path: '', content: '', exists: true });
    await loadWebsiteLog(site, 'access', 200, site.domain);
  }

  function openWebsiteTerminal(site) {
    setNginxCustomEditing(null);
    setLogViewer(null);
    setTerminalViewer({ id: site.id, domain: site.domain });
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
      if (String(selectedWafWebsiteId) === String(site.id)) await loadWebsiteWafConfig(site.id, false);
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

  async function changeWebsiteAppType(site) {
    const next = websiteAppTypes[site.id] || site.app_type || 'wordpress';
    if (next === (site.app_type || 'wordpress')) return;
    const data = await request(`/websites/${site.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ app_type: next }),
    }, `Changing ${site.domain} to ${next} mode...`);
    if (data) {
      setNotice(`Changed ${site.domain} to ${data.app_type} mode.`);
      setWebsiteAppTypes(prev => ({ ...prev, [site.id]: data.app_type }));
      await refreshAll();
    }
  }

  async function changeWebsiteDocumentRoot(site) {
    const next = (websiteDocumentRoots[site.id] ?? site.document_root ?? 'public_html').trim();
    if (!next || next === (site.document_root || 'public_html')) return;
    const data = await request(`/websites/${site.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ document_root: next }),
    }, `Changing document root for ${site.domain}...`);
    if (data) {
      setNotice(`Changed ${site.domain} document root to ${data.document_root}.`);
      setWebsiteDocumentRoots(prev => ({ ...prev, [site.id]: data.document_root }));
      await refreshAll();
    }
  }

  async function changeDbPassword(id) {
    const newPass = prompt('Enter a new database password, minimum 12 characters:');
    if (!newPass) return;
    await request(`/databases/${id}/password`, { method: 'POST', body: JSON.stringify({ password: newPass }) }, 'Changing database password...');
  }

  async function deleteDatabase(id, dbName) {
    if (!confirm(`Delete database "${dbName}"? This action cannot be undone.`)) return;
    const data = await request(`/databases/${id}`, { method: 'DELETE' }, 'Deleting database...');
    if (data) {
      setNotice(`Database "${dbName}" deleted successfully.`);
      await refreshAll();
    }
  }

  function generateRandomPassword(length = 20) {
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#%^*_+-';
    const arr = new Uint8Array(length);
    crypto.getRandomValues(arr);
    return Array.from(arr, b => chars[b % chars.length]).join('');
  }

  async function createDatabase() {
    const validDbName = /^[a-zA-Z0-9_]+$/;
    const dbName = newDatabase.db_name.trim();
    const dbUser = newDatabase.db_user.trim();
    const dbPass = newDatabase.db_password.trim();
    if (!dbName) { setError('Please enter a database name.'); return; }
    if (!validDbName.test(dbName)) { setError('Database name can only contain letters, numbers and underscores (no spaces or special characters).'); return; }
    if (dbUser && !validDbName.test(dbUser)) { setError('Database user can only contain letters, numbers and underscores (no spaces or special characters).'); return; }
    if (dbPass && dbPass.length < 12) { setError('Password must be at least 12 characters.'); return; }
    if (dbPass && /[^\x20-\x7E]/.test(dbPass)) { setError('Password contains invalid characters. Use only ASCII characters.'); return; }
    const body = {
      db_name: dbName,
      db_user: dbUser || null,
      db_password: dbPass || null,
    };
    const data = await request('/databases', { method: 'POST', body: JSON.stringify(body) }, 'Creating database...');
    if (data) {
      setCreatedDbInfo({ db_name: data.db_name, db_user: data.db_user, db_password: data.db_password });
      setNewDatabase({ db_name: '', db_user: '', db_password: '' });
      await refreshAll();
    }
  }

  async function addCron() {
    const data = await request('/maintenance/cron', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), schedule: cronSchedule, command: cronCommand }) }, 'Adding cron job...');
    if (data) {
      if (data.cron_user) setCronUser(data.cron_user);
      setNotice(`Cron job added${data.cron_user ? ` as ${data.cron_user}` : ''}.`);
      await listCron();
    }
  }

  async function listCron() {
    if (!selectedWebsiteId) return;
    const data = await request(`/maintenance/cron/${selectedWebsiteId}`, {}, 'Loading cron jobs...');
    if (data?.items) setCronItems(data.items);
    if (data?.cron_user) setCronUser(data.cron_user);
  }

  async function deleteCron(index) {
    if (!confirm(`Delete cron #${index}?`)) return;
    index = Number(index);
    if (Number.isNaN(index)) return;
    const data = await request('/maintenance/cron', { method: 'DELETE', body: JSON.stringify({ website_id: Number(selectedWebsiteId), index }) }, 'Deleting cron job...');
    if (data) {
      if (data.cron_user) setCronUser(data.cron_user);
      setNotice('Cron job deleted.');
      await listCron();
    }
  }

  async function listFiles(path = fileListPath, websiteId = selectedWebsiteId) {
    if (!websiteId) return;
    const data = await request(`/maintenance/files/${websiteId}?path=${encodeURIComponent(path)}`, {}, 'Loading file list...');
    if (data?.items) { setFiles(data.items); setFileListPath(path); setFileUploadDir(path || ''); setSelectedFilePaths([]); }
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
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Download failed.')); return; }
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
    url.pathname = routeForPage('files');
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
    const data = await request('/maintenance/files/mkdir', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: fileListPath || '', name }) }, 'Creating folder...');
    if (data) await listFiles(fileListPath);
  }

  async function makeFile() {
    if (!selectedWebsiteId) return;
    const name = prompt('File name:', 'new-file.txt');
    if (!name) return;
    const data = await request('/maintenance/files/create', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: fileListPath || '', name }) }, 'Creating file...');
    if (data) {
      await listFiles(fileListPath);
      const newPath = [fileListPath, name].filter(Boolean).join('/');
      openFileEditorTab(newPath);
    }
  }

  async function renameFileItem(item) {
    if (!item) return;
    const newName = prompt('New name:', item.name);
    if (!newName || newName === item.name) return;
    const data = await request('/maintenance/files/rename', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: item.path, new_name: newName }) }, 'Renaming...');
    if (data) await listFiles(fileListPath);
  }

  async function chmodFileItem(item) {
    if (!item) return;
    const currentMode = item.mode || (item.is_dir ? '755' : '644');
    const mode = prompt('Mode (octal, e.g. 644 or 755):', currentMode);
    if (!mode || mode === currentMode) return;
    const data = await request('/maintenance/files/chmod', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), path: item.path, mode }) }, 'Changing permissions...');
    if (data) await listFiles(fileListPath);
  }

  async function deleteSelectedFiles() {
    if (selectedFilePaths.length === 0) return;
    if (!confirm(`Delete ${selectedFilePaths.length} selected item(s)?`)) return;
    const data = await request('/maintenance/files/delete', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), paths: selectedFilePaths }) }, 'Deleting selected files...');
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function transferFileItems(action, paths) {
    if (!selectedWebsiteId || !paths?.length) return;
    const verb = action === 'copy' ? 'Copy' : 'Move';
    const destination = prompt(`${verb} to folder:`, fileListPath || 'public_html');
    if (destination === null) return;
    const targetPath = destination.trim() || fileListPath || 'public_html';
    const data = await request(`/maintenance/files/${action}`, {
      method: 'POST',
      body: JSON.stringify({ website_id: Number(selectedWebsiteId), paths, destination_path: targetPath }),
    }, `${verb}ing files...`);
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function copySelectedFiles() {
    await transferFileItems('copy', selectedFilePaths);
  }

  async function moveSelectedFiles() {
    await transferFileItems('move', selectedFilePaths);
  }

  async function copyFileItem(item) {
    if (!item) return;
    await transferFileItems('copy', [item.path]);
  }

  async function moveFileItem(item) {
    if (!item) return;
    await transferFileItems('move', [item.path]);
  }

  async function archiveSelectedFiles() {
    if (selectedFilePaths.length === 0) return;
    const ext = archiveFormat === 'tar.gz' ? 'tar.gz' : 'zip';
    const outputName = prompt('Archive file name:', `archive-${Date.now()}.${ext}`);
    if (!outputName) return;
    const data = await request('/maintenance/files/archive', {
      method: 'POST',
      body: JSON.stringify({ website_id: Number(selectedWebsiteId), base_path: fileListPath || '', paths: selectedFilePaths, output_name: outputName, format: archiveFormat }),
    }, 'Creating archive...');
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  function upsertFileJob(job) {
    if (!job?.job_id) return;
    setFileJobs(prev => [job, ...prev.filter(item => item.job_id !== job.job_id)].slice(0, 6));
  }

  async function loadFileJob(jobId) {
    try {
      const res = await fetch(`${API}/maintenance/files/jobs/${jobId}`, { credentials: 'include' });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text || `HTTP ${res.status}` }; }
      if (!res.ok && handleAuthExpired(res.status, data.detail)) return null;
      if (!res.ok) return null;
      return data;
    } catch {
      return null;
    }
  }

  async function loadFileJobs(websiteId = selectedWebsiteId) {
    if (!websiteId) return;
    const data = await request(`/maintenance/files/jobs?website_id=${encodeURIComponent(websiteId)}`);
    if (data?.jobs) {
      setFileJobs(prev => [
        ...data.jobs,
        ...prev.filter(job => String(job.website_id) !== String(websiteId)),
      ].slice(0, 6));
    }
  }

  async function extractArchiveFile(path) {
    if (!path) return;
    const destination = prompt('Extract to folder:', fileListPath || '.');
    if (destination === null) return;
    const targetPath = destination || fileListPath || '.';
    const data = await request('/maintenance/files/extract', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), archive_path: path, destination_path: targetPath }) }, 'Starting extraction...');
    if (data?.job_id) upsertFileJob(data);
    else if (data) { await listFiles(targetPath === '.' ? '' : targetPath); await loadCurrentUser(); }
  }

  useEffect(() => {
    const activeJobs = fileJobs.filter(job => ['queued', 'running'].includes(job.status));
    if (activeJobs.length === 0) return undefined;

    const poll = async () => {
      for (const job of activeJobs) {
        const data = await loadFileJob(job.job_id);
        if (!data) continue;
        upsertFileJob(data);
        if (data.status === 'done') {
          setNotice(data.message || 'Extraction completed');
          await listFiles(data.destination_path || fileListPath);
          await loadCurrentUser();
        } else if (data.status === 'error') {
          setError(formatApiError(data.error, 'Extraction failed'));
        }
      }
    };

    const timer = window.setInterval(poll, 3000);
    return () => window.clearInterval(timer);
  }, [fileJobs]);

  useEffect(() => {
    if (page === 'files' && selectedWebsiteId) loadFileJobs(selectedWebsiteId);
  }, [page, selectedWebsiteId]);

  async function openWebsiteFileManager(site) {
    setNginxCustomEditing(null);
    setLogViewer(null);
    setTerminalViewer(null);
    setSelectedWebsiteId(String(site.id));
    navigateToPage('files');
    setFileListPath('public_html');
    setFileUploadDir('public_html');
    await listFiles('public_html', site.id);
  }

  async function uploadSiteFile(file) {
    if (!file) return;
    if (!selectedWebsiteId) { setError('Please select a website first.'); return; }
    const uploadDir = fileUploadDir.trim();
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
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Upload failed.')); return; }
      setNotice(`Uploaded ${file.name} to ${uploadDir || 'site root'}.`);
      if (String(fileListPath || '') === uploadDir) await listFiles(uploadDir);
      await loadCurrentUser();
    } catch (err) { setError('File upload failed.'); }
    finally { setLoading(''); }
  }

  async function createBackup() {
    const data = await request('/maintenance/backup', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId) }) }, 'Queueing backup...');
    if (data?.job_id) { setNotice('Backup queued. It will keep running on the server.'); await loadBackupJobs(); }
    else if (data?.backup_file) { setNotice(`Created backup: ${data.backup_file}`); await listBackups(); }
  }

  async function listBackups() {
    const data = await request(`/maintenance/backups/${selectedWebsiteId}`);
    if (data?.items) setBackups(data.items);
  }

  async function loadBackupJobs() {
    const data = await request('/maintenance/backup-jobs');
    if (data?.jobs) {
      const hasActive = data.jobs.some(job => ['queued', 'running'].includes(job.status));
      setBackupJobs(prev => {
        const hadActive = prev.some(job => ['queued', 'running'].includes(job.status));
        if (hadActive && !hasActive) {
          setTimeout(() => {
            if (selectedWebsiteId) listBackups();
            if (selectedBackupUserId) listUserBackups(selectedBackupUserId);
          }, 0);
        }
        return data.jobs;
      });
    }
  }

  async function refreshBackupArea() {
    await listBackups();
    await loadBackupJobs();
    if (selectedBackupUserId) await listUserBackups(selectedBackupUserId);
  }

  async function refreshUserBackupArea() {
    await loadUsers();
    await loadRestoreBackups();
    await loadBackupJobs();
    if (selectedBackupUserId) await listUserBackups(selectedBackupUserId);
  }

  async function refreshScheduledBackupArea() {
    await loadUsers();
    await loadSftpTargets();
    await loadBackupSchedules();
    await loadBackupJobs();
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
    const data = await request('/maintenance/user-backup', { method: 'POST', body: JSON.stringify(body) }, 'Queueing full user backup...');
    if (data?.job_id) { setNotice('Full user backup queued. It will keep running on the server.'); await loadBackupJobs(); }
    else if (data?.backup_file) {
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
    }, 'Queueing SFTP backup...');
    if (data?.job_id) {
      setNotice('SFTP backup queued. It will keep running on the server.');
      await loadBackupJobs();
    } else if (data?.remote_file) {
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
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Download failed.')); return; }
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
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Download failed.')); return; }
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
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Upload failed.')); return; }
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
      if (!res.ok || !data.url) { setError(formatApiError(data.detail, 'Cannot open phpMyAdmin.')); return; }
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } catch (err) { setError('Cannot open phpMyAdmin.'); }
    finally { setLoading(''); }
  }

  async function downloadDatabase(databaseId, databaseName) {
    try {
      setError(''); setLoading('Downloading database...');
      const res = await fetch(`${API}/databases/${databaseId}/download`, { credentials: 'include' });
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Download failed.')); return; }
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
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Upload failed.')); return; }
      if (data.backup_file) { setNotice(`Uploaded backup: ${data.backup_file}`); await listBackups(); }
    } catch (err) { setError('Upload backup failed.'); }
    finally { setLoading(''); }
  }

  async function checkService(name) {
    const data = await request('/services/action', { method: 'POST', body: JSON.stringify({ name, action: 'status' }) });
    setServiceStates(prev => ({ ...prev, [name]: data || { stdout: '', stderr: error || 'Cannot check', returncode: 1 } }));
    return data;
  }

  async function loadServiceNames() {
    const data = await request('/services/list');
    const names = data?.services?.length ? data.services : serviceNames;
    setServiceNames(names);
    return names;
  }

  async function checkAllServices() {
    setLoading('Checking services...');
    const names = await loadServiceNames();
    for (const name of names) { await checkService(name); }
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

  async function restorePhpDefaults() {
    if (!confirm(`Restore default PHP ${phpConfig.php_version} values?`)) return;
    const data = await request('/maintenance/php-config/defaults', {
      method: 'POST',
      body: JSON.stringify({ php_version: phpConfig.php_version }),
    }, 'Restoring PHP defaults...');
    if (data?.values) {
      setPhpConfig(prev => ({ ...prev, ...data.values }));
      setNotice(`Restored PHP ${phpConfig.php_version} defaults.`);
    }
  }

  async function loadPhpVersions() {
    const data = await request('/maintenance/php-versions', {}, 'Loading PHP versions...');
    if (data) setPhpVersions({
      installed: sortPhpVersions(data.installed || []),
      supported: sortPhpVersions(data.supported || []),
    });
  }

  async function installPhpVersion(version) {
    if (!confirm(`Install PHP ${version}? This will install php${version}-fpm via apt.`)) return;
    const data = await request(`/maintenance/php-versions/${version}/install`, { method: 'POST' }, `Installing PHP ${version}...`);
    if (data) { setNotice(`PHP ${version} installed successfully.`); await loadPhpVersions(); await loadServiceNames(); }
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
  async function deleteFirewallRule(numberOverride = firewallDeleteNumber) {
    const ruleNumber = String(numberOverride || '').trim();
    if (!ruleNumber) return;
    if (!confirm(`Delete UFW rule #${ruleNumber}?`)) return;
    await runFirewallAction(`/firewall/rules/${encodeURIComponent(ruleNumber)}`, { method: 'DELETE' }, 'Deleting rule...');
    setFirewallDeleteNumber('');
  }

  function parseFirewallBlocklistUrls(text) {
    const lines = String(text || '').split('\n');
    const urls = [];
    let inUrls = false;
    for (const raw of lines) {
      const line = raw.trim();
      if (line === 'URLs:') { inUrls = true; continue; }
      if (line === 'Networks:' || line === 'Timer:') break;
      if (inUrls && /^https?:\/\//i.test(line)) urls.push(line);
    }
    return urls;
  }

  async function loadFirewallBlocklists() {
    const data = await request('/firewall/blocklists', {}, 'Loading Nginx blocklists...');
    if (data) setFirewallBlocklists(data);
  }

  async function addFirewallBlocklistUrl() {
    const url = firewallBlocklistUrl.trim();
    if (!url) return;
    const data = await request('/firewall/blocklists', { method: 'POST', body: JSON.stringify({ url }) }, 'Adding Nginx blocklist URL...');
    if (data) {
      setNotice((data.stdout || data.stderr || 'Nginx blocklist URL added.').trim());
      setFirewallBlocklistUrl('');
      await loadFirewallBlocklists();
    }
  }

  async function deleteFirewallBlocklistUrl(url) {
    if (!confirm(`Delete blocklist URL?\n${url}`)) return;
    const data = await request('/firewall/blocklists/delete', { method: 'POST', body: JSON.stringify({ url }) }, 'Deleting Nginx blocklist URL...');
    if (data) {
      setNotice((data.stdout || data.stderr || 'Nginx blocklist URL removed.').trim());
      await loadFirewallBlocklists();
    }
  }

  async function updateFirewallBlocklistsNow() {
    const data = await request('/firewall/blocklists/update', { method: 'POST' }, 'Refreshing Nginx blocklists...');
    if (data) {
      setNotice((data.stdout || data.stderr || 'Nginx blocklists refreshed.').trim());
      await loadFirewall();
      await loadFirewallBlocklists();
    }
  }

  async function loadWafRules() {
    const data = await request('/waf/rules', {}, 'Loading WAF rules...');
    if (data) {
      setWafRules(data);
      const firstWebsiteId = selectedWafWebsiteId || selectedWebsiteId || websites[0]?.id || '';
      if (firstWebsiteId) {
        setSelectedWafWebsiteId(String(firstWebsiteId));
        await loadWebsiteWafConfig(firstWebsiteId, false);
      }
    }
  }

  async function loadWebsiteWafConfig(websiteId = selectedWafWebsiteId, showLoading = true) {
    if (!websiteId) {
      setWafSiteConfig(null);
      setHttpFloodForm({ http_flood_enabled: false, ...HTTP_FLOOD_DEFAULTS });
      return;
    }
    const data = await request(`/waf/websites/${websiteId}`, {}, showLoading ? 'Loading website WAF...' : '');
    if (data) {
      setSelectedWafWebsiteId(String(websiteId));
      setWafSiteConfig(data);
      setWafCustomRules(data.custom_rules || '');
      setHttpFloodForm({ http_flood_enabled: !!data.http_flood_enabled, ...normalizeHttpFloodConfig(data.http_flood_config) });
    }
  }

  function toggleWafDefaultRule(ruleId, enabled) {
    setWafSiteConfig(prev => {
      if (!prev) return prev;
      const current = new Set(prev.enabled_rule_ids || []);
      if (enabled) current.add(ruleId); else current.delete(ruleId);
      return {
        ...prev,
        enabled_rule_ids: Array.from(current),
        default_rules: (prev.default_rules || []).map(rule => rule.id === ruleId ? { ...rule, enabled } : rule),
      };
    });
  }

  async function saveWebsiteWafRules() {
    if (!selectedWafWebsiteId || !wafSiteConfig) return;
    const data = await request(`/waf/websites/${selectedWafWebsiteId}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled_rule_ids: wafSiteConfig.enabled_rule_ids || [], custom_rules: wafCustomRules }),
    }, 'Saving website WAF rules...');
    if (data) {
      setWafSiteConfig(data);
      setWafCustomRules(data.custom_rules || '');
      setNotice(data.message || 'Website WAF rules saved.');
      await refreshAll();
    }
  }

  async function saveWebsiteHttpFlood() {
    if (!selectedWafWebsiteId || !wafSiteConfig) return;
    const config = normalizeHttpFloodConfig(httpFloodForm);
    const data = await request(`/websites/${selectedWafWebsiteId}/http-flood`, {
      method: 'PATCH',
      body: JSON.stringify({ http_flood_enabled: !!httpFloodForm.http_flood_enabled, ...config }),
    }, 'Saving HTTP Flood settings...');
    if (data) {
      setNotice(`HTTP Flood settings saved for ${data.domain}.`);
      await refreshAll();
      await loadWebsiteWafConfig(selectedWafWebsiteId, false);
    }
  }

  async function loadUpdates(force = false) {
    const data = await request(`/updates/status${force ? '?refresh=true' : ''}`, {}, 'Loading update status...');
    if (data) setUpdatesStatus(data);
  }

  async function toggleUpdateLog() {
    if (!showUpdateLog && !updatesStatus) await loadUpdates();
    setShowUpdateLog(prev => !prev);
  }

  async function runOsUpdate() {
    if (!confirm('Run apt-get update && apt-get upgrade now?')) return;
    setOsUpdating(true);
    const data = await request('/updates/os/run', { method: 'POST' }, 'Updating OS packages...');
    setOsUpdating(false);
    if (data) { setNotice((data.stdout || data.stderr || 'OS update completed.').trim()); if (showUpdateLog) await loadUpdates(); }
  }

  async function saveOsAutoUpdate() {
    const data = await request('/updates/os/auto', { method: 'POST', body: JSON.stringify(osAutoUpdate) }, 'Saving OS auto update...');
    if (data) { setNotice((data.stdout || data.stderr || 'OS auto update saved.').trim()); if (showUpdateLog) await loadUpdates(); }
  }

  async function runPanelUpdate() {
    if (!confirm('Update BPanel from GitHub now? The API may restart.')) return;
    setPanelUpdating(true);
    const data = await request('/updates/panel/run', { method: 'POST' }, 'Updating BPanel...');
    setPanelUpdating(false);
    if (data) { setNotice((data.stdout || data.stderr || 'Panel update completed.').trim()); await loadUpdates(); }
  }

  async function savePanelAutoUpdate() {
    const data = await request('/updates/panel/auto', { method: 'POST', body: JSON.stringify(panelAutoUpdate) }, 'Saving panel auto update...');
    if (data) { setNotice((data.stdout || data.stderr || 'Panel auto update saved.').trim()); if (showUpdateLog) await loadUpdates(); }
  }

  useEffect(() => {
    if (isAuthenticated) {
      refreshAll();
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (standaloneEditor) return undefined;
    const syncPageFromLocation = () => setPage(pageFromPathname(window.location.pathname));
    syncPageFromLocation();
    window.addEventListener('popstate', syncPageFromLocation);
    return () => window.removeEventListener('popstate', syncPageFromLocation);
  }, [standaloneEditor]);

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

  useEffect(() => { if (selectedWebsiteId && page === 'backups') { listBackups(); loadBackupJobs(); } }, [selectedWebsiteId, page]);

  useEffect(() => { if (selectedWebsiteId && page === 'cron') listCron(); }, [selectedWebsiteId, page]);

  useEffect(() => { if (selectedWebsiteId && page === 'files') listFiles('public_html'); }, [selectedWebsiteId, page]);

  useEffect(() => { if (selectedBackupUserId && page === 'backups') listUserBackups(selectedBackupUserId); }, [selectedBackupUserId, page]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'backups') return undefined;
    loadBackupJobs();
    const timer = setInterval(loadBackupJobs, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page, selectedWebsiteId, selectedBackupUserId]);

  useEffect(() => {
    if (isAuthenticated && page === 'users') loadUsers();
    if (isAuthenticated && page === 'php') loadPhpConfig();
    if (isAuthenticated && page === 'firewall') { loadFirewall(); loadFirewallBlocklists(); }
    if (isAuthenticated && page === 'waf') loadWafRules();
    if (isAuthenticated && page === 'updates' && currentUser?.role === 'admin') loadUpdates();
    if (isAuthenticated && page === 'security') loadTwoFactorStatus();
    if (isAuthenticated && page === 'settings') loadPanelSettings();
    if (isAuthenticated && page === 'backups' && currentUser?.role === 'admin') { loadUsers(); loadSftpTargets(); loadBackupSchedules(); loadRestoreBackups(); }
  }, [isAuthenticated, page, currentUser?.role]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'waf' || selectedWafWebsiteId || websites.length === 0) return;
    loadWebsiteWafConfig(websites[0].id, false);
  }, [isAuthenticated, page, selectedWafWebsiteId, websites.length]);

  useEffect(() => { setMobileMenuOpen(false); }, [page]);

  useEffect(() => {
    if (SETTINGS_PAGE_KEYS.includes(page)) setSettingsMenuOpen(true);
  }, [page]);

  const isAdmin = currentUser?.role === 'admin';

  function roleLabel(role) {
    return role === 'admin' ? 'Admin' : 'End user';
  }

  const mainNavItems = [
    ['dashboard', 'Dashboard', Home],
    ['websites', 'Websites', Globe],
    ['ssl', 'SSL', Lock],
    ['databases', 'Database', Database],
    ['cron', 'Cron', Clock],
    ['files', 'File manager', FolderOpen],
    ['backups', 'Backups', Archive],
    ...(isAdmin ? [['users', 'Panel users', Users]] : []),
  ];

  const settingsNavItems = [
    ...(isAdmin ? [['settings', 'Panel settings', SettingsIcon]] : []),
    ['security', 'Security', Shield],
    ...(isAdmin ? [['php', 'PHP config', Code2]] : []),
    ...(isAdmin ? [['firewall', 'Firewall', Shield]] : []),
    ...(isAdmin ? [['waf', 'WAF', Shield]] : []),
    ...(isAdmin ? [['updates', 'Updates', RefreshCw]] : []),
    ['services', 'Services Status', Server],
  ];

  const navItems = [...mainNavItems, ...settingsNavItems];
  const currentSite = websites.find(site => String(site.id) === String(selectedWebsiteId));
  const activeNavItem = navItems.find(([key]) => key === page) || navItems[0];
  const settingsIsActive = SETTINGS_PAGE_KEYS.includes(page);

  function renderNotifications() {
    const errorMessage = formatApiError(error, '').trim();
    const noticeMessage = formatApiError(notice, '').trim();
    if (!errorMessage && !noticeMessage) return null;
    return <div className="app-toast-stack" aria-label="Notifications">
      <NotificationToast type="error" message={errorMessage} onClose={() => setError('')} />
      <NotificationToast type="success" message={noticeMessage} onClose={() => setNotice('')} />
    </div>;
  }

  function websiteUrl(site) {
    const value = (site?.domain || '').trim();
    if (/^https?:\/\//i.test(value)) return value;
    return `${site?.ssl_enabled ? 'https' : 'http'}://${value}`;
  }

  function parentFilePath(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    parts.pop();
    return parts.join('/');
  }

  function fileBreadcrumbs(path) {
    const parts = String(path || '').split('/').filter(Boolean);
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
    const editableDotfiles = new Set(['.env', '.env.example', '.htaccess', '.user.ini', '.gitignore', '.gitattributes']);
    return editableDotfiles.has(name) || /\.(txt|md|json|css|js|jsx|ts|tsx|html|htm|xml|yml|yaml|ini|conf|log|php|env|htaccess)$/.test(name) || !name.includes('.');
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
              <span>Root <strong>{site.document_root || 'public_html'}</strong></span>
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

  function renderNginxEditor() {
    if (!nginxCustomEditing) return null;
    const fullConfig = nginxCustomEditing.mode === 'full';
    return <section className="section nginx-modal inline-nginx-editor">
      <div className="section-title">
        <div className="nginx-config-title">
          <h2>{fullConfig ? 'Full Nginx config' : 'Custom Nginx'} - {nginxCustomEditing.domain}</h2>
          <p className="hint">{fullConfig
            ? 'This is read-only. BPanel manages the main vhost template.'
            : 'These directives are written to a separate include file and survive BPanel template updates.'}</p>
        </div>
        <div className="actions">
          {!fullConfig && isAdmin && <button className="secondary-light" disabled={!!loading} onClick={viewFullNginxConfig}><FileText size={14}/> View all</button>}
          <button className="secondary-light" onClick={() => setNginxCustomEditing(null)}><X size={14}/> Close</button>
        </div>
      </div>
      <textarea
        className="code-editor"
        value={nginxCustomEditing.content}
        onChange={e => setNginxCustomEditing(prev => ({ ...prev, content: e.target.value }))}
        placeholder={fullConfig
          ? `server {\n    listen 80;\n    server_name ${nginxCustomEditing.domain};\n}`
          : `try_files $uri $uri/ @seohburl;\nlocation @seohburl {\n    rewrite ^/(.+)$ /index.php?/$1 last;\n}`}
        spellCheck={false}
        rows={14}
        readOnly={fullConfig}
      />
      <div className="actions">
        {!fullConfig && <button disabled={!!loading} onClick={saveNginxCustom}>Save and reload Nginx</button>}
        {!fullConfig && <button className="secondary-light" disabled={!!loading} onClick={resetNginxDefault}><RotateCcw size={14}/> Reset custom</button>}
        <button className="secondary-light" disabled={!!loading} onClick={() => setNginxCustomEditing(null)}>{fullConfig ? 'Close' : 'Cancel'}</button>
      </div>
    </section>;
  }

  function renderWebsiteLogViewer() {
    if (!logViewer) return null;
    return <section className="section nginx-modal log-viewer">
      <div className="section-title">
        <div className="nginx-config-title">
          <h2>Nginx logs - {logViewer.domain}</h2>
          <p className="hint">{logViewer.path || `/var/log/nginx/${logViewer.domain}.${logViewer.kind}.log`}</p>
        </div>
        <button className="secondary-light" onClick={() => setLogViewer(null)}><X size={14}/> Close</button>
      </div>
      <div className="log-toolbar">
        <div className="segmented-control">
          <button className={logViewer.kind === 'access' ? 'active' : ''} disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, 'access', logViewer.lines, logViewer.domain)}>Access</button>
          <button className={logViewer.kind === 'error' ? 'active' : ''} disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, 'error', logViewer.lines, logViewer.domain)}>Error</button>
        </div>
        <select value={logViewer.lines} onChange={e => loadWebsiteLog(logViewer.id, logViewer.kind, Number(e.target.value), logViewer.domain)} disabled={!!loading}>
          <option value={100}>100 lines</option>
          <option value={200}>200 lines</option>
          <option value={500}>500 lines</option>
          <option value={1000}>1000 lines</option>
          <option value={2000}>2000 lines</option>
        </select>
        <button disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, logViewer.kind, logViewer.lines, logViewer.domain)}><RefreshCw size={14}/> Refresh</button>
      </div>
      <pre className="log-output">{logViewer.exists ? (logViewer.content || 'Log is empty.') : 'Log file has not been created yet.'}</pre>
    </section>;
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
            <option value="php">PHP</option>
          </select>
          <select value={phpVersion} onChange={e => setPhpVersion(e.target.value)}>
            {phpVersions.installed.map(v => <option key={v} value={v}>PHP {v}</option>)}
          </select>
          {wpFieldsEnabled && <input value={adminEmail} onChange={e => setAdminEmail(e.target.value)} placeholder="admin@domain.com" />}
          {wpFieldsEnabled && <input value={wpAdminUser} onChange={e => setWpAdminUser(e.target.value)} placeholder="WP admin user" />}
          {wpFieldsEnabled && <input value={wpAdminPassword} onChange={e => setWpAdminPassword(e.target.value)} placeholder="WP admin password" type="password" />}
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
          : 'A PHP-FPM vhost will be created with public_html/ folder. Upload your PHP, HTML, or static files via File Manager.'}</p>
      </section>
      <section className="section">
        <div className="section-title">
          <h2>Website list</h2>
          <button disabled={!!loading} onClick={refreshAll}><RefreshCw size={15}/> Refresh</button>
        </div>
        {websites.length === 0 && <EmptyState icon={Globe} message="No websites yet." />}
        <div className="site-grid">
          {websites.map(site => <div className="site-stack" key={site.id}>
          <article className="site-card">
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
              {site.http_flood_enabled && <span className="badge ok">HTTP Flood</span>}
            </div>
            <div className="site-actions" aria-label={`Website actions for ${site.domain}`}>
              <div className="site-mode-actions">
                <select
                  value={websiteAppTypes[site.id] || site.app_type || 'wordpress'}
                  onChange={e => setWebsiteAppTypes(prev => ({ ...prev, [site.id]: e.target.value }))}
                  title="Website mode"
                  aria-label={`Website mode for ${site.domain}`}
                  disabled={!!loading}
                >
                  <option value="wordpress">WordPress</option>
                  <option value="php">PHP</option>
                  <option value="static">Static</option>
                </select>
                <button
                  className="site-icon-button secondary-light"
                  data-tooltip="Save mode"
                  title="Save website mode"
                  aria-label={`Save website mode for ${site.domain}`}
                  disabled={
                    !!loading
                    || (websiteAppTypes[site.id] || site.app_type || 'wordpress') === (site.app_type || 'wordpress')
                  }
                  onClick={() => changeWebsiteAppType(site)}
                ><Save size={15}/></button>
              </div>
              <div className="site-root-actions">
                <input
                  value={websiteDocumentRoots[site.id] ?? site.document_root ?? 'public_html'}
                  onChange={e => setWebsiteDocumentRoots(prev => ({ ...prev, [site.id]: e.target.value }))}
                  placeholder="public_html/public"
                  title="Document root relative to website root"
                  aria-label={`Document root for ${site.domain}`}
                  disabled={!!loading}
                />
                <button
                  className="site-icon-button secondary-light"
                  data-tooltip="Save root"
                  title="Save document root"
                  aria-label={`Save document root for ${site.domain}`}
                  disabled={
                    !!loading
                    || !(websiteDocumentRoots[site.id] ?? site.document_root ?? 'public_html').trim()
                    || (websiteDocumentRoots[site.id] ?? site.document_root ?? 'public_html').trim() === (site.document_root || 'public_html')
                  }
                  onClick={() => changeWebsiteDocumentRoot(site)}
                ><Save size={15}/></button>
              </div>
              {site.app_type !== 'static' && <div className="site-php-actions">
                <select
                  value={websitePhpVersions[site.id] || site.php_version || '8.3'}
                  onChange={e => setWebsitePhpVersions(prev => ({ ...prev, [site.id]: e.target.value }))}
                  title="PHP version"
                  aria-label={`PHP version for ${site.domain}`}
                >
                  {phpVersions.installed.map(v => <option key={v} value={v}>PHP {v}</option>)}
                </select>
                <button
                  className="site-icon-button secondary-light"
                  data-tooltip="Change PHP"
                  title="Change PHP"
                  aria-label={`Change PHP version for ${site.domain}`}
                  disabled={!!loading || (websitePhpVersions[site.id] || site.php_version) === site.php_version}
                  onClick={() => changeWebsitePhpVersion(site)}
                ><RefreshCw size={15}/></button>
              </div>}
              <div className="site-feature-actions">
                <button className="site-icon-button secondary-light" data-tooltip="Files" title="Files" aria-label={`Open file manager for ${site.domain}`} disabled={!!loading} onClick={() => openWebsiteFileManager(site)}><FolderOpen size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Logs" title="Logs" aria-label={`View logs for ${site.domain}`} disabled={!!loading} onClick={() => openWebsiteLogs(site)}><FileText size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Terminal" title="Terminal" aria-label={`Open terminal for ${site.domain}`} disabled={!!loading} onClick={() => openWebsiteTerminal(site)}><TerminalIcon size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Custom Nginx" title="Custom Nginx" aria-label={`Edit Custom Nginx for ${site.domain}`} disabled={!!loading} onClick={() => openNginxCustom(site)}><Code2 size={15}/></button>
                <button className="site-icon-button danger" data-tooltip="Delete" title="Delete" aria-label={`Delete ${site.domain}`} disabled={!!loading} onClick={() => deleteWebsite(site.id)}><Trash2 size={15}/></button>
              </div>
            </div>
          </article>
          {nginxCustomEditing?.id === site.id && renderNginxEditor()}
          {logViewer?.id === site.id && renderWebsiteLogViewer()}
          </div>)}
        </div>
      </section>
      {terminalViewer && <section className="section terminal-modal">
        <div className="section-title">
          <h2>Terminal - {terminalViewer.domain}</h2>
          <button className="secondary-light" onClick={() => setTerminalViewer(null)}><X size={14}/> Close</button>
        </div>
        <div style={{ height: '500px', marginTop: '8px' }}>
          <Terminal websiteId={terminalViewer.id} apiBase={API} />
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
    function copyToClipboard(text, field) {
      const doCopy = navigator.clipboard ? navigator.clipboard.writeText(text) : new Promise((resolve, reject) => {
        try { const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); resolve(); } catch(e) { reject(e); }
      });
      doCopy.then(() => { setCopiedField(field); setTimeout(() => setCopiedField(null), 2000); }).catch(() => setError('Copy failed.'));
    }
    return <section className="section">
      <div className="section-title">
        <h2>Databases</h2>
        <button disabled={!!loading} onClick={refreshAll}><RefreshCw size={15}/> Refresh</button>
      </div>
      <div className="form-row">
        <input value={newDatabase.db_name} onChange={e => setNewDatabase(prev => ({ ...prev, db_name: e.target.value }))} placeholder="database_name" />
        <input value={newDatabase.db_user} onChange={e => setNewDatabase(prev => ({ ...prev, db_user: e.target.value }))} placeholder="db_user (default = db_name)" />
        <input value={newDatabase.db_password} onChange={e => setNewDatabase(prev => ({ ...prev, db_password: e.target.value }))} placeholder="password (min 12 chars)" />
        <button className="mini secondary-light" title="Generate random password" onClick={() => setNewDatabase(prev => ({ ...prev, db_password: generateRandomPassword() }))}><Dices size={13}/></button>
        <button disabled={!!loading || !newDatabase.db_name.trim()} onClick={createDatabase}><Plus size={15}/> Create database</button>
      </div>
      {createdDbInfo && <div className="info-box db-created-box">
        <div className="db-created-head"><strong>Database created successfully</strong><button className="mini secondary-light" onClick={() => setCreatedDbInfo(null)}><X size={13}/></button></div>
        <div className="db-created-grid">
          <label>Database</label><span>{createdDbInfo.db_name} <button className="mini secondary-light" title={copiedField === 'db_name' ? 'Copied!' : 'Copy'} onClick={() => copyToClipboard(createdDbInfo.db_name, 'db_name')}>{copiedField === 'db_name' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
          <label>User</label><span>{createdDbInfo.db_user} <button className="mini secondary-light" title={copiedField === 'db_user' ? 'Copied!' : 'Copy'} onClick={() => copyToClipboard(createdDbInfo.db_user, 'db_user')}>{copiedField === 'db_user' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
          <label>Password</label><span><code>{createdDbInfo.db_password}</code> <button className="mini secondary-light" title={copiedField === 'db_password' ? 'Copied!' : 'Copy'} onClick={() => copyToClipboard(createdDbInfo.db_password, 'db_password')}>{copiedField === 'db_password' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
        </div>
      </div>}
      {databases.length === 0 && !createdDbInfo && <EmptyState icon={Database} message="No databases found." />}
      <div className="table">
        {databases.map(db => {
          return <div className="row db-row" key={db.id}>
          <span><strong>{db.db_name}</strong></span>
          <span style={{color:'var(--text-muted)'}}>{db.db_user}</span>
          <button disabled={!!loading} onClick={() => openPhpMyAdmin(db.id)}>phpMyAdmin</button>
          <button disabled={!!loading} onClick={() => downloadDatabase(db.id, db.db_name)}><Download size={14}/> SQL</button>
          <button disabled={!!loading} onClick={() => changeDbPassword(db.id)}><KeyRound size={14}/> Password</button>
          <button className="danger" disabled={!!loading} onClick={() => deleteDatabase(db.id, db.db_name)}><Trash2 size={14}/></button>
        </div>})}
      </div>
      <p className="hint">Click phpMyAdmin to sign in directly. Token expires after 60s.</p>
    </section>;
  }

  function renderCron() {
    return <section className="section">
      <div className="section-title">
        <div><h2>Cron manager</h2></div>
        <button disabled={!selectedWebsiteId || !!loading} onClick={listCron}><RefreshCw size={14}/> Refresh</button>
      </div>
      <div className="cron-form">
        <WebsiteSelect />
        <input value={cronSchedule} onChange={e => setCronSchedule(e.target.value)} placeholder="*/15 * * * *" />
        <input value={cronCommand} onChange={e => setCronCommand(e.target.value)} placeholder="command" />
        <button disabled={!selectedWebsiteId || !!loading} onClick={addCron}><Plus size={14}/> Add cron</button>
      </div>
      {selectedWebsiteId && <p className="hint">Cron runs as <strong>{cronUser || currentSite?.linux_user || 'www-data'}</strong> for the selected website.</p>}
      <div className="cron-list">
        {selectedWebsiteId && cronItems.length === 0 && <EmptyState icon={Clock} message="No cron jobs found for this website." />}
        {cronItems.map(item => <div className="cron-item" key={`${item.index}-${item.line}`}>
          <span className="badge">#{item.index}</span>
          <span><strong>{item.schedule}</strong><small>{item.command || item.line}</small></span>
          <button className="mini danger" disabled={!!loading} onClick={() => deleteCron(item.index)}><Trash2 size={13}/></button>
        </div>)}
      </div>
    </section>;
  }

  function renderFiles() {
    const allSelected = files.length > 0 && selectedFilePaths.length === files.length;
    const visibleFileJobs = fileJobs.filter(job => String(job.website_id) === String(selectedWebsiteId)).slice(0, 4);
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
              <span>Root: <strong>{currentSite.root_path}{fileListPath ? `/${fileListPath}` : ''}</strong></span>
              {currentUser && !isAdmin && <span>Storage: <strong>{storageUsageText(currentUser)}</strong></span>}
            </div>}
            <div className="path-pill breadcrumb-line">
              <button className="crumb" disabled={!selectedWebsiteId || fileListPath === ''} onClick={() => listFiles('')}>root</button>
              {fileBreadcrumbs(fileListPath).map(crumb => <button className="crumb" key={crumb.path} onClick={() => listFiles(crumb.path)}>{crumb.label}</button>)}
            </div>
            <div className="file-toolbar">
              <button disabled={!selectedWebsiteId || fileListPath === '' || !!loading} onClick={() => listFiles(parentFilePath(fileListPath))}>Up</button>
              <button disabled={!selectedWebsiteId || !!loading} onClick={makeFileDirectory}><Plus size={14}/> Folder</button>
              <button disabled={!selectedWebsiteId || !!loading} onClick={makeFile}><FileText size={14}/> File</button>
              <label className={`upload-button ${(!selectedWebsiteId || !!loading) ? 'disabled' : ''}`}>
                <Upload size={14}/> Upload
                <input type="file" disabled={!selectedWebsiteId || !!loading} onChange={e => { uploadSiteFile(e.target.files?.[0]); e.target.value = ''; }} />
              </label>
              <select value={archiveFormat} onChange={e => setArchiveFormat(e.target.value)} disabled={!selectedWebsiteId || !!loading}>
                <option value="zip">zip</option>
                <option value="tar.gz">tar.gz</option>
              </select>
              <button disabled={selectedFilePaths.length === 0 || !!loading} onClick={copySelectedFiles}><Copy size={14}/> Copy</button>
              <button disabled={selectedFilePaths.length === 0 || !!loading} onClick={moveSelectedFiles}><MoveRight size={14}/> Move</button>
              <button disabled={selectedFilePaths.length === 0 || !!loading} onClick={archiveSelectedFiles}><Archive size={14}/> Archive</button>
              <button className="danger" disabled={selectedFilePaths.length === 0 || !!loading} onClick={deleteSelectedFiles}><Trash2 size={14}/> Delete</button>
            </div>
            {visibleFileJobs.length > 0 && <div className="file-job-list">
              {visibleFileJobs.map(job => <div className={`file-job ${job.status}`} key={job.job_id}>
                <Clock size={14}/>
                <span><strong>{job.archive_path?.split('/').pop() || 'Archive'}</strong> {job.status === 'done' ? 'completed' : job.status === 'error' ? 'failed' : job.status}</span>
                {job.error && <small>{job.error}</small>}
              </div>)}
            </div>}
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
              <span className="file-mode">{item.mode || '---'}</span>
              <span className="file-size">{item.is_dir ? 'Folder' : formatBytes(item.size)}</span>
              <div className="file-row-actions">
                {!item.is_dir && isTextEditable(item) && <button className="mini secondary-light" disabled={!!loading} onClick={() => openFileEditorTab(item.path)}>Edit</button>}
                {!item.is_dir && <button className="mini secondary-light" disabled={!!loading} onClick={() => downloadFile(item.path)}><Download size={13}/></button>}
                {isArchiveFile(item) && <button className="mini secondary-light" disabled={!!loading} onClick={() => extractArchiveFile(item.path)}>Extract</button>}
                <button className="mini secondary-light" disabled={!!loading} onClick={() => chmodFileItem(item)}>Chmod</button>
                <button className="mini secondary-light" title="Copy" aria-label="Copy" disabled={!!loading} onClick={() => copyFileItem(item)}><Copy size={13}/></button>
                <button className="mini secondary-light" title="Move" aria-label="Move" disabled={!!loading} onClick={() => moveFileItem(item)}><MoveRight size={13}/></button>
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
    const jobTitle = job => ({ site_backup: 'Website backup', user_backup: 'Full user backup', sftp_backup: 'SFTP backup' }[job.kind] || 'Backup task');
    const jobDetail = job => job.error || job.remote_file || job.backup_file || job.message || job.status;
    const backupTabs = isAdmin
      ? [
        ['website', 'Backup website', Globe],
        ['user', 'Backup user', Users],
        ['schedule', 'Scheduled backups', Clock],
        ['destination', 'Backup Destination', Network],
      ]
      : [['website', 'Backup website', Globe]];
    const activeBackupTab = backupTabs.some(([id]) => id === backupTab) ? backupTab : 'website';

    return <section className="section backups-page">
      <h2>Backups</h2>
      <div className="segmented-control backup-tabs" role="tablist" aria-label="Backup sections">
        {backupTabs.map(([id, label, Icon]) => <button
          key={id}
          type="button"
          role="tab"
          aria-selected={activeBackupTab === id}
          className={activeBackupTab === id ? 'active' : ''}
          onClick={() => setBackupTab(id)}
        ><Icon size={14}/>{label}</button>)}
      </div>
      {backupJobs.length > 0 && <div className="backup-job-list">
        {backupJobs.map(job => <div className={`backup-job ${job.status}`} key={job.job_id}>
          <Clock size={14}/>
          <span><strong>{jobTitle(job)}</strong><small>{jobDetail(job)}</small></span>
          <span className={job.status === 'done' ? 'badge ok' : job.status === 'error' ? 'badge bad' : 'badge'}>{job.status}</span>
        </div>)}
      </div>}

      {activeBackupTab === 'website' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>Backup website</h3><p className="hint">Backups include website source files and a database SQL export.</p></div>
        </div>
        <WebsiteSelect />
        <div className="actions backup-toolbar">
          <button disabled={!selectedWebsiteId || !!loading} onClick={createBackup}><Plus size={14}/> Create backup</button>
          <button disabled={!selectedWebsiteId || !!loading} onClick={refreshBackupArea}><RefreshCw size={14}/> Refresh</button>
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
      </div>}

      {isAdmin && activeBackupTab === 'user' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>Backup user</h3><p className="hint">Includes the panel user, all owned websites, source files, database dumps, and restore metadata.</p></div>
          <button disabled={!!loading} onClick={refreshUserBackupArea}><RefreshCw size={14}/> Reload</button>
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
          <button disabled={!selectedBackupUserId || !!loading} onClick={createUserBackup}><Archive size={14}/> Create backup</button>
        </div>
        {selectedBackupUser && <p className="hint">Current user: <strong>{selectedBackupUser.username}</strong></p>}
        <div className="actions backup-subactions">
          <button disabled={!selectedBackupUserId || !!loading} onClick={() => listUserBackups()}><RefreshCw size={14}/> Refresh list</button>
        </div>
        {selectedBackupUserId && userBackups.length === 0 && <EmptyState icon={Archive} message="No user backups found." />}
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

        <div className="section-title restore-title backup-panel-heading backup-subtitle">
          <div><h3>Restore folder</h3><p className="hint">{restoreBackupDir || '/var/backups/bpanel/users/restore'}</p></div>
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

      </div>}

      {isAdmin && activeBackupTab === 'schedule' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>Scheduled backups</h3><p className="hint">Run full user backups automatically with optional off-server destination.</p></div>
          <button disabled={!!loading} onClick={refreshScheduledBackupArea}><RefreshCw size={14}/> Refresh</button>
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
          <button disabled={(!newBackupSchedule.all_users && (!newBackupSchedule.user_ids || newBackupSchedule.user_ids.length === 0)) || !!loading} onClick={createBackupSchedule}><Clock size={14}/> Schedule</button>
        </div>
        <div className="backup-list">
          {backupSchedules.map(item => {
            const scheduleTarget = sftpTargets.find(target => target.id === item.target_id);
            return <div className="backup-item" key={item.id}>
              <span>{scheduleUserLabel(item)} - {item.schedule}{scheduleTarget ? ` - ${scheduleTarget.name}` : ''}<small>{item.last_status}: {item.last_message || 'not run yet'}</small></span>
              <button className="danger" disabled={!!loading} onClick={() => deleteBackupSchedule(item.id)}><Trash2 size={14}/></button>
            </div>;
          })}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'destination' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>Backup Destination</h3><p className="hint">Manage SFTP destinations used for off-server backup copies.</p></div>
          <button disabled={!!loading} onClick={loadSftpTargets}><RefreshCw size={14}/> Refresh</button>
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
        {sftpTargets.length === 0 && <EmptyState icon={Network} message="No backup destinations found." />}
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
        {serviceNames.map(name => {
          const state = serviceStates[name];
          const text = `${state?.stdout || ''} ${state?.stderr || ''}`;
          const active = text.includes('active (running)');
          const inactive = text.includes('inactive') || text.includes('failed');
          return <div className="service-card" key={name}>
            <div><strong>{name}</strong><span className={active ? 'badge ok' : inactive ? 'badge bad' : 'badge'}>{active ? 'Running' : inactive ? 'Stopped' : '...'}</span></div>
            <small>Auto-refreshes every 10s</small>
            {isAdmin && <div className="service-actions">
              <button onClick={() => runServiceAction(name, 'start')}><Play size={13}/> Start</button>
              {!['bpanel-api', 'redis-server'].includes(name) && <button onClick={() => runServiceAction(name, 'stop')}><Square size={13}/> Stop</button>}
              <button onClick={() => runServiceAction(name, 'restart')}><RotateCcw size={13}/> Restart</button>
            </div>}
          </div>;
        })}
      </div>
    </section>;
  }

  function renderPhpConfig() {
    if (!isAdmin) return <section className="section"><h2>PHP config</h2><p className="hint">You do not have permission to edit PHP config.</p></section>;
    const notInstalled = sortPhpVersions(phpVersions.supported.filter(v => !phpVersions.installed.includes(v)));
    return <section className="section">
      <div className="section-title">
        <div><h2>PHP Configuration</h2></div>
      </div>
      <div className="user-create-card">
        <label><span>PHP version</span><select value={phpConfig.php_version} onChange={e => { const v = e.target.value; setPhpConfig(prev => ({ ...prev, php_version: v })); loadPhpConfig(v); }}>
          {phpVersions.installed.map(v => <option key={v} value={v}>PHP {v}</option>)}
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
        <button className="secondary-light" disabled={!!loading} onClick={restorePhpDefaults}><RotateCcw size={14}/> Restore defaults</button>
        <button disabled={!!loading} onClick={updatePhpConfig}>Save</button>
      </div>
      {notInstalled.length > 0 && <div className="user-create-card" style={{ marginTop: 16 }}>
        <h3>Install PHP</h3>
        <div className="php-install-grid">
          {notInstalled.map(v => <button key={v} disabled={!!loading} onClick={() => installPhpVersion(v)}>+ PHP {v}</button>)}
        </div>
      </div>}
    </section>;
  }

  function renderFirewall() {
    if (!isAdmin) return <section className="section"><h2>Firewall</h2><p className="hint">No permission.</p></section>;
    const firewallText = firewallStatus?.stdout || firewallStatus?.stderr || 'Click Refresh to load status.';
    const blocklistText = firewallBlocklists?.stdout || firewallBlocklists?.stderr || 'No blocklist status loaded.';
    const blocklistUrls = parseFirewallBlocklistUrls(blocklistText);
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
          <pre>{firewallText}</pre>
          <div className="firewall-delete-inline">
            <label><span>Delete UserZone #</span><input value={firewallDeleteNumber} onChange={e => setFirewallDeleteNumber(e.target.value)} placeholder="12" inputMode="numeric" /></label>
            <button className="danger" disabled={!!loading || !firewallDeleteNumber} onClick={() => deleteFirewallRule()}>Delete</button>
          </div>
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
        <div className="section-title">
          <div><h2>Nginx IP blocklist URLs</h2><p className="hint">TXT files are fetched daily at 01:00 and enforced by Nginx, so large lists do not create thousands of UFW rules.</p></div>
          <button disabled={!!loading} onClick={loadFirewallBlocklists}><RefreshCw size={14}/> Refresh</button>
        </div>
        <div className="firewall-form firewall-blocklist-form">
          <label><span>TXT URL</span><input value={firewallBlocklistUrl} onChange={e => setFirewallBlocklistUrl(e.target.value)} placeholder="https://example.com/blocklist.txt" /></label>
          <button disabled={!!loading || !firewallBlocklistUrl.trim()} onClick={addFirewallBlocklistUrl}><Plus size={14}/> Add URL</button>
          <button className="secondary-light" disabled={!!loading} onClick={updateFirewallBlocklistsNow}><RefreshCw size={14}/> Update now</button>
        </div>
        {blocklistUrls.length > 0 && <div className="table firewall-blocklist-table">
          {blocklistUrls.map(url => <div className="firewall-rule" key={url}>
            <span>{url}</span>
            <div className="firewall-rule-actions"><button className="danger" disabled={!!loading} onClick={() => deleteFirewallBlocklistUrl(url)}><Trash2 size={14}/> Delete</button></div>
          </div>)}
        </div>}
        <div className="info-box firewall-status"><strong>Nginx blocklist status</strong><pre>{blocklistText}</pre></div>
      </section>
    </>;
  }

  function renderWaf() {
    if (!isAdmin) return <section className="section"><h2>WAF</h2><p className="hint">No permission.</p></section>;
    const statusText = wafRules.status?.stdout || wafRules.status?.stderr || 'Click Refresh to load WAF status.';
    const selectedSite = websites.find(site => String(site.id) === String(selectedWafWebsiteId));
    const groupedRules = (wafSiteConfig?.default_rules || wafRules.default_rule_definitions || []).reduce((groups, rule) => {
      const category = rule.category || 'General';
      groups[category] = groups[category] || [];
      groups[category].push(rule);
      return groups;
    }, {});
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>WAF</h2><p className="hint">WAF engine is installed by the panel. Rules are configured per website.</p></div>
          <button disabled={!!loading} onClick={loadWafRules}><RefreshCw size={14}/> Refresh</button>
        </div>
        <div className="info-box firewall-status"><strong>Status</strong><pre>{statusText}</pre></div>
      </section>
      <section className="section">
        <div className="section-title"><h2>Website WAF</h2></div>
        {websites.length === 0 && <EmptyState icon={Globe} message="No websites yet." />}
        {websites.length > 0 && <div className="firewall-form waf-website-selector">
          <label><span>Website</span><select value={selectedWafWebsiteId} onChange={e => loadWebsiteWafConfig(e.target.value)}>
            <option value="">Select website</option>
            {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
          </select></label>
          <button disabled={!selectedWafWebsiteId || !!loading} onClick={() => selectedSite && toggleWebsiteWaf(selectedSite)}><Shield size={14}/> {selectedSite?.waf_enabled ? 'Disable WAF' : 'Enable WAF'}</button>
        </div>}
        <div className="table waf-site-list">
          {websites.map(site => <div className="firewall-rule" key={site.id}>
            <span><strong>{site.domain}</strong></span>
            <div className="firewall-rule-actions">
              <span className={site.waf_enabled ? 'badge ok' : 'badge'}>{site.waf_enabled ? 'Enabled' : 'Disabled'}</span>
              <span className={site.http_flood_enabled ? 'badge ok' : 'badge'}>{site.http_flood_enabled ? 'Flood On' : 'Flood Off'}</span>
              <button disabled={!!loading} onClick={() => loadWebsiteWafConfig(site.id)}>Rules</button>
            </div>
          </div>)}
        </div>
      </section>
      {wafSiteConfig && <section className="section http-flood-panel">
        <div className="section-title">
          <h2>HTTP Flood - {wafSiteConfig.domain}</h2>
          <span className={httpFloodForm.http_flood_enabled ? 'badge ok' : 'badge'}>{httpFloodForm.http_flood_enabled ? 'Enabled' : 'Disabled'}</span>
        </div>
        <label className="schedule-toggle http-flood-toggle">
          <input type="checkbox" checked={!!httpFloodForm.http_flood_enabled} onChange={e => setHttpFloodForm(prev => ({ ...prev, http_flood_enabled: e.target.checked }))} />
          Enabled
        </label>
        <div className="http-flood-grid">
          <label><span>Requests</span><input type="number" min="1" max="100000" value={httpFloodForm.access_limit_requests} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_requests: e.target.value }))} /></label>
          <label><span>Window (sec)</span><input type="number" min="1" max="3600" value={httpFloodForm.access_limit_window} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_window: e.target.value }))} /></label>
          <label><span>Burst</span><input type="number" min="0" max="100000" value={httpFloodForm.access_limit_burst} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_burst: e.target.value }))} /></label>
          <label><span>Connections/IP</span><input type="number" min="1" max="10000" value={httpFloodForm.connection_limit} onChange={e => setHttpFloodForm(prev => ({ ...prev, connection_limit: e.target.value }))} /></label>
          <button disabled={!!loading} onClick={saveWebsiteHttpFlood}><Shield size={14}/> Save HTTP Flood</button>
        </div>
      </section>}
      {wafSiteConfig && <section className="section waf-rules-grid">
        <div className="waf-rule-panel">
          <div className="section-title"><h2>Default rules - {wafSiteConfig.domain}</h2></div>
          <div className="waf-default-groups">
            {Object.entries(groupedRules).map(([category, rules]) => <div className="waf-rule-group" key={category}>
              <h3>{category}</h3>
              {rules.map(rule => <label className="waf-rule-toggle" key={rule.id}>
                <input type="checkbox" checked={!!rule.enabled} onChange={e => toggleWafDefaultRule(rule.id, e.target.checked)} />
                <span><strong>{rule.title}</strong><small>{rule.description}</small></span>
              </label>)}
            </div>)}
          </div>
        </div>
        <div className="waf-rule-panel">
          <div className="section-title"><h2>Custom rules - {wafSiteConfig.domain}</h2></div>
          <textarea className="code-editor" value={wafCustomRules} onChange={e => setWafCustomRules(e.target.value)} rows={14} spellCheck={false} placeholder="SecRule ..." />
          <p className="hint">Saved into {wafSiteConfig.rules_file}</p>
          <div className="actions"><button disabled={!!loading} onClick={saveWebsiteWafRules}>Save website WAF rules</button></div>
        </div>
      </section>}
    </>;
  }

  function renderUpdates() {
    if (!isAdmin) return <section className="section"><h2>Updates</h2><p className="hint">No permission.</p></section>;
    const statusText = updatesStatus?.stdout || updatesStatus?.stderr || 'Click View logs to load update logs.';
    const panelUpdate = updatesStatus?.panel || {};
    const updateKnown = typeof panelUpdate.update_available === 'boolean';
    const updateAvailable = panelUpdate.update_available === true;
    const panelBadge = updateAvailable ? 'Update available' : updateKnown ? 'Up to date' : 'Unknown';
    const panelBadgeClass = updateAvailable ? 'badge bad' : updateKnown ? 'badge ok' : 'badge';
    const currentPanelVersion = panelUpdate.current_version || appVersion || 'unknown';
    const latestPanelVersion = panelUpdate.latest_version || 'unknown';
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>Updates</h2><p className="hint">OS packages use apt; panel updates use <code>bpanel-update</code>.</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={toggleUpdateLog}>{showUpdateLog ? <X size={14}/> : <FileText size={14}/>} {showUpdateLog ? 'Hide logs' : 'View logs'}</button>
        </div>
        <div className="info-box update-version-box">
          <div className="update-version-head"><strong>Panel release</strong><span className={panelBadgeClass}>{panelBadge}</span></div>
          <div className="update-version-grid">
            <span>Current <strong>v{currentPanelVersion}</strong></span>
            <span>Latest <strong>{latestPanelVersion === 'unknown' ? 'unknown' : `v${latestPanelVersion}`}</strong></span>
            <span>Checked <strong>{panelUpdate.last_checked_at || 'never'}</strong></span>
            <span>State file <strong>{panelUpdate.state_file || '/var/lib/bpanel/update-status.json'}</strong></span>
          </div>
          {panelUpdate.check_error && <p className="hint">Release check failed: {panelUpdate.check_error}</p>}
          {panelUpdate.last_update_status && <p className="hint">Last update: {panelUpdate.last_update_status}{panelUpdate.last_update_ref ? ` (${panelUpdate.last_update_ref})` : ''}{panelUpdate.last_update_finished_at ? ` at ${panelUpdate.last_update_finished_at}` : ''}</p>}
        </div>
        <div className="actions">
          <button className="secondary-light" disabled={!!loading} onClick={() => loadUpdates(true)}><RefreshCw size={14}/> Check releases</button>
          <button disabled={!!loading || osUpdating} onClick={runOsUpdate}><RefreshCw size={14} className={osUpdating ? 'spin' : ''}/> {osUpdating ? 'Updating OS...' : 'Update OS now'}</button>
          <button disabled={!!loading || panelUpdating || !updateAvailable} onClick={runPanelUpdate}><RotateCcw size={14} className={panelUpdating ? 'spin' : ''}/> {panelUpdating ? 'Updating panel...' : 'Update panel now'}</button>
        </div>
        {showUpdateLog && <div className="info-box firewall-status update-log-box">
          <div className="update-log-head"><strong>Update logs</strong><button className="secondary-light" disabled={!!loading} onClick={() => loadUpdates(true)}><RefreshCw size={13}/> Refresh</button></div>
          <pre>{statusText}</pre>
        </div>}
      </section>
      <section className="section">
        <h2>Auto Update OS</h2>
        <div className="firewall-form updates-os-form">
          <label><span>Enabled</span><select value={osAutoUpdate.enabled ? 'on' : 'off'} onChange={e => setOsAutoUpdate(prev => ({ ...prev, enabled: e.target.value === 'on' }))}><option value="on">On</option><option value="off">Off</option></select></label>
          <label><span>Mode</span><select value={osAutoUpdate.mode} onChange={e => setOsAutoUpdate(prev => ({ ...prev, mode: e.target.value }))}><option value="security">Security</option><option value="all">All packages</option></select></label>
          <label><span>Auto reboot</span><select value={osAutoUpdate.auto_reboot ? 'on' : 'off'} onChange={e => setOsAutoUpdate(prev => ({ ...prev, auto_reboot: e.target.value === 'on' }))}><option value="off">Off</option><option value="on">On</option></select></label>
          <button disabled={!!loading} onClick={saveOsAutoUpdate}>Save OS auto update</button>
        </div>
      </section>
      <section className="section">
        <h2>Auto Update Panel</h2>
        <div className="firewall-form updates-panel-form">
          <label><span>Enabled</span><select value={panelAutoUpdate.enabled ? 'on' : 'off'} onChange={e => setPanelAutoUpdate(prev => ({ ...prev, enabled: e.target.value === 'on' }))}><option value="on">On</option><option value="off">Off</option></select></label>
          <label><span>Daily time</span><input value={panelAutoUpdate.time} onChange={e => setPanelAutoUpdate(prev => ({ ...prev, time: e.target.value }))} placeholder="03:30" /></label>
          <button disabled={!!loading} onClick={savePanelAutoUpdate}>Save panel auto update</button>
        </div>
      </section>
    </>;
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
          <div><h2>Panel settings</h2><p className="hint">Branding and hostname.</p></div>
          <button disabled={!!loading} onClick={loadPanelSettings}><RefreshCw size={14}/> Refresh</button>
        </div>
        <div className="panel-settings-grid panel-settings-compact">
          <label><span>Panel name</span><input value={panelSettingsForm.app_name} onChange={e => setPanelSettingsForm(prev => ({ ...prev, app_name: e.target.value }))} placeholder="BPanel" /></label>
          <label><span>Panel hostname</span><input value={panelSettingsForm.panel_hostname} onChange={e => setPanelSettingsForm(prev => ({ ...prev, panel_hostname: e.target.value }))} placeholder="panel.domain.com" /></label>
          <label className="check-line panel-ssl-status"><input type="checkbox" checked={!!panelSettingsForm.ssl_enabled} onChange={e => setPanelSettingsForm(prev => ({ ...prev, ssl_enabled: e.target.checked }))} /> Panel SSL</label>
          <button disabled={!!loading || !panelSettingsForm.app_name || !panelSettingsForm.panel_hostname} onClick={savePanelSettings}><SettingsIcon size={14}/> Save settings</button>
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
              <button className="mini secondary-light" disabled={!!loading} onClick={() => startEditingUser(user)}><Pencil size={14}/> Edit</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => quickLoginUser(user)}><LogIn size={14}/> Login as</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => changeUserPassword(user)}><KeyRound size={14}/> Password</button>
              {user.totp_enabled && user.id !== currentUser?.id && <button className="mini secondary-light" disabled={!!loading} onClick={() => resetUserTwoFactor(user)}>Reset 2FA</button>}
              {user.id !== currentUser?.id && <button className="mini danger" disabled={!!loading} onClick={() => deletePanelUser(user)}><Trash2 size={14}/></button>}
            </div>
            {editingUser?.id === user.id && <div className="user-edit-panel">
              <div className="user-edit-heading">
                <div><strong>Edit {user.username}</strong><small>
                  {user.id === currentUser?.id ? 'Role is locked for the active admin session.' : 'Role changes sign the user out of existing sessions.'}
                  {editingUserForm.role === 'admin' ? ' Admin accounts bypass website and storage limits.' : ''}
                </small></div>
                <button className="user-edit-close secondary-light" onClick={cancelEditingUser} aria-label="Close user editor" title="Close user editor"><X size={16}/></button>
              </div>
              <div className="user-edit-grid">
                <label><span>Email</span><input type="email" value={editingUserForm.email} onChange={e => setEditingUserForm(prev => ({ ...prev, email: e.target.value }))} /></label>
                <label><span>Role</span><select value={editingUserForm.role} disabled={user.id === currentUser?.id} onChange={e => setEditingUserForm(prev => ({ ...prev, role: e.target.value }))}>
                  <option value="end_user">End user</option><option value="admin">Admin</option>
                </select></label>
                <label><span>Website limit</span><input type="number" min="0" max="1000" value={editingUserForm.website_limit} onChange={e => setEditingUserForm(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
                <label><span>Storage limit (MB)</span><input type="number" min="0" max="1048576" value={editingUserForm.storage_limit_mb} onChange={e => setEditingUserForm(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
              </div>
              <div className="user-edit-actions">
                <button className="secondary-light" onClick={cancelEditingUser}>Cancel</button>
                <button disabled={!!loading || !editingUserForm.email.trim()} onClick={updatePanelUser}><Save size={14}/> Save changes</button>
              </div>
            </div>}
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
      {renderNotifications()}
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
      </section>
      {renderNotifications()}
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
          {mainNavItems.map(([key, label, Icon]) => <button key={key} type="button" className={page === key ? 'active' : ''} onClick={() => navigateToPage(key)} aria-current={page === key ? 'page' : undefined}>
            <Icon size={17}/>{label}
          </button>)}
          <div className={`sidebar-nav-group ${settingsMenuOpen ? 'open' : ''}`}>
            <button className={`sidebar-group-toggle ${settingsIsActive ? 'active' : ''}`} onClick={() => setSettingsMenuOpen(open => !open)} aria-expanded={settingsMenuOpen} aria-controls="settings-submenu">
              <SettingsIcon size={17}/><span>Settings</span><ChevronDown className="sidebar-group-chevron" size={16}/>
            </button>
            {settingsMenuOpen && <div className="sidebar-subnav" id="settings-submenu">
              {settingsNavItems.map(([key, label, Icon]) => <button key={key} type="button" className={page === key ? 'active' : ''} onClick={() => navigateToPage(key)} aria-current={page === key ? 'page' : undefined}>
                <Icon size={16}/>{label}
              </button>)}
            </div>}
          </div>
        </nav>
        {appVersion && <div className="sidebar-version">v{appVersion}</div>}
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
        </div>
      </div>
    </section>
    {renderNotifications()}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
