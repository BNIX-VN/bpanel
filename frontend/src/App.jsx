import React, { useEffect, useLayoutEffect, useState, useCallback, useRef } from 'react';
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
import 'ace-builds/src-noconflict/theme-tomorrow_night';
import { Archive, ArchiveRestore, ArrowLeft, Ban, Bot, Boxes, Check, ChevronDown, Clock, Code2, Copy, Cpu, Database, Dices, ExternalLink, FileText, FolderOpen, Globe, HardDrive, Home, Image, KeyRound, Lock, LogIn, LogOut, MemoryStick, Menu, Moon, MoveRight, Network, Pencil, Save, Search, Server, Settings as SettingsIcon, Shield, Sun, Trash2, TerminalIcon, Users, X, RefreshCw, Plus, Download, Upload, Play, Square, RotateCcw, AlertCircle, Activity, BrickWall, Bug, LockKeyhole, PackageOpen, ScrollText, ShieldAlert, CheckCircle, Zap } from 'lucide-react';
import { Terminal } from './components/Terminal';
import { LANGUAGES, t, useLanguage } from './i18n.js';
import './style.css';
import './brand.css';
import './file-manager.css';
import './theme.css';
// OPanel's layout layer, loaded last so it wins ties: navy sidebar in
// groups, one account menu, one blue button per task.
import './ui.css';

const API = import.meta.env.VITE_API_URL || '/api';
// Schedules offered by name; anything else is "Custom". A cron expression is
// the one field most people get wrong, so it is picked rather than typed.
const CRON_SCHEDULE_PRESETS = [
  ['* * * * *', 'Every minute'],
  ['*/5 * * * *', 'Every 5 minutes'],
  ['*/15 * * * *', 'Every 15 minutes'],
  ['*/30 * * * *', 'Every 30 minutes'],
  ['0 * * * *', 'Every hour'],
  ['0 */6 * * *', 'Every 6 hours'],
  ['0 0 * * *', 'Every day at 00:00'],
  ['0 2 * * *', 'Every day at 02:00'],
  ['0 0 * * 0', 'Every Sunday at 00:00'],
  ['0 0 1 * *', 'On the 1st of every month'],
];
const BACKUP_SCHEDULE_PRESETS = [
  ['0 2 * * *', 'Every day at 02:00'],
  ['0 3 * * *', 'Every day at 03:00'],
  ['0 */12 * * *', 'Every 12 hours'],
  ['0 2 * * 0', 'Every Sunday at 02:00'],
  ['0 2 1 * *', 'On the 1st of every month at 02:00'],
];
const isPresetSchedule = (presets, value) => presets.some(([preset]) => preset === value);
// How a site's app_type is written wherever a person reads it.
const APP_TYPE_LABELS = { wordpress: 'WordPress', php: 'PHP', static: 'Static', application: 'App' };
const DEFAULT_SERVICE_NAMES = ['bpanel-api', 'nginx', 'php8.3-fpm', 'php8.4-fpm', 'mariadb', 'redis-server'];
const HTTP_FLOOD_DEFAULTS = {
  access_limit_requests: 100,
  access_limit_window: 10,
  access_limit_burst: 100,
  connection_limit: 60,
};
const PHP_VERSION_ORDER = ['5.6', '7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5'];
const NGINX_REWRITE_MODES = [
  { value: 'none', label: 'None / static PHP' },
  { value: 'front_controller', label: 'PHP front controller' },
  { value: 'laravel', label: 'Laravel' },
  { value: 'codeigniter', label: 'CodeIgniter' },
  { value: 'seohburl', label: 'SEO HB URL' },
];
function composeWebPorts(plan, wanted) {
  // Which ports the service behind the domain listens on. More than one means
  // the customer has to say which, rather than the panel guessing.
  const name = wanted || plan?.web_service;
  const service = plan?.services?.find(item => item.name === name);
  return service?.container_ports || [];
}

// Pages opened from inside another page instead of the sidebar. They have no
// nav entry of their own, so without this the header falls back to the first
// item and titles the page "Dashboard".
const NAV_PARENT_PAGE = { 'waf-site': 'waf', 'malware-scan': 'malware' };

// 'waf-site' is reached from the WAF overview rather than the sidebar, but it
// still belongs to Settings so the menu stays open and WAF stays highlighted.
const PAGE_ROUTES = {
  dashboard: '/',
  websites: '/website',
  applications: '/applications',
  ssl: '/ssl',
  databases: '/database',
  sftp: '/sftp',
  cron: '/cron',
  files: '/filemanager',
  backups: '/backups',
  users: '/users',
  settings: '/settings',
  security: '/security',
  php: '/php',
  firewall: '/firewall',
  waf: '/waf',
  'waf-site': '/waf-site',
  'malware-scan': '/malware-scan',
  malware: '/malware',
  'access-logs': '/access-logs',
  updates: '/updates',
  services: '/services',
  addons: '/addons',
  mcp: '/ai-assistants',
};

/* ---------------------------------------------------------------
   Theme (light / dark)
   The initial value is applied by the inline script in index.html,
   so React only has to keep it in sync from here on.
--------------------------------------------------------------- */
const THEME_STORAGE_KEY = 'bpanel-theme';
const THEME_EVENT = 'bpanel-theme-change';

function readStoredTheme() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'dark' || stored === 'light' ? stored : null;
  } catch { return null; }
}

function systemTheme() {
  try { return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; }
  catch { return 'light'; }
}

function currentTheme() {
  const attr = document.documentElement.getAttribute('data-theme');
  if (attr === 'dark' || attr === 'light') return attr;
  return readStoredTheme() || systemTheme();
}

function applyTheme(theme) {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  root.style.colorScheme = theme;
  document.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: theme }));
}

/* Subscribe to the active theme without owning it. */
function useThemeName() {
  const [theme, setTheme] = useState(currentTheme);
  useEffect(() => {
    const handler = event => setTheme(event.detail);
    document.addEventListener(THEME_EVENT, handler);
    return () => document.removeEventListener(THEME_EVENT, handler);
  }, []);
  return theme;
}

/* Owns the theme: persists the user's choice, follows the OS until they pick one. */
function useTheme() {
  const [theme, setTheme] = useState(currentTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  useEffect(() => {
    let media;
    try { media = window.matchMedia('(prefers-color-scheme: dark)'); } catch { return undefined; }
    const onChange = () => { if (!readStoredTheme()) setTheme(systemTheme()); };
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(prev => {
      const next = prev === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch {}
      return next;
    });
  }, []);

  return [theme, toggleTheme];
}

function ThemeToggle({ theme, onToggle, className = '' }) {
  const isDark = theme === 'dark';
  const label = isDark ? 'Switch to light mode' : 'Switch to dark mode';
  return <button
    type="button"
    className={`theme-toggle ${className}`.trim()}
    onClick={onToggle}
    title={label}
    aria-label={label}
    aria-pressed={isDark}
  >{isDark ? <Sun size={16}/> : <Moon size={16}/>}</button>;
}

// Chrome's password manager writes the saved panel username into text fields
// that are not login fields at all - the website search opened as "admin",
// and so did the passkey name beside a password box - whatever autocomplete
// says. It never fills a read-only field, so this one stays read-only until a
// pointer or the keyboard actually lands on it. Unlocking on pointerdown,
// before focus, keeps a phone's keyboard coming up on the first tap.
function NoAutofillInput({ onFocus, onPointerDown, ...props }) {
  const unlock = event => { event.currentTarget.readOnly = false; };
  return <input
    autoComplete="off"
    {...props}
    readOnly
    onPointerDown={event => { unlock(event); onPointerDown?.(event); }}
    onFocus={event => { unlock(event); onFocus?.(event); }}
  />;
}

function LanguageToggle({ language, onChange, className = '' }) {
  /* A button, not a select. There are two languages and English is the one the
   * panel is written in, so the only thing anybody wants is to flip to the
   * other - a dropdown asks them to open a list to choose between two items.
   *
   * It shows the language you get by pressing it, which is how the theme
   * toggle next to it behaves: in dark mode that button shows a sun.
   *
   * Two letters and no icon. EN and VI already are the picture - a globe or
   * a speech bubble beside them says nothing the letters do not, and any
   * flag would name a country instead of a language. */
  const next = language === 'vi' ? 'en' : 'vi';
  const label = next === 'vi' ? 'Chuyển sang Tiếng Việt' : 'Switch to English';
  return <button
    type="button"
    className={`language-toggle ${className}`.trim()}
    onClick={() => onChange(next)}
    title={label}
    aria-label={label}
  >
    {next === 'vi' ? 'VI' : 'EN'}
  </button>;
}

function WordPressIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="lucide">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
      <text x="12" y="16" textAnchor="middle" fontSize="11" fontWeight="700" fontFamily="Georgia, serif" fill="currentColor">W</text>
    </svg>
  );
}
const EDITOR_FONT_FAMILY = "Consolas, 'SFMono-Regular', 'Liberation Mono', Menlo, monospace";
const WAF_ACCESS_LOG_DEFAULTS = {
  websiteId: '',
  verdict: 'all',
  query: '',
  limit: 50,
  refresh: 5,
};
const ROUTE_PAGES = new Map([
  ...Object.entries(PAGE_ROUTES).map(([pageName, path]) => [path, pageName]),
  ['/dashboard', 'dashboard'],
  ['/websites', 'websites'],
  ['/databases', 'databases'],
  ['/sftp-accounts', 'sftp'],
  ['/files', 'files'],
  ['/file-manager', 'files'],
  ['/website', 'websites'],
  // API tokens moved into Panel settings. Old links still land somewhere real.
  ['/api-token', 'settings'],
  ['/api-tokens', 'settings'],
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

// The one website mode served by proxying to an installed application.
const PROXIED_APP_TYPES = ['application'];
const EMPTY_SITE_APP_DRAFT = {
  name: 'app',
  kind: 'node',
  port: '',
  memory_limit_mb: '',
  compose_source: '',
  web_service: '',
  start_kind: 'npm',
  start_arg: 'start',
  node_major: '22',
  image: '',
  container_port: '3000',
  cpu_limit: '1',
  env: '',
};
const SITE_APP_KIND_LABELS = { node: 'Node.js', docker: 'Container', compose: 'Compose' };
const SITE_APP_KINDS = [
  ['node', 'Node.js', 'BPanel installs dependencies and keeps the process running under systemd.'],
  ['docker', 'Container', 'BPanel pulls the image and runs it, published on loopback only.'],
  ['compose', 'Docker Compose', 'Paste your project\u2019s docker-compose.yml. BPanel checks it and runs a file it generates from what it accepted.'],
];
const WEBSITE_MODES = [
  ['wordpress', 'WordPress'],
  ['php', 'PHP'],
  ['static', 'Static'],
  ['application', 'Application'],
];

function isProxiedAppType(appType) {
  return PROXIED_APP_TYPES.includes(appType);
}

function websiteConfigForm(site = {}) {
  const appType = site.app_type || 'wordpress';
  return {
    app_type: appType,
    php_version: site.php_version || '8.4',
    app_id: site.app_id ? String(site.app_id) : '',
    nginx_rewrite_mode: appType === 'wordpress'
      ? 'front_controller'
      : appType === 'static' || isProxiedAppType(appType)
        ? 'none'
        : site.nginx_rewrite_mode || 'none',
  };
}

function formatAccessLogTime(value = '') {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function accessLogBadgeClass(verdict = '') {
  if (verdict === 'allow') return 'access-log-verdict allow';
  if (verdict === 'error') return 'access-log-verdict error';
  return 'access-log-verdict block';
}

function accessLogVerdictLabel(verdict = '') {
  if (verdict === 'allow') return 'Allow';
  if (verdict === 'error') return 'Error';
  return 'Block';
}

function accessLogCountryLabel(item = {}) {
  const country = item.country || '';
  const code = item.country_code || '';
  if (country && code && country !== code) return `${country} (${code})`;
  return country || code || '-';
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replace(/"/g, '""')}"`;
}

/* ---------------------------------------------------------------
   Passkeys (WebAuthn)

   The browser speaks ArrayBuffers and the API speaks base64url, so every
   ceremony is a translation either side of navigator.credentials. Nothing here
   decides anything: the server issues the challenge and checks the signature
   against an origin and a Relying Party ID it derives itself.
   --------------------------------------------------------------- */

const passkeySupported = () =>
  typeof window !== 'undefined'
  && !!window.PublicKeyCredential
  && !!navigator.credentials;

function b64urlToBytes(value) {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(raw, ch => ch.charCodeAt(0));
}

function bytesToB64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let raw = '';
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/* The server sends the options as the spec writes them, with the binary fields
   base64url encoded. These two put them back. */
function decodeCreationOptions(options) {
  return {
    ...options,
    challenge: b64urlToBytes(options.challenge),
    user: { ...options.user, id: b64urlToBytes(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map(c => ({
      ...c, id: b64urlToBytes(c.id),
    })),
  };
}

function decodeRequestOptions(options) {
  return {
    ...options,
    challenge: b64urlToBytes(options.challenge),
    allowCredentials: (options.allowCredentials || []).map(c => ({
      ...c, id: b64urlToBytes(c.id),
    })),
  };
}

/* What goes back to the server, in the shape py_webauthn parses. */
function encodeRegistration(credential) {
  return JSON.stringify({
    id: credential.id,
    rawId: bytesToB64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bytesToB64url(credential.response.clientDataJSON),
      attestationObject: bytesToB64url(credential.response.attestationObject),
      transports: credential.response.getTransports ? credential.response.getTransports() : [],
    },
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
  });
}

function encodeAssertion(credential) {
  return JSON.stringify({
    id: credential.id,
    rawId: bytesToB64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bytesToB64url(credential.response.clientDataJSON),
      authenticatorData: bytesToB64url(credential.response.authenticatorData),
      signature: bytesToB64url(credential.response.signature),
      userHandle: credential.response.userHandle ? bytesToB64url(credential.response.userHandle) : null,
    },
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
  });
}

function editorParamsFromLocation() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('view') !== 'editor') return null;
  const websiteId = params.get('website_id');
  const appId = params.get('app_id');
  const path = params.get('path') || 'public_html/index.html';
  if (!websiteId && !appId) return null;
  return { websiteId: websiteId ? String(websiteId) : '', appId: appId ? String(appId) : '', path };
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

// --- File permissions (chmod) ------------------------------------------------
// The listing reports POSIX modes as octal strings ("644", and "2755" or the
// like when a folder carries a special bit), so the dialog works on the same
// representation.
// Monday first, matching datetime.weekday() on the server.
const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MALWARE_SCHEDULES_DEFAULT = {
  websites: { enabled: false, weekday: 6, hour: 3, weekday_label: '', next_run_at: '', last_run_at: '', last_status: '' },
  server: { enabled: false, weekday: 6, hour: 4, weekday_label: '', next_run_at: '', last_run_at: '', last_status: '' },
};
const MALWARE_SCHEDULE_LABELS = {
  websites: 'All websites',
  server: 'Whole server',
};
// The malware scan schedule is stored and sent to the API as UTC weekday/hour
// (matching datetime.weekday() on the server) - nobody running a Vietnamese
// host should have to do +7 math to pick a quiet hour. These convert only
// for display/input; malwareSchedulesForm itself always stays in UTC.
const VN_UTC_OFFSET_HOURS = 7;
function utcScheduleToVn(weekday, hour) {
  const vnHour = (hour + VN_UTC_OFFSET_HOURS) % 24;
  const dayShift = hour + VN_UTC_OFFSET_HOURS >= 24 ? 1 : 0;
  return { weekday: (weekday + dayShift) % 7, hour: vnHour };
}
function vnScheduleToUtc(weekday, hour) {
  const utcHour = (hour - VN_UTC_OFFSET_HOURS + 24) % 24;
  const dayShift = hour - VN_UTC_OFFSET_HOURS < 0 ? -1 : 0;
  return { weekday: (weekday + dayShift + 7) % 7, hour: utcHour };
}

const PERMISSION_CLASSES = [
  { key: 'owner', label: 'Owner' },
  { key: 'group', label: 'Group' },
  { key: 'other', label: 'Public' },
];
const PERMISSION_BITS = [
  { key: 'read', label: 'Read', value: 4 },
  { key: 'write', label: 'Write', value: 2 },
  { key: 'execute', label: 'Execute', value: 1 },
];
const PERMISSION_PRESETS = {
  file: [['644', 'Default'], ['755', 'Executable'], ['600', 'Private'], ['444', 'Read-only']],
  dir: [['755', 'Default'], ['750', 'Group read'], ['775', 'Group write'], ['700', 'Private']],
};

function normalizeOctalMode(mode) {
  const value = String(mode ?? '').trim();
  return /^[0-7]{3,4}$/.test(value) ? value : '';
}

function octalToPermissionBits(mode) {
  const padded = (normalizeOctalMode(mode) || '0644').padStart(4, '0');
  return {
    special: Number(padded[0]),
    owner: Number(padded[1]),
    group: Number(padded[2]),
    other: Number(padded[3]),
  };
}

function permissionBitsToOctal({ special, owner, group, other }) {
  const body = `${owner}${group}${other}`;
  return special ? `${special}${body}` : body;
}

function permissionSymbols(mode) {
  const bits = octalToPermissionBits(mode);
  return PERMISSION_CLASSES
    .map(({ key }) => PERMISSION_BITS.map(bit => (bits[key] & bit.value ? bit.key[0] : '-')).join(''))
    .join('');
}

function formatApiError(detail, fallback = 'Request failed.') {
  /* Backend messages pass through t() on their way to the screen.
   *
   * The server does not know what language the reader wants, and teaching it
   * would mean a header, a dependency and a second dictionary. Translating on
   * display costs a lookup: a sentence the dictionary knows is shown in
   * Vietnamese, and anything it does not know is shown in the English the
   * server wrote - which is the same fallback the rest of the interface uses.
   */
  if (detail === null || detail === undefined || detail === '') return t(fallback);
  if (typeof detail === 'string') {
    const cleaned = detail.replace(/^Value error,\s*/i, '');
    return cleaned ? t(cleaned) : t(fallback);
  }
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
      <strong>{isError ? t('Action failed') : t('Completed')}</strong>
      <span>{message}</span>
    </div>
    <button className="app-toast-close" onClick={onClose} aria-label={t('Dismiss notification')} title={t('Dismiss notification')}><X size={16}/></button>
  </div>;
}

const ACE_THEMES = { light: 'ace/theme/textmate', dark: 'ace/theme/tomorrow_night' };
const aceThemeFor = theme => ACE_THEMES[theme] || ACE_THEMES.light;

function CodeEditor({ value, mode, disabled, onChange, onCursorChange }) {
  const hostRef = useRef(null);
  const editorRef = useRef(null);
  const suppressChangeRef = useRef(false);
  const onChangeRef = useRef(onChange);
  const onCursorChangeRef = useRef(onCursorChange);
  const themeName = useThemeName();
  const themeRef = useRef(themeName);

  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  useEffect(() => { onCursorChangeRef.current = onCursorChange; }, [onCursorChange]);
  useEffect(() => {
    themeRef.current = themeName;
    editorRef.current?.setTheme(aceThemeFor(themeName));
  }, [themeName]);

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const editor = ace.edit(hostRef.current, {
      mode: `ace/mode/${aceModeName(mode)}`,
      theme: aceThemeFor(themeRef.current),
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

    editor.setOptions({
      enableBasicAutocompletion: true,
      enableLiveAutocompletion: true,
      enableMatchBrackets: true,
      enableSnippets: false,
      fontFamily: EDITOR_FONT_FAMILY,
    });
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
    editorRef.current = editor;
    reportCursor();

    return () => {
      destroyed = true;
      editor.session.off('change', handleChange);
      editor.selection.off('changeCursor', reportCursor);
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
  const [theme, toggleTheme] = useTheme();
  // Subscribed, not owned - the same shape as the theme. Reading it here
  // is what makes the whole tree render again when the language changes,
  // because every t() call is evaluated during render.
  const [language, changeLanguage] = useLanguage();
  const [currentUser, setCurrentUser] = useState(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [standaloneEditor] = useState(() => editorParamsFromLocation());
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [otpCode, setOtpCode] = useState('');
  // The passkey challenge the server handed back with the password check, and
  // whether the customer has asked for the authenticator app instead.
  const [passkeyPrompt, setPasskeyPrompt] = useState(null);
  const [passkeyStatus, setPasskeyStatus] = useState(null);
  // The step-up for adding a passkey. A masked field rather than prompt(),
  // which shows a password in clear text in a browser dialog.
  const [passkeyPassword, setPasskeyPassword] = useState('');
  const [passkeyName, setPasskeyName] = useState('');
  const [needsTwoFactor, setNeedsTwoFactor] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [page, setPage] = useState(() => pageFromPathname(window.location.pathname));
  const [domain, setDomain] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [wpAdminUser, setWpAdminUser] = useState('admin');
  const [wpAdminPassword, setWpAdminPassword] = useState('');
  const [phpVersion, setPhpVersion] = useState('8.4');
  const [siteType, setSiteType] = useState('wordpress');
  const [createSslMode, setCreateSslMode] = useState('none'); // none|letsencrypt|wildcard|shared|manual
  const [createSslToken, setCreateSslToken] = useState(''); // Cloudflare token for the wildcard mode
  const [installWordPress, setInstallWordPress] = useState(true);
  /* The create form starts folded away. Making a website is something an
     operator does now and then; looking one up is what they came for, and
     the form was four hundred pixels of it between them and the list. A
     panel with no sites yet is the exception - there the form is the only
     thing to do, so it opens itself. */
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [nginxCustomEditing, setNginxCustomEditing] = useState(null); // Website settings editor state
  const [websiteSettingsForm, setWebsiteSettingsForm] = useState(websiteConfigForm());
  const [logViewer, setLogViewer] = useState(null); // {id, domain, kind, lines, path, content, exists}
  const [terminalViewer, setTerminalViewer] = useState(null); // {id, domain}
  const [wordpressInstaller, setWordpressInstaller] = useState(null);
  const [websites, setWebsites] = useState([]);
  const [websiteList, setWebsiteList] = useState([]);
  const [websiteSearch, setWebsiteSearch] = useState('');
  const [websiteSearching, setWebsiteSearching] = useState(false);
  const [aliasDrafts, setAliasDrafts] = useState({});
  const [aliasModes, setAliasModes] = useState({});
  const [databases, setDatabases] = useState([]);
  const [dbCreateOpen, setDbCreateOpen] = useState(false);
  const [dbSearch, setDbSearch] = useState('');
  const [dbSearching, setDbSearching] = useState(false);
  const [newDatabase, setNewDatabase] = useState({ db_name: '', db_user: '', db_password: '' });
  const [createdDbInfo, setCreatedDbInfo] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [users, setUsers] = useState([]);
  const [packages, setPackages] = useState([]);
  const [userTab, setUserTab] = useState('list');
  const [resourceUsage, setResourceUsage] = useState(null);
  const [dashSummary, setDashSummary] = useState(null);
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
  const [newBackupSchedule, setNewBackupSchedule] = useState({ user_ids: [], all_users: false, schedule: '0 2 * * *', target_id: '', name_suffix: 'full_date', retention: 7 });
  const [sftpTargets, setSftpTargets] = useState([]);
  const [selectedSftpTargetId, setSelectedSftpTargetId] = useState('');
  const [newSftpTarget, setNewSftpTarget] = useState({ name: '', kind: 'sftp', host: '', port: 22, username: '', password: '', private_key: '', remote_path: '/backups/bpanel', endpoint: '', region: '', bucket: '', access_key: '', secret_key: '', prefix: '', secure: true });
  // The restore catalogue: local archives and whatever is in each S3 bucket,
  // in one list, because "what can I restore" is not answered by this disk alone.
  const [restoreCatalogue, setRestoreCatalogue] = useState({ items: [], errors: [], loaded: false });
  const [restorePicks, setRestorePicks] = useState([]);
  const [restoreFilter, setRestoreFilter] = useState('');
  const [daBackups, setDaBackups] = useState([]);
  const [daReplaceExisting, setDaReplaceExisting] = useState(false);
  const [daScanResult, setDaScanResult] = useState(null);
  const [daImportJob, setDaImportJob] = useState(null);
  const [daBulkImportJob, setDaBulkImportJob] = useState(null);
  const [selectedDaBackups, setSelectedDaBackups] = useState([]);
  const daFileInputRef = React.useRef(null);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState(() => standaloneEditor?.websiteId || '');
  const [sslMode, setSslMode] = useState('letsencrypt');
  const [manualSslForm, setManualSslForm] = useState({ certificate: '', private_key: '', ca_bundle: '' });
  const [manualSslFiles, setManualSslFiles] = useState({ certificate: null, private_key: null, ca_bundle: null });
  const [wildcardToken, setWildcardToken] = useState('');
  const [cfZone, setCfZone] = useState({ zone: null, has_token: false });
  const [sslSources, setSslSources] = useState([]);
  const [sharedSource, setSharedSource] = useState('');
  const [cronSchedule, setCronSchedule] = useState('*/15 * * * *');
  const [cronScheduleCustom, setCronScheduleCustom] = useState(false);
  const [backupScheduleCustom, setBackupScheduleCustom] = useState(false);
  const [cronCommand, setCronCommand] = useState('');
  const [cronItems, setCronItems] = useState([]);
  const [cronUser, setCronUser] = useState('');
  const [cronPhpInfo, setCronPhpInfo] = useState({ php_binary: '', php_version: '' });
  const [sftpAccounts, setSftpAccounts] = useState([]);
  const [newSftpAccount, setNewSftpAccount] = useState({ label: '', password: '' });
  // Shown once, right after creation. A password the user typed is never
  // echoed back by the API, so this only ever holds a generated one.
  const [createdSftpInfo, setCreatedSftpInfo] = useState(null);
  const [sftpLimits, setSftpLimits] = useState({ limit: 0, used: 0, unlimited: false });
  // The main account's own SFTP password, shown once after it is set.
  const [ownSftpPassword, setOwnSftpPassword] = useState(null);
  const [siteApps, setSiteApps] = useState({ items: [], limit: 0, used: 0, memory_ceiling_mb: 512, port_range: [21000, 21999] });
  // Optional features. Until this has loaded nothing addon-owned is offered, so
  // a slow first request cannot flash a section that turns out not to be there.
  const [addons, setAddons] = useState({ items: [], can_manage: false, loaded: false });
  const [f2b, setF2b] = useState(null);
  // Which list the operator asked to see. Null keeps the page one screen tall
  // however many rules, banned addresses or blocklist URLs there are.
  const [fwDetail, setFwDetail] = useState(null);
  const [fwFilter, setFwFilter] = useState('');
  const [f2bBanned, setF2bBanned] = useState({ items: [], total: 0, offset: 0, limit: 50 });
  const [fwAction, setFwAction] = useState('block');
  const [siteAppDraft, setSiteAppDraft] = useState(EMPTY_SITE_APP_DRAFT);
  const [createSiteAppId, setCreateSiteAppId] = useState('');
  // File manager target: empty means the selected website, otherwise an app.
  const [fileAppId, setFileAppId] = useState(() => standaloneEditor?.appId || '');
  const [siteAppLog, setSiteAppLog] = useState(null);
  const [composePlan, setComposePlan] = useState(null);
  const [siteAppEdit, setSiteAppEdit] = useState(null);
  const [siteAppEditPlan, setSiteAppEditPlan] = useState(null);
  const [siteRuntimes, setSiteRuntimes] = useState({ docker: { installed: false }, node_majors: [], allowed_registries: [] });
  const [chmodTarget, setChmodTarget] = useState(null);
  const [chmodMode, setChmodMode] = useState('644');
  const [filePath, setFilePath] = useState(() => standaloneEditor?.path || 'public_html/index.html');
  const [fileListPath, setFileListPath] = useState('public_html');
  const [fileUploadDir, setFileUploadDir] = useState('public_html');
  const [files, setFiles] = useState([]);
  const [fileJobs, setFileJobs] = useState([]);
  const [fileContent, setFileContent] = useState('');
  const [selectedFilePaths, setSelectedFilePaths] = useState([]);
  const [archiveFormat, setArchiveFormat] = useState('zip');
  const [editorCursor, setEditorCursor] = useState({ line: 1, column: 1 });
  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0 });
  const [editingUser, setEditingUser] = useState(null);
  const [editingUserForm, setEditingUserForm] = useState({ email: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, new_password: '', confirm_password: '' });
  const [newPackage, setNewPackage] = useState({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0 });
  const [editingPackageId, setEditingPackageId] = useState('');
  const [editingPackageForm, setEditingPackageForm] = useState({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0 });
  const [phpConfig, setPhpConfig] = useState({ php_version: '8.4', display_errors: 'Off', max_execution_time: 300, max_input_time: 600, max_input_vars: 10000, memory_limit: '1024M', post_max_size: '1024M', upload_max_filesize: '1024M' });
  const [phpExtensions, setPhpExtensions] = useState({ versions: [], extensions: [] });
  const [phpVersions, setPhpVersions] = useState({ installed: ['8.4'], supported: ['5.6', '7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5'] });
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
  // Bot blocking. The list is free text so a whole blocklist can be pasted in
  // one go; the backend splits and cleans it. Targets are the websites the
  // paste is applied to - it is normally the same list on many sites.
  const [botBlocks, setBotBlocks] = useState(null);
  const [bulkBotOpen, setBulkBotOpen] = useState(false);
  // The global list as an array so each entry can be removed on its own; the
  // paste box is only for adding several at once.
  const [globalBots, setGlobalBots] = useState([]);
  const [crs, setCrs] = useState(null);
  const [newBotName, setNewBotName] = useState('');
  const [globalBotPaste, setGlobalBotPaste] = useState('');
  const [globalBotFilter, setGlobalBotFilter] = useState('');
  // The list for the one site being configured, kept apart from the bulk
  // import above so editing one site cannot disturb a pending bulk paste.
  const [siteBotText, setSiteBotText] = useState('');
  const [wafAccessLogFilters, setWafAccessLogFilters] = useState(WAF_ACCESS_LOG_DEFAULTS);
  const [wafAccessLogs, setWafAccessLogs] = useState({ items: [], total: 0, scanned: 0, missing: [], generated_at: '' });
  const [assignUserId, setAssignUserId] = useState('');
  const [assignWebsiteId, setAssignWebsiteId] = useState('');
  const [twoFactorStatus, setTwoFactorStatus] = useState(null);
  const [twoFactorSetup, setTwoFactorSetup] = useState(null);
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [malwareScanStatus, setMalwareScanStatus] = useState(null);
  const [scanTargetWebsiteId, setScanTargetWebsiteId] = useState('');
  const [scanResults, setScanResults] = useState(null);
  const [scanJob, setScanJob] = useState(null);
  const [scanJobs, setScanJobs] = useState([]);
  const [malwareSchedules, setMalwareSchedules] = useState(MALWARE_SCHEDULES_DEFAULT);
  const [malwareSchedulesForm, setMalwareSchedulesForm] = useState(MALWARE_SCHEDULES_DEFAULT);
  const [scanLoading, setScanLoading] = useState(false);
  const [incrementalDays, setIncrementalDays] = useState(2);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);
  // Set while signing out on purpose. Requests already in flight come back
  // 401 once the server drops the session; they are this sign-out, not an
  // expiry, and must not replace "Logged out." with "Your session expired".
  const signedOutRef = useRef(false);
  const [panelSettings, setPanelSettings] = useState({ app_name: 'BPanel', panel_url: '', panel_hostname: '', panel_port: 2222, logo_url: '', favicon_url: '/favicon.png', ssl_enabled: false });
  const [phpTune, setPhpTune] = useState(null);
  const [phpTuneApplied, setPhpTuneApplied] = useState(false);
  const [panelSettingsForm, setPanelSettingsForm] = useState({ app_name: 'BPanel', panel_hostname: '', panel_port: 2222, ssl_enabled: false });
  const [apiTokens, setApiTokens] = useState([]);
  const [newApiToken, setNewApiToken] = useState({ name: 'WHMCS', allowed_ips: '' });
  const [createdApiToken, setCreatedApiToken] = useState('');
  const [appVersion, setAppVersion] = useState('');
  const [panelLogoFile, setPanelLogoFile] = useState(null);
  const [panelFaviconFile, setPanelFaviconFile] = useState(null);
  const [adminAccountForm, setAdminAccountForm] = useState({ email: '', current_password: '', password: '', confirm_password: '', code: '' });
  const [updatesStatus, setUpdatesStatus] = useState(null);
  const [showUpdateLog, setShowUpdateLog] = useState(false);
  const [osUpdating, setOsUpdating] = useState(false);
  const [panelUpdating, setPanelUpdating] = useState(false);
  const [panelUpdateLog, setPanelUpdateLog] = useState([]);
  const panelUpdateInterval = useRef(null);
  const [osAutoUpdate, setOsAutoUpdate] = useState({ enabled: true, mode: 'security', auto_reboot: false });
  const noticeTimer = useRef(null);
  const isAdmin = currentUser?.role === 'admin';
  const mcpAddonInstalled = !!addons.items.find(item => item.slug === 'mcp')?.installed;
  const [mcpTokens, setMcpTokens] = useState([]);
  const [mcpDraft, setMcpDraft] = useState({ name: '', expires_in_days: 90, can_write: false });
  // Held until dismissed rather than cleared on the next render: the server
  // keeps only a hash, so a token that scrolls away is gone for good.
  const [mcpNewToken, setMcpNewToken] = useState('');
  const applicationAddon = addons.items.find(item => item.slug === 'application');
  const applicationAddonInstalled = !!applicationAddon?.installed;
  // Two locks, and both have to be open: the server has to have the addon
  // installed at all, and the customer's package has to include it. Admins skip
  // the second one, never the first.
  const appsFeatureEnabled = applicationAddonInstalled && (isAdmin || siteApps.limit > 0);
  const currentSite = websites.find(site => String(site.id) === String(selectedWebsiteId));
  const accountLabel = currentUser?.package_name
    ? `${currentUser?.username || username} - ${currentUser.package_name}`
    : (currentUser?.username || username);

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

  // Every page opens at its top. The window is the scroller and nothing
  // reset it, so the next page opened at the last one's offset - part-way
  // down, or in empty space until its content loaded. Before paint, and
  // instant: html has scroll-behavior:smooth, which would slide there from
  // the old offset. Back and Forward land at the top as well; the browser's
  // own restoration ran before the page had content and restored nothing.
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [page]);
  useEffect(() => {
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
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

  function clearReadableSessionCookies() {
    try {
      document.cookie = 'bpanel_csrf=; Max-Age=0; path=/; SameSite=Lax';
      if (window.location.protocol === 'https:') {
        document.cookie = 'bpanel_csrf=; Max-Age=0; path=/; SameSite=Lax; Secure';
      }
    } catch {}
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
    clearReadableSessionCookies();
    setIsAuthenticated(false);
    setCurrentUser(null);
    setNeedsTwoFactor(false);
    setOtpCode('');
    setWebsites([]);
    setDatabases([]);
    setUsers([]);
    setPackages([]);
    setUserTab('list');
    setAdminAccountForm({ email: '', current_password: '', password: '', confirm_password: '', code: '' });
    setResourceUsage(null);
    setServiceStates({});
    setServiceNames(DEFAULT_SERVICE_NAMES);
    setBackupTab('website');
    setBackups([]);
    setBackupJobs([]);
    setCronItems([]);
    setCronUser('');
    setCronPhpInfo({ php_binary: '', php_version: '' });
    setChmodTarget(null);
    setFileAppId('');
    setSiteAppLog(null);
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
    setMalwareScanStatus(null);
    setScanTargetWebsiteId('');
    setScanResults(null);
    setScanJob(null);
    setScanJobs([]);
    setScanLoading(false);
    setWebsiteList([]);
    setWebsiteSearch('');
    setWebsiteSearching(false);
    setUpdatesStatus(null);
    setFirewallBlocklists(null);
    setWafRules({ status: null, default_rules: '', custom_rules: '' });
    setWafCustomRules('');
    setSelectedWafWebsiteId('');
    setWafSiteConfig(null);
    setWafAccessLogFilters(WAF_ACCESS_LOG_DEFAULTS);
    setWafAccessLogs({ items: [], total: 0, scanned: 0, missing: [], generated_at: '' });
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
      if (!signedOutRef.current) clearSession();
      return true;
    }
    return false;
  }

  async function request(path, options = {}, label = '') {
    try {
      setError('');
      if (label) setLoading(label);
      const { silent, ...fetchOptions } = options;
      const method = (fetchOptions.method || 'GET').toUpperCase();
      const isFormData = typeof FormData !== 'undefined' && fetchOptions.body instanceof FormData;
      const headers = isFormData ? { ...(fetchOptions.headers || {}) } : {
        'Content-Type': 'application/json',
        ...(fetchOptions.headers || {}),
      };
      // CSRF: echo the bpanel_csrf cookie back in a header for mutating
      // requests. The backend rejects mismatches when the request was
      // authenticated via cookie.
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const csrf = readCookie('bpanel_csrf');
        if (csrf) headers['X-CSRF-Token'] = csrf;
      }
      const res = await fetch(`${API}${path}`, {
        ...fetchOptions,
        credentials: 'include',
        headers,
      });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text || `HTTP ${res.status}` }; }
      if (!res.ok && handleAuthExpired(res.status, data.detail)) return null;
      if (!res.ok && !silent) setError(formatApiError(data.detail, `Request failed with status ${res.status}`));
      if (res.ok && data?.message && !silent) setNotice(data.message);
      return res.ok ? data : null;
    } catch (err) {
      setError(`Cannot connect to the ${panelSettings.app_name || 'BPanel'} API at ${API}. Check bpanel-api and the panel port.`);
      return null;
    } finally {
      if (label) setLoading('');
    }
  }

  async function login(passkeyAssertion = '') {
    try {
      setError('');
      setLoading('Logging in...');
      const body = new URLSearchParams({ username, password });
      // An otp and a passkey are never sent together: the customer either used
      // the key or chose the app.
      if (otpCode) body.set('otp', otpCode);
      else if (passkeyAssertion) body.set('passkey', passkeyAssertion);
      if (rememberMe) body.set('remember', 'true');
      const res = await fetch(`${API}/auth/login`, {
        method: 'POST',
        body,
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.requires_passkey) {
        // The account has a passkey for this hostname. Offer it, and remember
        // whether an authenticator app is available as the way out - a passkey
        // is bound to one hostname, so there has to be one.
        setPasskeyPrompt({ options: data.passkey_options, canUseOtp: !!data.requires_2fa });
        setNotice(t('Signed in with a passkey.'));
        await usePasskey(data.passkey_options);
      } else if (res.ok && data.requires_2fa) {
        setNeedsTwoFactor(true);
        setPasskeyPrompt(null);
        setNotice(t('Enter your authentication code.'));
      } else if (res.ok && data.access_token) {
        // Don't keep the token anywhere: the HttpOnly cookie just got set by
        // the response. JS code MUST NOT touch the JWT.
        signedOutRef.current = false;
        setIsAuthenticated(true);
        setNeedsTwoFactor(false);
        setPasskeyPrompt(null);
        setOtpCode('');
        setNotice(t('Login successful.'));
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
    signedOutRef.current = true;
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

  async function usePasskey(optionsJson) {
    if (!passkeySupported()) {
      setError(t('This browser does not support passkeys. Use the code from your authenticator app.'));
      return;
    }
    try {
      const parsed = JSON.parse(optionsJson);
      const credential = await navigator.credentials.get({
        publicKey: decodeRequestOptions(parsed),
      });
      if (!credential) return;
      await login(encodeAssertion(credential));
    } catch (err) {
      // A cancel and a hardware failure look the same here, and neither is
      // worth an alarming message: the authenticator app is still available.
      setError(t('That passkey did not work. Try again, or use the code from your authenticator app.'));
    }
  }

  async function loadPasskeyStatus() {
    const data = await request('/auth/passkey/status', { silent: true });
    if (data) setPasskeyStatus(data);
  }

  async function addPasskey() {
    if (!passkeySupported()) {
      setError(t('This browser does not support passkeys.'));
      return;
    }
    const started = await request('/auth/passkey/register/options', {
      method: 'POST',
      body: JSON.stringify({ current_password: passkeyPassword || null }),
    }, t('Preparing passkey...'));
    if (!started?.options) return;
    try {
      const parsed = JSON.parse(started.options);
      const credential = await navigator.credentials.create({
        publicKey: decodeCreationOptions(parsed),
      });
      if (!credential) return;
      const done = await request('/auth/passkey/register/verify', {
        method: 'POST',
        body: JSON.stringify({ credential: encodeRegistration(credential), name: passkeyName }),
      }, t('Saving passkey...'));
      if (done?.id) {
        setNotice(`Added passkey ${done.name}.`);
        setPasskeyPassword('');
        setPasskeyName('');
        await loadPasskeyStatus();
      }
    } catch (err) {
      setError(t('Could not create the passkey. The device may have refused it, or you cancelled.'));
    }
  }

  async function removePasskey(credential) {
    if (!confirm(`Delete passkey ${credential.name}? That device will no longer be able to sign in.`)) return;
    await request(`/auth/passkey/credentials/${credential.id}`, { method: 'DELETE' }, t('Deleting passkey...'));
    await loadPasskeyStatus();
  }

  async function loadCurrentUser({ clearOnUnauthorized = true } = {}) {
    try {
      const res = await fetch(`${API}/auth/session`, { credentials: 'include' });
      if (!res.ok) {
        if (res.status === 401) {
          if (clearOnUnauthorized && !signedOutRef.current) clearSession('Session expired.');
          else {
            clearReadableSessionCookies();
            setCurrentUser(null);
            setIsAuthenticated(false);
          }
        }
        return null;
      }
      const data = await res.json();
      if (!data.authenticated || !data.user) {
        if (clearOnUnauthorized && !signedOutRef.current) clearSession('Session expired.');
        else {
          clearReadableSessionCookies();
          setCurrentUser(null);
          setIsAuthenticated(false);
        }
        return null;
      }
      setCurrentUser(data.user);
      setAdminAccountForm(prev => ({ ...prev, email: data.user?.email || '' }));
      signedOutRef.current = false;
      setIsAuthenticated(true);
      return data.user;
    } catch {
      setCurrentUser(null);
      return null;
    }
  }

  async function loadPanelSettings() {
    // Signed in, the panel tells us more than the login page is allowed to
    // know: the hostnames it answers for and the certificates on this server
    // only come back from the authenticated route.
    const path = currentUser ? '/panel-settings' : '/panel-settings/public';
    try {
      const res = await fetch(`${API}${path}`, { credentials: 'include' });
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
      const nameData = await request('/panel-settings', {
        method: 'PATCH',
        body: JSON.stringify({ app_name: panelSettingsForm.app_name }),
      }, t('Saving panel settings...'));
      if (!nameData) return;
      const sslData = await request('/panel-settings/ssl', {
        method: 'POST',
        body: JSON.stringify({ panel_hostname: hostname, panel_port: port }),
      }, t('Installing panel SSL...'));
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
    }, t('Saving panel settings...'));
    if (data) {
      setPanelSettings(data);
      setPanelSettingsForm(formFromPanelSettings(data));
      setNotice(hasSsl && !wantsSsl ? 'Panel SSL disabled. The panel remains reachable by IP and port over HTTP.' : 'Panel settings updated.');
    }
  }

  async function saveAdminAccount() {
    const email = String(adminAccountForm.email || '').trim();
    const password = String(adminAccountForm.password || '');
    const confirmPassword = String(adminAccountForm.confirm_password || '');
    const currentPassword = String(adminAccountForm.current_password || '');
    const code = String(adminAccountForm.code || '').trim();

    if (!email) {
      setError(t('Email is required.'));
      return;
    }
    if (password && password.length < 12) {
      setError(t('Password must be at least 12 characters.'));
      return;
    }
    if (password && password !== confirmPassword) {
      setError(t('Passwords do not match.'));
      return;
    }

    const payload = { email };
    if (password) {
      if (!currentPassword) {
        setError(t('Current password is required to change password.'));
        return;
      }
      payload.password = password;
      payload.current_password = currentPassword;
      if (currentUser?.totp_enabled) {
        if (!code) {
          setError(t('Authentication code is required.'));
          return;
        }
        payload.code = code;
      }
    }

    const data = await request('/panel-settings/admin-account', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }, t('Saving admin account...'));
    if (!data) return;
    if (data.password_changed) {
      clearSession('Password changed. Please log in again.');
      return;
    }
    setAdminAccountForm(prev => ({ ...prev, current_password: '', password: '', confirm_password: '', code: '' }));
    await loadCurrentUser({ clearOnUnauthorized: false });
    setNotice(data.message || 'Admin account updated.');
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

  // Bootstrap: ask for session state without turning an anonymous visit into
  // a console-level 401.
  useEffect(() => {
    (async () => {
      try {
        await loadCurrentUser({ clearOnUnauthorized: false });
      } catch {}
      finally {
        setBootstrapping(false);
        // SSO redirect may carry an error param (e.g. suspended account).
        const urlError = new URLSearchParams(window.location.search).get('error');
        if (urlError) {
          const messages = {
            account_suspended: 'This account is suspended. Contact an administrator.',
          };
          setError(messages[urlError] || urlError);
          window.history.replaceState({}, '', window.location.pathname);
        }
      }
    })();
  }, []);

  useEffect(() => { loadPanelSettings(); loadAppVersion(); }, []);

  useEffect(() => {
    const appName = panelSettings.app_name || 'BPanel';
    document.title = appName;
    const configuredFaviconUrl = panelSettings.favicon_url || '/favicon.png';
    const faviconUrl = configuredFaviconUrl.includes('?')
      ? configuredFaviconUrl
      : `${configuredFaviconUrl}?v=${encodeURIComponent(appVersion || 'current')}`;
    const pathname = faviconUrl.split('?', 1)[0].toLowerCase();
    const faviconType = pathname.endsWith('.ico') ? 'image/x-icon'
      : pathname.endsWith('.jpg') || pathname.endsWith('.jpeg') ? 'image/jpeg'
        : pathname.endsWith('.webp') ? 'image/webp'
          : 'image/png';
    document.querySelectorAll('link[rel~="icon"]').forEach(link => link.remove());
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = faviconType;
    link.href = faviconUrl;
    document.head.appendChild(link);
  }, [panelSettings, appVersion]);

  async function refreshAll() {
    const refreshedUser = await loadCurrentUser();
    const siteData = await request('/websites');
    if (siteData) {
      setWebsites(siteData);
      if (!websiteSearch.trim()) setWebsiteList(siteData);
      if (!selectedWebsiteId && siteData[0]) setSelectedWebsiteId(String(siteData[0].id));
    }
    const dbData = await request(dbSearch.trim() ? `/databases?q=${encodeURIComponent(dbSearch.trim())}` : '/databases');
    if (dbData) setDatabases(dbData);
    if (refreshedUser?.role === 'admin') {
      await loadPhpVersions();
      await loadPackages();
    }
    if (page === 'websites' && websiteSearch.trim()) await loadWebsiteList(websiteSearch, false);
  }

  async function loadWebsiteList(search = websiteSearch, showLoading = false) {
    const query = String(search || '').trim();
    const suffix = query ? `?q=${encodeURIComponent(query)}` : '';
    setWebsiteSearching(true);
    const data = await request(`/websites${suffix}`, {}, showLoading ? 'Loading websites...' : '');
    setWebsiteSearching(false);
    if (data) {
      setWebsiteList(data);
      if (!query) setWebsites(data);
      if (!selectedWebsiteId && data[0]) setSelectedWebsiteId(String(data[0].id));
    }
  }

  async function loadDatabases(search = dbSearch, showLoading = false) {
    const query = String(search || '').trim();
    const suffix = query ? `?q=${encodeURIComponent(query)}` : '';
    setDbSearching(true);
    const data = await request(`/databases${suffix}`, {}, showLoading ? 'Loading databases...' : '');
    setDbSearching(false);
    if (data) setDatabases(data);
  }

  async function loadPackages() {
    const data = await request('/packages');
    if (data) setPackages(data);
  }

  async function loadApiTokens() {
    const data = await request('/provisioning/v1/tokens');
    if (data) setApiTokens(data);
  }

  async function createApiToken() {
    if (!newApiToken.name.trim()) { setError(t('Token name is required.')); return; }
    const data = await request('/provisioning/v1/tokens', {
      method: 'POST',
      body: JSON.stringify({
        name: newApiToken.name.trim(),
        scopes: 'provisioning:read,provisioning:write',
        allowed_ips: newApiToken.allowed_ips.trim(),
      }),
    }, t('Creating API token...'));
    if (data) {
      setCreatedApiToken(data.token || '');
      setNotice(t('API token created. Copy it now; it will not be shown again. Paste it into WHMCS Server Access Hash.'));
      setNewApiToken({ name: 'WHMCS', allowed_ips: '' });
      await loadApiTokens();
    }
  }

  async function copyApiToken() {
    if (!createdApiToken) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(createdApiToken);
      } else {
        const input = document.getElementById('created-api-token');
        input?.focus();
        input?.select();
        document.execCommand('copy');
      }
      setNotice(t('API token copied. Paste it into WHMCS Server Access Hash.'));
    } catch {
      const input = document.getElementById('created-api-token');
      input?.focus();
      input?.select();
      setError(t('Copy failed. The token is selected; press Ctrl+C.'));
    }
  }

  async function revokeApiToken(token) {
    if (!confirm(`Revoke API token ${token.name}? WHMCS using it will stop working.`)) return;
    const data = await request(`/provisioning/v1/tokens/${token.id}`, { method: 'DELETE' }, `Revoking ${token.name}...`);
    if (data) {
      setNotice(`Revoked API token ${token.name}.`);
      await loadApiTokens();
    }
  }

  // Disk usage costs a filesystem walk per account, so the list arrives first
  // and the figures follow. Rows come back with storage_used_bytes = -1 when
  // the panel has not measured them recently; this fills those in.
  async function loadUserStorageUsage() {
    const usage = await request('/users/storage-usage', { silent: true });
    if (!usage) return;
    setUsers(prev => prev.map(user => {
      const found = usage[String(user.id)];
      return found ? { ...user, ...found } : user;
    }));
  }

  async function loadUsers() {
    const data = await request('/users');
    if (data) {
      setUsers(data);
      if (data.some(user => Number(user.storage_used_bytes) < 0)) loadUserStorageUsage();
      if (!selectedBackupUserId && data[0]) setSelectedBackupUserId(String(data[0].id));
      setNewBackupSchedule(prev => (!prev.all_users && (!prev.user_ids || prev.user_ids.length === 0) && data[0]) ? ({ ...prev, user_ids: [String(data[0].id)] }) : prev);
    }
  }

  // One request for the dashboard's cards and its "Needs attention" list;
  // each part is best effort on the server, so a failing probe is a card
  // that says "—", not a dashboard that fails.
  async function loadDashboardSummary() {
    const data = await request('/dashboard/summary', { silent: true });
    if (data) setDashSummary(data);
  }

  async function loadResourceUsage() {
    const data = await request('/services/resource-usage');
    if (data) setResourceUsage(data);
  }

  async function createUser() {
    const payload = {
      ...newUser,
      package_id: newUser.package_id ? Number(newUser.package_id) : null,
      website_limit: Number(newUser.website_limit),
      storage_limit_mb: Number(newUser.storage_limit_mb),
      sftp_accounts_limit: Number(newUser.sftp_accounts_limit || 0),
    };
    const data = await request('/users', { method: 'POST', body: JSON.stringify(payload) }, t('Creating user...'));
    if (data) {
      setNotice(`Created user ${data.username}`);
      setNewUser({ username: '', email: '', password: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0 });
      await loadUsers();
      setUserTab('list');
    }
  }

  function applyPackageToNewUser(packageId) {
    const selected = packages.find(item => String(item.id) === String(packageId));
    setNewUser(prev => ({
      ...prev,
      package_id: packageId,
      website_limit: selected ? selected.website_limit : 5,
      storage_limit_mb: selected ? selected.storage_limit_mb : 1024,
      sftp_accounts_limit: selected ? (selected.sftp_accounts_limit || 0) : 0,
    }));
  }

  function applyPackageToEditingUser(packageId) {
    const selected = packages.find(item => String(item.id) === String(packageId));
    setEditingUserForm(prev => ({
      ...prev,
      package_id: packageId,
      website_limit: selected ? selected.website_limit : 5,
      storage_limit_mb: selected ? selected.storage_limit_mb : 1024,
      sftp_accounts_limit: selected ? (selected.sftp_accounts_limit || 0) : 0,
    }));
  }

  function startEditingUser(user) {
    setEditingUser(user);
    setEditingUserForm({
      email: user.email || '',
      role: user.role || 'end_user',
      package_id: user.package_id ? String(user.package_id) : '',
      website_limit: user.website_limit ?? 5,
      storage_limit_mb: user.storage_limit_mb ?? 1024,
      sftp_accounts_limit: user.sftp_accounts_limit ?? 0,
      new_password: '',
      confirm_password: '',
    });
  }

  function cancelEditingUser() {
    setEditingUser(null);
    setEditingUserForm({ email: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, new_password: '', confirm_password: '' });
    setNewPackage({ name: '', website_limit: 5, storage_limit_mb: 1024 });
    setEditingPackageId('');
    setEditingPackageForm({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0 });
  }

  async function updatePanelUser() {
    if (!editingUser) return;
    const websiteLimit = Number(editingUserForm.website_limit);
    const storageLimitMb = Number(editingUserForm.storage_limit_mb);
    if (!editingUserForm.email.trim()) { setError(t('Email is required.')); return; }
    if (!Number.isInteger(websiteLimit) || websiteLimit < 0 || websiteLimit > 1000) {
      setError(t('Website limit must be between 0 and 1000.'));
      return;
    }
    if (!Number.isInteger(storageLimitMb) || storageLimitMb < 0 || storageLimitMb > 1024 * 1024) {
      setError(t('Storage limit must be between 0 and 1048576 MB.'));
      return;
    }
    const payload = {
      email: editingUserForm.email.trim(),
      package_id: editingUserForm.package_id ? Number(editingUserForm.package_id) : null,
      website_limit: websiteLimit,
      storage_limit_mb: storageLimitMb,
      sftp_accounts_limit: Number(editingUserForm.sftp_accounts_limit || 0),
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

  async function submitPasswordChange(user) {
    if (!user) return;
    const pw = editingUserForm.new_password;
    if (pw.length < 12) { setError(t('Password must be at least 12 characters.')); return; }
    if (pw !== editingUserForm.confirm_password) { setError(t('Passwords do not match.')); return; }
    const payload = { password: pw };
    if (user.id === currentUser?.id) {
      const currentPassword = prompt('Enter your current password to confirm this change:');
      if (!currentPassword) return;
      payload.current_password = currentPassword;
      if (currentUser?.totp_enabled) {
        const code = prompt('Enter the 6-digit code from your authenticator:');
        if (!code) return;
        payload.code = code.trim();
      }
    }
    const data = await request(`/users/${user.id}/password`, { method: 'POST', body: JSON.stringify(payload) }, `Changing password for ${user.username}...`);
    if (data?.message) {
      setNotice(data.message);
      setEditingUserForm(prev => ({ ...prev, new_password: '', confirm_password: '' }));
    }
  }

  async function createPackage() {
    const websiteLimit = Number(newPackage.website_limit);
    const storageLimitMb = Number(newPackage.storage_limit_mb);
    if (!newPackage.name.trim()) { setError(t('Package name is required.')); return; }
    if (!Number.isInteger(websiteLimit) || websiteLimit < 0 || websiteLimit > 1000) {
      setError(t('Website limit must be between 0 and 1000.'));
      return;
    }
    if (!Number.isInteger(storageLimitMb) || storageLimitMb < 0 || storageLimitMb > 1024 * 1024) {
      setError(t('Storage limit must be between 0 and 1048576 MB.'));
      return;
    }
    const data = await request('/packages', {
      method: 'POST',
      body: JSON.stringify({ name: newPackage.name.trim(), website_limit: websiteLimit, storage_limit_mb: storageLimitMb, sftp_accounts_limit: Number(newPackage.sftp_accounts_limit || 0) }),
    }, t('Creating package...'));
    if (data) {
      setNotice(`Created package ${data.name}.`);
      setNewPackage({ name: '', website_limit: 5, storage_limit_mb: 1024 });
      await loadPackages();
    }
  }

  function startEditingPackage(item) {
    setEditingPackageId(String(item.id));
    setEditingPackageForm({
      name: item.name || '',
      website_limit: item.website_limit ?? 5,
      storage_limit_mb: item.storage_limit_mb ?? 1024,
      sftp_accounts_limit: item.sftp_accounts_limit ?? 0,
    });
  }

  function cancelEditingPackage() {
    setEditingPackageId('');
    setEditingPackageForm({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0 });
  }

  async function updatePackage(packageId) {
    const websiteLimit = Number(editingPackageForm.website_limit);
    const storageLimitMb = Number(editingPackageForm.storage_limit_mb);
    if (!editingPackageForm.name.trim()) { setError(t('Package name is required.')); return; }
    if (!Number.isInteger(websiteLimit) || websiteLimit < 0 || websiteLimit > 1000) {
      setError(t('Website limit must be between 0 and 1000.'));
      return;
    }
    if (!Number.isInteger(storageLimitMb) || storageLimitMb < 0 || storageLimitMb > 1024 * 1024) {
      setError(t('Storage limit must be between 0 and 1048576 MB.'));
      return;
    }
    const data = await request(`/packages/${packageId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name: editingPackageForm.name.trim(), website_limit: websiteLimit, storage_limit_mb: storageLimitMb, sftp_accounts_limit: Number(editingPackageForm.sftp_accounts_limit || 0) }),
    }, t('Updating package...'));
    if (data) {
      setNotice(`Updated package ${data.name}.`);
      cancelEditingPackage();
      await loadPackages();
      await loadUsers();
    }
  }

  async function deletePackage(item) {
    if (!confirm(`Delete package ${item.name}?`)) return;
    const data = await request(`/packages/${item.id}`, { method: 'DELETE' }, `Deleting ${item.name}...`);
    if (data) {
      setNotice(`Deleted package ${item.name}.`);
      if (String(editingPackageId) === String(item.id)) cancelEditingPackage();
      await loadPackages();
    }
  }

  async function changeUserPassword(user) {
    const password = prompt(`Enter a new password for ${user.username} (minimum 12 characters):`);
    if (!password) return;
    if (password.length < 12) { setError(t('Password must be at least 12 characters.')); return; }
    const payload = { password };
    if (user.id === currentUser?.id) {
      const currentPassword = prompt('Enter your current password to confirm this change:');
      if (!currentPassword) return;
      payload.current_password = currentPassword;
      if (currentUser?.totp_enabled) {
        const code = prompt('Enter the 6-digit code from your authenticator:');
        if (!code) return;
        payload.code = code.trim();
      }
    }
    const data = await request(`/users/${user.id}/password`, { method: 'POST', body: JSON.stringify(payload) }, `Changing password for ${user.username}...`);
    if (data?.message) setNotice(data.message);
  }

  async function deletePanelUser(user) {
    if (!user || user.id === currentUser?.id) return;
    if (!confirm(`Delete panel user ${user.username} and permanently delete all owned websites, files, databases, SSL certificates, and Linux user data?`)) return;
    const data = await request(`/users/${user.id}`, { method: 'DELETE' }, `Deleting user ${user.username}...`);
    if (data) {
      const count = data.deleted_websites?.length || 0;
      setNotice(count
        ? t('Deleted user {name} and {n} website(s)', { name: user.username, n: count })
        : t('Deleted user {name}', { name: user.username }));
      await loadUsers();
      await refreshAll();
    }
  }

  async function suspendUser(user) {
    if (!user || user.id === currentUser?.id) return;
    const siteCount = websites.filter(w => w.owner_id === user.id).length;
    if (!confirm(t('Suspend user {name}? This will block login, disable all {n} website(s), lock SFTP, and kill active sessions.', { name: user.username, n: siteCount }))) return;
    const data = await request(`/users/${user.id}/suspend`, { method: 'POST' }, `Suspending user ${user.username}...`);
    if (data) {
      await loadUsers();
      await refreshAll();
    }
  }

  async function unsuspendUser(user) {
    if (!user || user.id === currentUser?.id) return;
    if (!confirm(`Unsuspend user ${user.username}? This will restore login, websites, and SFTP access.`)) return;
    const data = await request(`/users/${user.id}/unsuspend`, { method: 'POST' }, `Unsuspending user ${user.username}...`);
    if (data) {
      await loadUsers();
      await refreshAll();
    }
  }

  async function quickLoginUser(user) {
    if (!user) return;
    const suspendedNote = user.is_active ? '' : ' This user is SUSPENDED — websites and SFTP are disabled.';
    if (!confirm(`Login as ${user.username}?${suspendedNote}`)) return;
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

  async function loadTwoFactorStatus() {
    const data = await request('/auth/2fa/status');
    if (data) setTwoFactorStatus(data);
  }

  async function setupTwoFactorAuth() {
    const currentPassword = prompt('Enter your current password to generate a new 2FA secret:');
    if (!currentPassword) return;
    const payload = { current_password: currentPassword };
    if (currentUser?.totp_enabled) {
      const code = prompt('Enter the 6-digit code from your authenticator:');
      if (!code) return;
      payload.code = code.trim();
    }
    const data = await request('/auth/2fa/setup', { method: 'POST', body: JSON.stringify(payload) }, t('Preparing 2FA...'));
    if (data) {
      setTwoFactorSetup(data);
      setTwoFactorStatus({ enabled: false });
    }
  }

  async function enableTwoFactorAuth() {
    const data = await request('/auth/2fa/enable', { method: 'POST', body: JSON.stringify({ code: twoFactorCode }) }, t('Enabling 2FA...'));
    if (data) {
      setTwoFactorStatus(data);
      setTwoFactorSetup(null);
      setTwoFactorCode('');
      await loadCurrentUser();
      setNotice(t('2FA enabled.'));
    }
  }

  async function disableTwoFactorAuth() {
    const currentPassword = prompt('Enter your current password to disable 2FA:');
    if (!currentPassword) return;
    const data = await request(
      '/auth/2fa/disable',
      { method: 'POST', body: JSON.stringify({ current_password: currentPassword, code: twoFactorCode }) },
      'Disabling 2FA...',
    );
    if (data) {
      setTwoFactorStatus(data);
      setTwoFactorCode('');
      await loadCurrentUser();
      setNotice(t('2FA disabled.'));
    }
  }

  async function resetUserTwoFactor(user) {
    if (!confirm(`Reset 2FA for ${user.username}?`)) return;
    const data = await request(`/users/${user.id}/2fa/reset`, { method: 'POST' }, `Resetting 2FA for ${user.username}...`);
    if (data?.message) { setNotice(data.message); await loadUsers(); }
  }

  async function loadMalwareScanStatus() {
    const data = await request('/malware/status', {}, t('Loading scanner status...'));
    if (data) setMalwareScanStatus(data);
  }

  async function toggleIpv6(enable) {
    const ipv6 = panelSettings.ipv6 || {};
    if (enable && !ipv6.available) {
      setError(ipv6.detail || 'This server has no IPv6 address, so this feature cannot be used.');
      return;
    }
    if (!confirm(t(enable
      ? 'Enable IPv6 for every website and the panel?\n\nBPanel adds listen [::] to every website\'s nginx config, checks it with nginx -t, and rolls back on any error. The panel restarts.'
      : 'Disable IPv6?\n\nWebsites and the panel will accept IPv4 only. If a domain still has an AAAA record, visitors arriving over IPv6 will not get through.'))) return;
    const data = await request('/panel-settings/ipv6', {
      method: 'POST',
      body: JSON.stringify({ enabled: enable }),
    }, enable ? 'Enabling IPv6...' : 'Disabling IPv6...');
    if (data) {
      setPanelSettings(data);
      setNotice(data.message || (enable ? 'IPv6 enabled.' : 'IPv6 disabled.'));
    }
  }

  async function toggleMalwareScan(enable) {
    if (enable && !malwareScanStatus?.installed) {
      if (!confirm(t('The scanner is not installed on this server yet. The panel will install it now (1-2 minutes). Continue?'))) return;
    }
    const data = await request('/malware/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled: enable }),
    }, enable ? 'Enabling the scanner...' : 'Disabling the scanner...');
    if (data) {
      setPanelSettings(data);
      setNotice(data.message || `Scanner ${enable ? 'enabled' : 'disabled'}.`);
      await loadMalwareScanStatus();
    }
  }

  async function loadMalwareSchedule() {
    const data = await request('/malware/schedule', { silent: true }, '');
    if (data) {
      setMalwareSchedules(data);
      setMalwareSchedulesForm(data);
    }
  }

  async function saveMalwareSchedule() {
    const f = malwareSchedulesForm;
    if (f.server?.enabled && malwareScanStatus?.memory_warning) {
      if (!confirm(`${malwareScanStatus.memory_warning}\n\nSchedule the whole-server scan anyway?`)) return;
    }
    const body = {};
    for (const name of ['websites', 'server']) {
      const e = f[name] || {};
      body[name] = { enabled: !!e.enabled, weekday: Number(e.weekday ?? 6), hour: Number(e.hour ?? 3) };
    }
    const data = await request('/malware/schedule', { method: 'PUT', body: JSON.stringify(body) }, t('Saving scan schedule...'));
    if (data) {
      setMalwareSchedules(data);
      setMalwareSchedulesForm(data);
      const on = ['websites', 'server'].filter(n => data[n]?.enabled).map(n => MALWARE_SCHEDULE_LABELS[n]);
      setNotice(on.length ? `Schedule saved: ${on.join(', ')}.` : 'All scan schedules turned off.');
    }
  }

  async function toggleMalwareRealtime(enabled) {
    if (enabled && !confirm(t('Turn on real-time protection? The panel watches website directories and scans new files as they appear. If it is not installed yet, the panel installs it (1-3 minutes).'))) return;
    const data = await request('/malware/realtime', { method: 'POST', body: JSON.stringify({ enabled }) },
      enabled ? 'Turning on real-time protection...' : 'Turning off...');
    if (data) { setMalwareScanStatus(data); setNotice(t(enabled ? 'Real-time protection is on (level 2).' : 'Real-time protection is off.')); }
  }

  async function toggleMalwareScanOnUpload(enabled) {
    if (enabled && !mw.clamd_running && !confirm(
      'This server has no resident clamd, so every uploaded file reloads the whole signature database: '
      + 'measured at 28 seconds and over 1 GB of RAM for a 20 MB file. The scan runs in the background so nobody waits on it, '
      + 'but the server pays that for every file. Turn it on anyway?')) return;
    const data = await request('/malware/scan-on-upload', { method: 'POST', body: JSON.stringify({ enabled }) },
      enabled ? 'Turning on scan-on-upload...' : 'Turning off...');
    if (data) { setMalwareScanStatus(data); setNotice(enabled ? 'Uploaded files are scanned.' : 'Uploaded files are no longer scanned.'); }
  }

  async function installLmd() {
    const data = await request('/malware/lmd/install', { method: 'POST' }, t('Installing...'));
    if (data) { setMalwareScanStatus(data); setNotice(t('Installing the scanner in the background (1-3 minutes). Press Refresh for an update.')); }
  }

  async function updateMalwareSignatures() {
    const data = await request('/malware/lmd/update-sigs', { method: 'POST' }, t('Updating signatures...'));
    if (data) { setMalwareScanStatus(data); setNotice(data.message || 'Signatures updated.'); }
  }

  async function runMalwareScan() {
    if (!scanTargetWebsiteId) return;
    if (scanTargetWebsiteId === 'server' && malwareScanStatus?.memory_warning) {
      if (!confirm(`${malwareScanStatus.memory_warning}\n\nScan the whole server anyway?`)) return;
    }
    setScanResults(null);
    setScanJob(null);
    setScanLoading(true);
    try {
      const body = scanTargetWebsiteId === 'server'
        ? { server: true }
        : scanTargetWebsiteId === 'incremental'
        ? { mode: 'incremental', days: Number(incrementalDays) || 2 }
        : scanTargetWebsiteId === 'all'
        ? { all: true }
        : { website_id: Number(scanTargetWebsiteId) };
      const data = await request('/malware/run', {
        method: 'POST',
        body: JSON.stringify(body),
      }, t('Starting scan...'));
      if (data) {
        setScanJob(data);
        await loadMalwareScanJobs();
        setNotice(t('Scan started.'));
      }
    } finally {
      setScanLoading(false);
    }
  }

  async function loadMalwareScanJob(jobId) {
    const data = await request(`/malware/jobs/${jobId}`, {}, '');
    if (!data) return null;
    if (['done', 'infected', 'error', 'interrupted'].includes(data.status)) {
      setScanLoading(false);
      setScanJob(null);
      setScanResults(null);
      if (data.status === 'infected' || data.infected > 0) {
        setNotice(`${data.infected} threats found.`);
      } else if (['error', 'interrupted'].includes(data.status)) {
        setError(data.error || data.message || 'Scan failed.');
      } else {
        setNotice(`Scan finished: ${data.scanned || 0} files checked, nothing found.`);
      }
      await loadMalwareScanJobs();
    } else {
      setScanJob(data);
    }
    return data;
  }

  async function loadMalwareScanJobs() {
    const data = await request('/malware/jobs', { silent: true }, '');
    if (data?.jobs) setScanJobs(data.jobs);
    return data?.jobs || [];
  }

  function showMalwareScanJob(job) {
    setScanJob(job);
    setScanResults(job);
    setScanLoading(['queued', 'running'].includes(job?.status));
  }

  async function loadLatestMalwareScanJob() {
    const data = await request('/malware/jobs/latest', { silent: true }, '');
    if (!data) return null;
    if (['done', 'infected', 'error', 'interrupted'].includes(data.status)) {
      setScanJob(null);
      setScanResults(null);
      setScanLoading(false);
    } else {
      setScanJob(data);
    }
    return data;
  }

  async function startClamavDaemon() {
    const data = await request('/malware/start-daemon', { method: 'POST' }, t('Starting ClamAV daemon...'));
    if (data) {
      setNotice(data.message || 'ClamAV daemon started.');
      await loadMalwareScanStatus();
    }
  }

  async function assignDomainToUser() {
    if (!assignWebsiteId || !assignUserId) return;
    const data = await request(`/websites/${assignWebsiteId}`, { method: 'PATCH', body: JSON.stringify({ owner_id: Number(assignUserId) }) }, t('Assigning domain to user...'));
    if (data) { setNotice(`Assigned domain ${data.domain} to user ID ${assignUserId}`); await refreshAll(); }
  }

  async function createWordPress() {
    const cleanDomain = domain.trim().toLowerCase();
    const cleanAdminEmail = adminEmail.trim();
    if (!cleanDomain) { setError(t('Please enter a domain name.')); return; }
    const installWp = siteType === 'wordpress' && installWordPress;
    if (siteType === 'application' && !createSiteAppId) {
      setError(t('Pick which application this website should serve.'));
      return;
    }
    const body = {
      domain: cleanDomain,
      php_version: phpVersion,
      app_type: siteType,
      install_wordpress: installWp,
      title: cleanDomain,
    };
    if (siteType === 'application') body.app_id = Number(createSiteAppId);
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
      } else if (siteType === 'application') {
        setNotice(`Created ${cleanDomain}, serving the selected application.`);
        setCreateSiteAppId('');
      } else {
        setNotice(`Created site ${cleanDomain}. Upload your files to public_html/ folder.`);
      }
      if (createSslMode !== 'none') await applyCreateSsl(data.id, cleanDomain);
      refreshAll();
    }
  }

  async function deleteWebsite(id) {
    if (!confirm(t('Delete this website including files, vhost, database, and its SSL certificate?'))) return;
    const data = await request(`/websites/${id}?delete_files=true&delete_database=true`, { method: 'DELETE' }, t('Deleting website...'));
    if (data) refreshAll();
  }

  async function enableSsl(id) {
    const data = await request(`/websites/${id}/ssl`, { method: 'POST' }, "Installing Let's Encrypt SSL...");
    if (data) refreshAll();
  }

  // Run the SSL step chosen in the "Create website" form, on the site that was
  // just created. The site already exists at this point, so a failure here is
  // reported but never rolls the site back — the operator can retry from the
  // SSL page.
  async function applyCreateSsl(id, siteDomain) {
    if (createSslMode === 'letsencrypt') {
      await enableSsl(id);
      return;
    }
    if (createSslMode === 'wildcard') {
      const body = {};
      if (createSslToken.trim()) body.cloudflare_api_token = createSslToken.trim();
      const data = await request(`/websites/${id}/ssl/wildcard`,
        { method: 'POST', body: JSON.stringify(body) },
        'Issuing wildcard certificate via Cloudflare...');
      if (data) {
        setCreateSslToken('');
        setNotice(`Created ${siteDomain}. Wildcard SSL active — *.${data.ssl_source_domain} covers it.`);
      }
      return;
    }
    if (createSslMode === 'shared') {
      const sources = await request(`/websites/${id}/ssl/sources`, { silent: true });
      const list = Array.isArray(sources) ? sources : [];
      if (!list.length) {
        setError(`Created ${siteDomain}, but no existing certificate covers it. Enable SSL from the SSL page.`);
        return;
      }
      // Prefer a wildcard cert, then the longest-matching source domain.
      const pick = [...list].sort((a, b) =>
        (b.wildcard - a.wildcard) || (b.domain.length - a.domain.length))[0];
      const data = await request(`/websites/${id}/ssl/shared`,
        { method: 'POST', body: JSON.stringify({ source_domain: pick.domain }) },
        `Using ${pick.domain}'s certificate...`);
      if (data) setNotice(`Created ${siteDomain}, now serving ${pick.domain}'s certificate.`);
      return;
    }
    if (createSslMode === 'manual') {
      // Manual SSL needs the cert and key pasted in; send the operator to the
      // SSL page for this site to finish it there.
      setSelectedWebsiteId(String(id));
      setNotice(`Created ${siteDomain}. Open the Manual tab on the SSL page to paste its certificate.`);
      navigateToPage('ssl');
    }
  }

  async function addWebsiteAlias(site) {
    const cleanAlias = String(aliasDrafts[site.id] || '').trim().toLowerCase();
    const aliasMode = aliasModes[site.id] || 'alias';
    if (!cleanAlias) { setError(t('Enter a domain.')); return; }
    const data = await request(`/websites/${site.id}/aliases`, {
      method: 'POST',
      body: JSON.stringify({ domain: cleanAlias, mode: aliasMode }),
    }, `Adding ${aliasMode === 'redirect' ? 'redirect' : 'alias'} ${cleanAlias}...`);
    if (data) {
      const label = aliasMode === 'redirect' ? 'redirect' : 'alias';
      // Adding a domain only wires it into Nginx - same split DirectAdmin
      // uses. Getting it a certificate is the separate, explicit step on the
      // SSL page (Install / Renew SSL there already asks for every alias and
      // redirect), so nothing SSL-related is attempted or claimed here.
      setNotice(site.ssl_mode === 'letsencrypt' && !data.ssl_enabled
        ? `Added ${label} ${cleanAlias}. Go to the SSL page and press "Install / Renew SSL" to issue a certificate for it.`
        : `Added ${label} ${cleanAlias}.`);
      setAliasDrafts(prev => ({ ...prev, [site.id]: '' }));
      setNginxCustomEditing(prev => {
        if (!prev || prev.id !== site.id) return prev;
        const nextSite = prev.site || site;
        return { ...prev, site: { ...nextSite, aliases: [...(nextSite.aliases || []), data] } };
      });
      await refreshAll();
    }
  }

  async function deleteWebsiteAlias(site, alias) {
    const label = alias.mode === 'redirect' ? 'redirect' : 'alias';
    if (!confirm(`Remove ${label} ${alias.domain} from ${site.domain}?`)) return;
    const data = await request(`/websites/${site.id}/aliases/${alias.id}`, { method: 'DELETE' }, `Removing ${label} ${alias.domain}...`);
    if (data) {
      setNotice(`Removed ${label} ${alias.domain}.`);
      setNginxCustomEditing(prev => {
        if (!prev || prev.id !== site.id) return prev;
        const nextSite = prev.site || site;
        return { ...prev, site: { ...nextSite, aliases: (nextSite.aliases || []).filter(item => item.id !== alias.id) } };
      });
      await refreshAll();
    }
  }

  async function installManualSsl() {
    if (!selectedWebsiteId) return;
    const hasCert = manualSslFiles.certificate || manualSslForm.certificate.trim();
    const hasKey = manualSslFiles.private_key || manualSslForm.private_key.trim();
    if (!hasCert || !hasKey) {
      setError(t('Certificate and private key are required.'));
      return;
    }
    const form = new FormData();
    if (manualSslFiles.certificate) form.append('certificate', manualSslFiles.certificate);
    else form.append('certificate_text', manualSslForm.certificate);
    if (manualSslFiles.private_key) form.append('private_key', manualSslFiles.private_key);
    else form.append('private_key_text', manualSslForm.private_key);
    if (manualSslFiles.ca_bundle) form.append('ca_bundle', manualSslFiles.ca_bundle);
    else if (manualSslForm.ca_bundle.trim()) form.append('ca_bundle_text', manualSslForm.ca_bundle);
    const data = await request(`/websites/${selectedWebsiteId}/ssl/manual`, { method: 'POST', body: form }, t('Installing manual SSL...'));
    if (data) {
      setManualSslForm({ certificate: '', private_key: '', ca_bundle: '' });
      setManualSslFiles({ certificate: null, private_key: null, ca_bundle: null });
      refreshAll();
    }
  }

  async function loadCfZone(id) {
    const data = await request(`/websites/${id}/ssl/cloudflare-zone`, { silent: true });
    if (data) setCfZone({ zone: data.zone || null, has_token: !!data.has_token });
  }

  async function loadSslSources(id) {
    const data = await request(`/websites/${id}/ssl/sources`, { silent: true });
    setSslSources(Array.isArray(data) ? data : []);
  }

  async function installWildcardSsl() {
    if (!selectedWebsiteId) return;
    const body = {};
    if (wildcardToken.trim()) body.cloudflare_api_token = wildcardToken.trim();
    else if (!cfZone.has_token) { setError(t('Paste a Cloudflare API token (Zone.DNS Edit).')); return; }
    const data = await request(`/websites/${selectedWebsiteId}/ssl/wildcard`,
      { method: 'POST', body: JSON.stringify(body) }, t('Issuing wildcard certificate via Cloudflare...'));
    if (data) {
      setWildcardToken('');
      setNotice(`Wildcard SSL active — *.${data.ssl_source_domain} covers this site.`);
      refreshAll();
    }
  }

  async function installSharedSsl() {
    if (!selectedWebsiteId || !sharedSource) return;
    const data = await request(`/websites/${selectedWebsiteId}/ssl/shared`,
      { method: 'POST', body: JSON.stringify({ source_domain: sharedSource }) },
      `Using ${sharedSource}'s certificate...`);
    if (data) {
      setNotice(`Now serving ${sharedSource}'s certificate.`);
      refreshAll();
    }
  }

  async function openNginxCustom(site) {
    setWordpressInstaller(null);
    setLogViewer(null);
    setTerminalViewer(null);
    setWebsiteSettingsForm(websiteConfigForm(site));
    const data = await request(`/websites/${site.id}/nginx-custom`, {}, t('Loading Custom Nginx...'));
    if (data !== null) {
      setNginxCustomEditing({
        id: site.id,
        domain: site.domain,
        site,
        mode: 'custom',
        content: data?.nginx_custom || '',
      });
      await loadSiteApps();
    }
  }

  async function loadSiteApps() {
    const data = await request('/site-apps', { silent: true });
    if (data) setSiteApps({ port_range: [21000, 21999], ...data });
  }

  async function loadAddons() {
    const data = await request('/addons', { silent: true });
    setAddons({ items: data?.items || [], can_manage: !!data?.can_manage, loaded: true });
  }

  async function setAddonInstalled(slug, install) {
    const addon = addons.items.find(item => item.slug === slug);
    const label = addon?.name || slug;
    if (!install && !confirm(`Remove the ${label} addon?\n\nAnything running is stopped. Directories, volumes and panel data stay exactly where they are, and installing again picks up from there.`)) return;
    const data = await request(`/addons/${slug}/${install ? 'install' : 'uninstall'}`, { method: 'POST' },
      install ? `Installing ${label}...` : `Removing ${label}...`);
    if (data) {
      setNotice(install
        ? `${label} installed. ${data.next_step || ''}`.trim()
        : `${label} removed.${data.stopped?.length ? ` Stopped ${data.stopped.length} app(s).` : ''}`);
      await loadAddons();
      // The nav and the website mode picker both hang off this.
      if (install) await loadSiteApps();
      else if (page === 'applications') navigateToPage('dashboard');
    }
  }

  async function validateCompose(source, webService, env, webPort) {
    return await request('/site-apps/compose/validate', {
      method: 'POST',
      body: JSON.stringify({
        compose_source: source,
        web_service: webService || null,
        env: env || '',
        web_port: Number(webPort) || null,
      }),
    }, t('Checking the compose file...'));
  }

  async function checkComposeFile() {
    const data = await validateCompose(siteAppDraft.compose_source, siteAppDraft.web_service, siteAppDraft.env, siteAppDraft.container_port);
    if (data) {
      setComposePlan(data);
      if (data.web_service && !siteAppDraft.web_service) {
        setSiteAppDraft(prev => ({ ...prev, web_service: data.web_service }));
      }
    }
  }

  function openSiteAppEdit(app) {
    if (siteAppEdit?.id === app.id) { setSiteAppEdit(null); setSiteAppEditPlan(null); return; }
    setSiteAppEditPlan(null);
    setSiteAppEdit({
      id: app.id,
      kind: app.kind,
      compose_source: app.compose_source || '',
      web_service: app.web_service || '',
      container_port: app.container_port || '',
      env: app.env || '',
    });
  }

  async function checkSiteAppEdit() {
    const data = await validateCompose(siteAppEdit.compose_source, siteAppEdit.web_service, siteAppEdit.env, siteAppEdit.container_port);
    if (data) {
      setSiteAppEditPlan(data);
      if (data.web_service && !siteAppEdit.web_service) {
        setSiteAppEdit(prev => ({ ...prev, web_service: data.web_service }));
      }
    }
  }

  async function saveSiteAppEdit(app) {
    const patch = app.kind === 'compose'
      ? {
          compose_source: siteAppEdit.compose_source,
          web_service: siteAppEdit.web_service || null,
          env: siteAppEdit.env,
          container_port: Number(siteAppEdit.container_port) || null,
        }
      : { env: siteAppEdit.env };
    const data = await request(`/site-apps/${app.id}`, { method: 'PUT', body: JSON.stringify(patch) }, t('Saving configuration...'));
    if (data) {
      setSiteAppEdit(null);
      setSiteAppEditPlan(null);
      setNotice(`Saved ${data.name}.`);
      await loadSiteApps();
    }
  }

  async function loadSiteRuntimes() {
    const data = await request('/site-runtimes/status', { silent: true });
    if (data) setSiteRuntimes(data);
  }

  async function deploySiteApp(app) {
    const data = await request(`/site-apps/${app.id}/deploy`, { method: 'POST' }, `Deploying ${app.name}...`);
    if (data) {
      setNotice(data.running ? `${app.name} is running on port ${app.port}.` : `${app.name} was deployed but is not running — check the log.`);
      // What it downloaded and installed, which is otherwise invisible.
      if (data.output) setSiteAppLog({ name: `${app.name} deploy`, log: data.output });
      await loadSiteApps();
    }
  }

  async function controlSiteApp(app, action) {
    const data = await request(`/site-apps/${app.id}/control`, { method: 'POST', body: JSON.stringify({ action }) }, `${action} ${app.name}...`);
    if (data) {
      setNotice(`${app.name} is ${data.running ? 'running' : 'stopped'}.`);
      await loadSiteApps();
    }
  }

  async function openSiteAppLog(app) {
    const data = await request(`/site-apps/${app.id}/logs?lines=300`, {}, `Loading ${app.name} log...`);
    if (data) setSiteAppLog({ name: app.name, log: data.log || 'No output yet.' });
  }

  async function installDockerEngine() {
    const data = await request('/site-runtimes/docker-install', { method: 'POST' }, t('Installing Docker, this takes a few minutes...'));
    if (data) {
      setNotice(data.message || 'Docker is ready.');
      await loadSiteRuntimes();
    }
  }

  async function pruneDocker() {
    const data = await request('/site-runtimes/docker-prune', { method: 'POST' }, t('Pruning unused Docker layers...'));
    if (data) {
      setNotice(data.message || 'Pruned.');
      if (data.output) setSiteAppLog({ name: 'docker prune', log: data.output });
      await loadSiteRuntimes();
    }
  }

  async function installNodeMajor(major) {
    const data = await request('/site-runtimes/node-install', { method: 'POST', body: JSON.stringify({ major }) }, `Installing Node ${major}...`);
    if (data) {
      setNotice(data.message || `Node ${major} is ready.`);
      await loadSiteRuntimes();
    }
  }

  async function createSiteApp() {
    const body = {
      name: siteAppDraft.name,
      kind: siteAppDraft.kind,
    };
    if (String(siteAppDraft.port).trim()) body.port = Number(siteAppDraft.port);
    if (String(siteAppDraft.memory_limit_mb).trim()) body.memory_limit_mb = Number(siteAppDraft.memory_limit_mb);
    if (siteAppDraft.env.trim()) body.env = siteAppDraft.env;
    if (siteAppDraft.kind === 'node') {
      body.start_kind = siteAppDraft.start_kind;
      body.start_arg = siteAppDraft.start_arg;
      body.node_major = siteAppDraft.node_major;
    }
    if (siteAppDraft.kind === 'docker') {
      body.image = siteAppDraft.image.trim();
      body.container_port = Number(siteAppDraft.container_port) || 3000;
      body.cpu_limit = siteAppDraft.cpu_limit;
    }
    if (siteAppDraft.kind === 'compose') {
      body.compose_source = siteAppDraft.compose_source;
      body.cpu_limit = siteAppDraft.cpu_limit;
      if (siteAppDraft.web_service) body.web_service = siteAppDraft.web_service;
      if (siteAppDraft.container_port) body.container_port = Number(siteAppDraft.container_port);
    }
    const data = await request('/site-apps', { method: 'POST', body: JSON.stringify(body) }, t('Creating application...'));
    if (data) {
      setNotice(`Application ${data.name} created. Upload your files to ${data.directory} and press Deploy.`);
      setSiteAppDraft(EMPTY_SITE_APP_DRAFT);
      setComposePlan(null);
      await loadSiteApps();
    }
  }

  async function updateSiteApp(app, patch, label = 'Updating application...') {
    const data = await request(`/site-apps/${app.id}`, { method: 'PUT', body: JSON.stringify(patch) }, label);
    if (data) {
      setNotice(`Updated ${data.name}.`);
      await loadSiteApps();
    }
  }

  async function deleteSiteApp(app) {
    if (!confirm(`Delete application ${app.name}? Its files stay on disk; only the runtime is removed.`)) return;
    const data = await request(`/site-apps/${app.id}`, { method: 'DELETE' }, t('Deleting application...'));
    if (data) {
      setNotice(`Deleted ${app.name}.`);
      await loadSiteApps();
    }
  }

  async function suggestSiteAppPort() {
    const data = await request('/site-apps/suggest-port', { silent: true });
    if (data?.port) setSiteAppDraft(prev => ({ ...prev, port: String(data.port) }));
  }

  async function viewFullNginxConfig() {
    if (!nginxCustomEditing) return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-config`, {}, t('Loading full Nginx config...'));
    if (data !== null) {
      setNginxCustomEditing(prev => ({ ...prev, mode: 'full', customContent: prev?.content || '', content: data?.nginx_config || '' }));
    }
  }

  async function saveNginxCustom() {
    if (!nginxCustomEditing) return;
    if (nginxCustomEditing.mode === 'full') return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-custom`, {
      method: 'PUT',
      body: JSON.stringify({ nginx_custom: nginxCustomEditing.content }),
    }, t('Applying Custom Nginx and reloading...'));
    if (data) {
      setNotice(`Updated Custom Nginx for ${nginxCustomEditing.domain}`);
      setNginxCustomEditing(null);
      refreshAll();
    }
  }

  async function saveWebsiteSettings() {
    if (!nginxCustomEditing) return;
    const original = nginxCustomEditing.site || {};
    const body = {};
    const nextAppType = websiteSettingsForm.app_type || original.app_type || 'wordpress';
    const nextPhp = websiteSettingsForm.php_version || original.php_version || '8.4';
    const nextRewrite = nextAppType === 'wordpress'
      ? 'front_controller'
      : nextAppType === 'static' || isProxiedAppType(nextAppType)
        ? 'none'
        : websiteSettingsForm.nginx_rewrite_mode || 'none';

    if (isProxiedAppType(nextAppType)) {
      if (siteApps.items.length === 0) {
        setError(t('Install an application first, on the Applications page.'));
        return;
      }
      if (!websiteSettingsForm.app_id) {
        setError(t('Pick which application this website should serve.'));
        return;
      }
      if (String(websiteSettingsForm.app_id) !== String(original.app_id || '')) {
        body.app_id = Number(websiteSettingsForm.app_id);
      }
    }
    if (nextAppType !== (original.app_type || 'wordpress')) body.app_type = nextAppType;
    if (nextAppType !== 'static' && !isProxiedAppType(nextAppType) && nextPhp !== original.php_version) body.php_version = nextPhp;
    if (nextRewrite !== (original.nginx_rewrite_mode || (original.app_type === 'wordpress' ? 'front_controller' : 'none'))) {
      body.nginx_rewrite_mode = nextRewrite;
    }
    if (Object.keys(body).length === 0) return;

    const data = await request(`/websites/${nginxCustomEditing.id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }, `Saving ${nginxCustomEditing.domain} settings...`);
    if (data) {
      setNotice(`Updated settings for ${nginxCustomEditing.domain}.`);
      setWebsiteSettingsForm(websiteConfigForm(data));
      setNginxCustomEditing(prev => prev ? ({ ...prev, site: data }) : prev);
      await refreshAll();
    }
  }

  async function resetNginxDefault() {
    if (!nginxCustomEditing) return;
    if (!confirm(`Clear Custom Nginx for ${nginxCustomEditing.domain}?`)) return;
    const data = await request(`/websites/${nginxCustomEditing.id}/nginx-custom`, {
      method: 'PUT',
      body: JSON.stringify({ nginx_custom: '' }),
    }, t('Clearing Custom Nginx...'));
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
    setWordpressInstaller(null);
    setTerminalViewer(null);
    setLogViewer({ id: site.id, domain: site.domain, kind: 'access', lines: 200, path: '', content: '', exists: true });
    await loadWebsiteLog(site, 'access', 200, site.domain);
  }

  function openWebsiteTerminal(site) {
    setNginxCustomEditing(null);
    setWordpressInstaller(null);
    setLogViewer(null);
    setTerminalViewer({ id: site.id, domain: site.domain });
  }

  function openWordPressInstaller(site) {
    setNginxCustomEditing(null);
    setLogViewer(null);
    setTerminalViewer(null);
    setWordpressInstaller({
      website_id: site.id,
      domain: site.domain,
      php_version: site.php_version || phpVersion,
      title: site.domain,
      admin_user: 'admin',
      admin_email: `admin@${site.domain}`,
      admin_password: generateRandomPassword(20),
    });
  }

  async function installWordPressOnSite() {
    if (!wordpressInstaller) return;
    const title = String(wordpressInstaller.title || '').trim() || wordpressInstaller.domain;
    const adminUser = String(wordpressInstaller.admin_user || '').trim();
    const adminEmailValue = String(wordpressInstaller.admin_email || '').trim();
    const adminPasswordValue = String(wordpressInstaller.admin_password || '').trim();
    if (!adminUser || !adminEmailValue || !adminPasswordValue) {
      setError(t('Please fill all WordPress admin fields.'));
      return;
    }
    if (adminPasswordValue.length < 10) {
      setError(t('WordPress admin password must be at least 10 characters.'));
      return;
    }
    const data = await request(`/websites/${wordpressInstaller.website_id}/wordpress`, {
      method: 'POST',
      body: JSON.stringify({
        title,
        admin_user: adminUser,
        admin_email: adminEmailValue,
        admin_password: adminPasswordValue,
      }),
    }, `Installing WordPress for ${wordpressInstaller.domain}...`);
    if (data) {
      setNotice(`Installed WordPress: https://${wordpressInstaller.domain}\nAdmin: ${adminUser} | Password: ${adminPasswordValue}`);
      setWordpressInstaller(null);
      await refreshAll();
    }
  }

  async function runWordPressAction(site, action) {
    const labels = { core: 'core', plugins: 'plugins', themes: 'themes' };
    const label = labels[action] || action;
    const data = await request('/maintenance/wordpress', {
      method: 'POST',
      body: JSON.stringify({ website_id: site.id, action }),
    }, `Updating WordPress ${label}...`);
    if (data?.returncode && data.returncode !== 0) {
      setError(data.stderr || data.stdout || `WordPress ${label} update failed.`);
      return;
    }
    if (data) {
      setNotice(`Updated WordPress ${label} for ${site.domain}.`);
    }
  }

  async function updateWordPressAll(site) {
    if (!site) return;
    setLoading('Updating WordPress...');
    for (const action of ['core', 'plugins', 'themes']) {
      const data = await request('/maintenance/wordpress', {
        method: 'POST',
        body: JSON.stringify({ website_id: site.id, action }),
      });
      if (data?.returncode && data.returncode !== 0) {
        setError(data.stderr || data.stdout || `WordPress ${action} update failed.`);
        setLoading('');
        return;
      }
    }
    setLoading('');
    setNotice(`Updated WordPress core, plugins, and themes for ${site.domain}.`);
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
    const data = await request(`/maintenance/wordpress/${id}/fix-permissions`, { method: 'POST' }, t('Fixing permissions...'));
    if (data?.message) setNotice(data.message);
  }

  async function fixNginxSecurity(id) {
    const data = await request(`/websites/${id}/fix-nginx-security`, { method: 'POST' }, t('Rewriting Nginx security template...'));
    if (data?.message) setNotice(data.message);
  }

  async function changeDbPassword(id) {
    const newPass = prompt('Enter a new database password, minimum 12 characters:');
    if (!newPass) return;
    await request(`/databases/${id}/password`, { method: 'POST', body: JSON.stringify({ password: newPass }) }, t('Changing database password...'));
  }

  async function deleteDatabase(id, dbName) {
    if (!confirm(`Delete database "${dbName}"? This action cannot be undone.`)) return;
    const data = await request(`/databases/${id}`, { method: 'DELETE' }, t('Deleting database...'));
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
    if (!dbName) { setError(t('Please enter a database name.')); return; }
    if (!validDbName.test(dbName)) { setError(t('Database name can only contain letters, numbers and underscores (no spaces or special characters).')); return; }
    if (dbUser && !validDbName.test(dbUser)) { setError(t('Database user can only contain letters, numbers and underscores (no spaces or special characters).')); return; }
    if (dbPass && dbPass.length < 12) { setError(t('Password must be at least 12 characters.')); return; }
    if (dbPass && /[^\x20-\x7E]/.test(dbPass)) { setError(t('Password contains invalid characters. Use only ASCII characters.')); return; }
    const body = {
      db_name: dbName,
      db_user: dbUser || null,
      db_password: dbPass || null,
    };
    const data = await request('/databases', { method: 'POST', body: JSON.stringify(body) }, t('Creating database...'));
    if (data) {
      setCreatedDbInfo({ db_name: data.db_name, db_user: data.db_user, db_password: data.db_password });
      setNewDatabase({ db_name: '', db_user: '', db_password: '' });
      await refreshAll();
    }
  }

  async function addCron() {
    const data = await request('/maintenance/cron', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), schedule: cronSchedule, command: cronCommand }) }, t('Adding cron job...'));
    if (data) {
      if (data.cron_user) setCronUser(data.cron_user);
      setNotice(`Cron job added${data.cron_user ? ` as ${data.cron_user}` : ''}.`);
      await listCron();
    }
  }

  async function listCron() {
    if (!selectedWebsiteId) return;
    const data = await request(`/maintenance/cron/${selectedWebsiteId}`, {}, t('Loading cron jobs...'));
    if (data?.items) setCronItems(data.items);
    if (data?.cron_user) setCronUser(data.cron_user);
    if (data?.php_binary) setCronPhpInfo({ php_binary: data.php_binary, php_version: data.php_version || '' });
  }

  async function loadSftpAccounts() {
    if (!selectedWebsiteId) { setSftpAccounts([]); return; }
    const data = await request(`/sftp-accounts?website_id=${Number(selectedWebsiteId)}`, {}, t('Loading SFTP accounts...'));
    if (Array.isArray(data)) setSftpAccounts(data);
    const limits = await request('/sftp-accounts/limits', {}, null);
    if (limits) setSftpLimits(limits);
  }

  async function changeOwnSftpPassword() {
    const typed = prompt(
      'New SFTP password for your own account (leave empty to generate a strong one):',
      ''
    );
    if (typed === null) return;
    const data = await request(`/users/${currentUser.id}/sftp-password`, {
      method: 'POST',
      body: JSON.stringify({ password: typed ? typed : null }),
    }, t('Setting SFTP password...'));
    if (data) {
      if (data.password) setOwnSftpPassword(data.password);
      // The session carries sftp_password_set_at, so refresh it to clear the
      // "same as your panel password" warning.
      await loadCurrentUser();
      await loadSftpAccounts();
    }
  }

  async function createSftpAccount() {
    if (!selectedWebsiteId || !newSftpAccount.label.trim()) return;
    const body = {
      website_id: Number(selectedWebsiteId),
      label: newSftpAccount.label.trim(),
      password: newSftpAccount.password ? newSftpAccount.password : null,
    };
    const data = await request('/sftp-accounts', { method: 'POST', body: JSON.stringify(body) }, t('Creating SFTP account...'));
    if (data?.id) {
      setCreatedSftpInfo(data);
      setNewSftpAccount({ label: '', password: '' });
      await loadSftpAccounts();
    }
  }

  async function resetSftpPassword(account) {
    const typed = prompt(`New password for ${account.username} (leave empty to generate one):`, '');
    if (typed === null) return;
    const data = await request(`/sftp-accounts/${account.id}/password`, {
      method: 'POST',
      body: JSON.stringify({ password: typed ? typed : null }),
    }, t('Updating SFTP password...'));
    if (data) {
      if (data.password) setCreatedSftpInfo({ ...account, password: data.password });
      await loadSftpAccounts();
    }
  }

  async function deleteSftpAccount(account) {
    if (!confirm(`Delete SFTP account ${account.username}? The login stops working immediately. Site files are not touched.`)) return;
    await request(`/sftp-accounts/${account.id}`, { method: 'DELETE' }, t('Removing SFTP account...'));
    if (createdSftpInfo?.id === account.id) setCreatedSftpInfo(null);
    await loadSftpAccounts();
  }

  async function deleteCron(index) {
    if (!confirm(`Delete cron #${index}?`)) return;
    index = Number(index);
    if (Number.isNaN(index)) return;
    const data = await request('/maintenance/cron', { method: 'DELETE', body: JSON.stringify({ website_id: Number(selectedWebsiteId), index }) }, t('Deleting cron job...'));
    if (data) {
      if (data.cron_user) setCronUser(data.cron_user);
      setNotice(t('Cron job deleted.'));
      await listCron();
    }
  }

  async function listFiles(path = fileListPath) {
    if (!hasFileTarget()) return;
    const data = await request(`${fileTargetBase()}?path=${encodeURIComponent(path)}`, {}, t('Loading file list...'));
    if (data?.items) { setFiles(data.items); setFileListPath(path); setFileUploadDir(path || ''); setSelectedFilePaths([]); }
  }

  async function readFile(pathOverride = filePath) {
    const targetPath = pathOverride || filePath;
    if (!hasFileTarget() || !targetPath) return;
    if (pathOverride) setFilePath(pathOverride);
    const data = await request(`${fileTargetBase()}/read?path=${encodeURIComponent(targetPath)}`, {}, t('Reading file...'));
    if (data?.content !== undefined) {
      setFileContent(data.content);
      setEditorCursor({ line: 1, column: 1 });
    }
  }

  async function writeFile() {
    const data = await request('/maintenance/files/write', { method: 'POST', body: JSON.stringify({ ...fileTargetBody(), path: filePath, content: fileContent }) }, t('Saving file...'));
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function downloadFile(path) {
    if (!hasFileTarget() || !path) return;
    try {
      setError(''); setLoading('Downloading file...');
      const res = await fetch(`${API}${fileTargetBase()}/download?path=${encodeURIComponent(path)}`, { credentials: 'include' });
      if (!res.ok) { const data = await res.json().catch(() => ({})); if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Download failed.')); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = path.split('/').pop() || 'download';
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
    } catch (err) { setError(t('File download failed.')); }
    finally { setLoading(''); }
  }

  function fileEditorUrl(path) {
    const url = new URL(window.location.href);
    url.pathname = routeForPage('files');
    url.search = '';
    url.hash = '';
    url.searchParams.set('view', 'editor');
    if (fileAppId) url.searchParams.set('app_id', String(fileAppId));
    else url.searchParams.set('website_id', String(selectedWebsiteId));
    url.searchParams.set('path', path);
    return url.toString();
  }

  function openFileEditorTab(path) {
    if (!hasFileTarget() || !path) return;
    window.open(fileEditorUrl(path), '_blank', 'noopener,noreferrer');
  }

  async function makeFileDirectory() {
    if (!hasFileTarget()) return;
    const name = prompt('Folder name:');
    if (!name) return;
    const data = await request('/maintenance/files/mkdir', { method: 'POST', body: JSON.stringify({ ...fileTargetBody(), path: fileListPath || '', name }) }, t('Creating folder...'));
    if (data) await listFiles(fileListPath);
  }

  async function makeFile() {
    if (!hasFileTarget()) return;
    const name = prompt('File name:', 'new-file.txt');
    if (!name) return;
    const data = await request('/maintenance/files/create', { method: 'POST', body: JSON.stringify({ ...fileTargetBody(), path: fileListPath || '', name }) }, t('Creating file...'));
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
    const data = await request('/maintenance/files/rename', { method: 'POST', body: JSON.stringify({ ...fileTargetBody(), path: item.path, new_name: newName }) }, t('Renaming...'));
    if (data) await listFiles(fileListPath);
  }

  function openChmodDialog(items) {
    const targets = (Array.isArray(items) ? items : [items]).filter(Boolean);
    if (targets.length === 0) return;
    setChmodTarget(targets);
    if (targets.length === 1 && normalizeOctalMode(targets[0].mode)) {
      setChmodMode(normalizeOctalMode(targets[0].mode));
      return;
    }
    // With a mixed selection, keep the special bits only when every target
    // already agrees on them, so a bulk chmod never silently drops setgid.
    const specials = targets.map(item => octalToPermissionBits(item.mode).special);
    const special = specials.every(value => value === specials[0]) ? specials[0] : 0;
    const base = targets.every(item => item.is_dir)
      ? { owner: 7, group: 5, other: 5 }
      : { special: 0, owner: 6, group: 4, other: 4 };
    setChmodMode(permissionBitsToOctal({ special, ...base }));
  }

  async function applyChmod() {
    const targets = chmodTarget || [];
    const mode = chmodMode.trim();
    if (targets.length === 0) return;
    if (!/^[0-7]{3,4}$/.test(mode)) { setError(t('Mode must be octal, for example 644 or 755.')); return; }
    for (const item of targets) {
      const data = await request('/maintenance/files/chmod', {
        method: 'POST',
        body: JSON.stringify({ ...fileTargetBody(), path: item.path, mode }),
      }, `Setting permissions on ${item.name}...`);
      // request() already surfaced the reason; stop so the dialog keeps the mode.
      if (!data) return;
    }
    setChmodTarget(null);
    setNotice(t('Permissions set to {mode} on {n} item(s).', { mode, n: targets.length }));
    await listFiles(fileListPath);
  }

  async function deleteSelectedFiles() {
    if (selectedFilePaths.length === 0) return;
    if (!confirm(t('Delete {n} selected item(s)?', { n: selectedFilePaths.length }))) return;
    const data = await request('/maintenance/files/delete', { method: 'POST', body: JSON.stringify({ ...fileTargetBody(), paths: selectedFilePaths }) }, t('Deleting selected files...'));
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function transferFileItems(action, paths) {
    if (!hasFileTarget() || !paths?.length) return;
    const verb = action === 'copy' ? 'Copy' : 'Move';
    const destination = prompt(`${verb} to folder:`, fileListPath || 'public_html');
    if (destination === null) return;
    const targetPath = destination.trim() || fileListPath || 'public_html';
    const data = await request(`/maintenance/files/${action}`, {
      method: 'POST',
      body: JSON.stringify({ ...fileTargetBody(), paths, destination_path: targetPath }),
    }, `${verb}ing files...`);
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function copySelectedFiles() {
    await transferFileItems('copy', selectedFilePaths);
  }

  async function moveSelectedFiles() {
    await transferFileItems('move', selectedFilePaths);
  }

  async function archiveSelectedFiles() {
    if (selectedFilePaths.length === 0) return;
    const ext = archiveFormat === 'tar.gz' ? 'tar.gz' : 'zip';
    const outputName = prompt('Archive file name:', `archive-${Date.now()}.${ext}`);
    if (!outputName) return;
    const data = await request('/maintenance/files/archive', {
      method: 'POST',
      body: JSON.stringify({ ...fileTargetBody(), base_path: fileListPath || '', paths: selectedFilePaths, output_name: outputName, format: archiveFormat }),
    }, t('Creating archive...'));
    if (data) { await listFiles(fileListPath); await loadCurrentUser(); }
  }

  async function extractArchiveFile(path) {
    if (!hasFileTarget() || !path) return;
    const destination = prompt('Extract to folder:', fileListPath || '.');
    if (destination === null) return;
    const targetPath = destination.trim() || fileListPath || '.';
    const data = await request('/maintenance/files/extract', {
      method: 'POST',
      body: JSON.stringify({ ...fileTargetBody(), archive_path: path, destination_path: targetPath }),
    }, t('Starting extraction...'));
    if (data?.job_id) upsertFileJob(data);
    else if (data) { await listFiles(targetPath === '.' ? '' : targetPath); await loadCurrentUser(); }
  }

  function upsertFileJob(job) {
    if (!job?.job_id) return;
    setFileJobs(prev => [job, ...prev.filter(item => item.job_id !== job.job_id)].slice(0, 6));
  }

  function dismissFileJob(jobId) {
    setFileJobs(prev => prev.filter(item => item.job_id !== jobId));
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

  async function loadFileJobs() {
    const data = await request('/maintenance/files/jobs');
    if (data?.jobs) setFileJobs(data.jobs.filter(job => job.status !== 'done').slice(0, 6));
  }

  useEffect(() => {
    const activeJobs = fileJobs.filter(job => ['queued', 'running'].includes(job.status));
    if (activeJobs.length === 0) return undefined;

    const poll = async () => {
      for (const job of activeJobs) {
        const data = await loadFileJob(job.job_id);
        if (!data) continue;
        if (data.status === 'done') {
          // Drop the card rather than parking it on "completed" forever; the
          // notice and the refreshed listing are the confirmation.
          dismissFileJob(job.job_id);
          setNotice(data.message || 'Extraction completed');
          await listFiles(data.destination_path || fileListPath);
          await loadCurrentUser();
          continue;
        }
        upsertFileJob(data);
        if (data.status === 'error') {
          setError(formatApiError(data.error, 'Extraction failed'));
        }
      }
    };

    const timer = window.setInterval(poll, 3000);
    return () => window.clearInterval(timer);
  }, [fileJobs]);

  useEffect(() => {
    if (page === 'files' && hasFileTarget()) loadFileJobs();
  }, [page, selectedWebsiteId, fileAppId]);

  async function openWebsiteFileManager(site) {
    setNginxCustomEditing(null);
    setWordpressInstaller(null);
    setLogViewer(null);
    setTerminalViewer(null);
    setFileAppId('');
    setSelectedWebsiteId(String(site.id));
    navigateToPage('files');
    setFileListPath('public_html');
    setFileUploadDir('public_html');
    setFiles([]);
    setSelectedFilePaths([]);
  }

  function openAppFileManager(app) {
    setNginxCustomEditing(null);
    setLogViewer(null);
    setTerminalViewer(null);
    setFileAppId(String(app.id));
    // An app root has no public_html; the listing effect picks it up from here.
    setFileListPath('');
    setFileUploadDir('');
    setFiles([]);
    setSelectedFilePaths([]);
    navigateToPage('files');
  }

  async function uploadSiteFile(file) {
    if (!file) return;
    if (!hasFileTarget()) { setError(t('Please select a website or application first.')); return; }
    const uploadDir = fileUploadDir.trim();
    const form = new FormData();
    form.append('file', file);
    try {
      setError('');
      setLoading('Uploading file...');
      const csrfToken = readCookie('bpanel_csrf');
      const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
      const res = await fetch(`${API}${fileTargetBase()}/upload?path=${encodeURIComponent(uploadDir)}`, {
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
    } catch (err) { setError(t('File upload failed.')); }
    finally { setLoading(''); }
  }

  async function createBackup() {
    const data = await request('/maintenance/backup', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId) }) }, t('Queueing backup...'));
    if (data?.job_id) { setNotice(t('Backup queued. It will keep running on the server.')); await loadBackupJobs(); }
    else if (data?.backup_file) { setNotice(`Created backup: ${data.backup_file}`); await listBackups(); }
  }

  async function listBackups() {
    const data = await request(`/maintenance/backups/${selectedWebsiteId}`);
    if (data?.items) setBackups(data.items);
  }

  async function loadBackupJobs() {
    const data = await request('/maintenance/backup-jobs');
    if (data?.jobs) {
      const visibleJobs = data.jobs.filter(job => job.status !== 'done');
      const hasActive = data.jobs.some(job => ['queued', 'running'].includes(job.status));
      setBackupJobs(prev => {
        const hadActive = prev.some(job => ['queued', 'running'].includes(job.status));
        if (hadActive && !hasActive) {
          setTimeout(() => {
            if (selectedWebsiteId) listBackups();
            if (selectedBackupUserId) listUserBackups(selectedBackupUserId);
          }, 0);
        }
        return visibleJobs;
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
    const data = await request('/maintenance/user-backup', { method: 'POST', body: JSON.stringify(body) }, t('Queueing full user backup...'));
    if (data?.job_id) { setNotice(t('Full user backup queued. It will keep running on the server.')); await loadBackupJobs(); }
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
      name_suffix: newBackupSchedule.name_suffix || 'full_date',
      retention: Number(newBackupSchedule.retention || 7),
      is_active: true,
    };
    const data = await request('/maintenance/backup-schedules', { method: 'POST', body: JSON.stringify(body) }, t('Saving backup schedule...'));
    if (data) {
      setNotice(t('Backup schedule saved.'));
      await loadBackupSchedules();
    }
  }

  // Component level on purpose: renderBackups draws with these and
  // runBackupScheduleNow names the schedule in its confirmation with them.
  const userNameById = id => users.find(user => String(user.id) === String(id))?.username || `User #${id}`;
  const scheduleUserLabel = item => {
    if (item.all_users) return 'All users';
    const ids = (item.user_ids && item.user_ids.length > 0) ? item.user_ids : (item.user_id ? [item.user_id] : []);
    return ids.length ? ids.map(userNameById).join(', ') : 'No users';
  };

  async function runBackupScheduleNow(item) {
    const who = scheduleUserLabel(item);
    if (!confirm(`Run this schedule now?\n\n${who} - ${item.schedule}\n\nThis is the real thing: the same accounts, the same destination and the same stored name. Only the timing is skipped.`)) return;
    const data = await request(`/maintenance/backup-schedules/${item.id}/run`, { method: 'POST' }, t('Starting...'));
    if (data) {
      setNotice(data.detail || 'Running now.');
      await loadBackupSchedules();
      pollBackupSchedule(item.id);
    }
  }

  function pollBackupSchedule(scheduleId, attempts = 60) {
    // A schedule covering every account takes minutes, and the work runs in a
    // thread the request already let go of. Without this the row sits on
    // "running" until the operator reloads the page and guesses.
    if (attempts <= 0) return;
    window.setTimeout(async () => {
      const rows = await request('/maintenance/backup-schedules', { silent: true });
      if (!rows) return;
      setBackupSchedules(rows);
      const row = rows.find(entry => entry.id === scheduleId);
      if (!row) return;
      if (row.last_status === 'running') return pollBackupSchedule(scheduleId, attempts - 1);
      if (row.last_status === 'error') setError(`Schedule failed - ${row.last_message || 'no detail'}`);
      else setNotice(`Schedule finished - ${row.last_message || 'ok'}`);
    }, 5000);
  }

  async function deleteBackupSchedule(id) {
    if (!confirm(t('Delete this backup schedule?'))) return;
    const data = await request(`/maintenance/backup-schedules/${id}`, { method: 'DELETE' }, t('Deleting backup schedule...'));
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
    const isS3 = newSftpTarget.kind === 's3';
    const body = {
      ...newSftpTarget,
      port: Number(newSftpTarget.port || 22),
      password: newSftpTarget.password || null,
      private_key: newSftpTarget.private_key || null,
      secret_key: newSftpTarget.secret_key || null,
      endpoint: newSftpTarget.endpoint || null,
      region: newSftpTarget.region || null,
      bucket: newSftpTarget.bucket || null,
      access_key: newSftpTarget.access_key || null,
      prefix: newSftpTarget.prefix || null,
    };
    // An S3 target is checked against the bucket before it is saved, so this
    // can take a moment and can come back refused. That is the point.
    const data = await request('/maintenance/sftp-targets', { method: 'POST', body: JSON.stringify(body) },
      isS3 ? 'Checking the bucket...' : 'Saving SFTP target...');
    if (data) {
      setNotice(`Saved ${isS3 ? 'S3' : 'SFTP'} target ${data.name}`);
      setNewSftpTarget({ name: '', kind: newSftpTarget.kind, host: '', port: 22, username: '', password: '', private_key: '', remote_path: '/backups/bpanel', endpoint: '', region: '', bucket: '', access_key: '', secret_key: '', prefix: '', secure: true });
      await loadSftpTargets();
    }
  }

  async function loadRestoreCatalogue() {
    const data = await request('/maintenance/restore-catalogue', {}, t('Looking for backups...'));
    if (data) {
      setRestoreCatalogue({ items: data.items || [], errors: data.errors || [], loaded: true });
      setRestorePicks([]);
    }
  }

  function toggleRestorePick(item) {
    const id = `${item.source}:${item.target_id || 0}:${item.key}`;
    setRestorePicks(prev => prev.includes(id) ? prev.filter(entry => entry !== id) : [...prev, id]);
  }

  async function restorePicked() {
    const chosen = (restoreCatalogue.items || []).filter(item =>
      restorePicks.includes(`${item.source}:${item.target_id || 0}:${item.key}`));
    if (chosen.length === 0) return;
    const names = chosen.map(item => item.username || item.name).join(', ');
    if (!confirm(`Restore ${chosen.length} backup(s)?

${names}

Each account is overwritten with what is in its archive.`)) return;
    const data = await request('/maintenance/restore-bulk', {
      method: 'POST',
      body: JSON.stringify({ items: chosen.map(item => ({ source: item.source, name: item.name, key: item.key, target_id: item.target_id })) }),
    }, `Restoring ${chosen.length} backup(s)...`);
    if (data) {
      const failed = (data.results || []).filter(row => row.status === 'failed');
      if (failed.length === 0) setNotice(`Restored ${data.restored} of ${data.total}.`);
      else setError(`Restored ${data.restored} of ${data.total}. Failed: ` +
        failed.map(row => `${row.name} (${row.detail})`).join('; '));
      setRestorePicks([]);
      await loadRestoreCatalogue();
    }
  }

  async function deleteSftpTarget(id) {
    if (!confirm(t('Delete this SFTP target?'))) return;
    const data = await request(`/maintenance/sftp-targets/${id}`, { method: 'DELETE' }, t('Deleting SFTP target...'));
    if (data) await loadSftpTargets();
  }

  async function createSftpBackup() {
    if (!selectedWebsiteId || !selectedSftpTargetId) return;
    const data = await request('/maintenance/backup-sftp', {
      method: 'POST',
      body: JSON.stringify({ website_id: Number(selectedWebsiteId), target_id: Number(selectedSftpTargetId) }),
    }, t('Queueing SFTP backup...'));
    if (data?.job_id) {
      setNotice(t('SFTP backup queued. It will keep running on the server.'));
      await loadBackupJobs();
    } else if (data?.remote_file) {
      setNotice(`SFTP backup uploaded: ${data.remote_file}`);
      await listBackups();
    }
  }

  async function restoreBackup(file) {
    if (!confirm(`Restore this backup to the current website?\n${file}`)) return;
    await request('/maintenance/restore', { method: 'POST', body: JSON.stringify({ website_id: Number(selectedWebsiteId), backup_file: file }) }, t('Restoring backup...'));
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
      setNotice(t('Backup downloaded.'));
    } catch (err) { setError(t('Backup download failed.')); }
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
      setNotice(t('Full user backup downloaded.'));
    } catch (err) { setError(t('Full user backup download failed.')); }
    finally { setLoading(''); }
  }

  async function restoreUserBackup(file) {
    if (!confirm(`Restore this full user backup? Missing panel user and websites will be created.\n${file}`)) return;
    const data = await request('/maintenance/user-restore', { method: 'POST', body: JSON.stringify({ backup_file: file }) }, t('Restoring full user backup...'));
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
    const data = await request(`/maintenance/user-backups?backup_file=${encodeURIComponent(file)}`, { method: 'DELETE' }, t('Deleting full user backup...'));
    if (data) {
      await listUserBackups();
      await loadRestoreBackups();
    }
  }

  async function deleteRestoreBackup(file) {
    if (!confirm(`Delete this restore backup?\n${file}`)) return;
    const data = await request(`/maintenance/user-restore-backups?backup_file=${encodeURIComponent(file)}`, { method: 'DELETE' }, t('Deleting restore backup...'));
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
    } catch (err) { setError(t('Full user backup upload failed.')); }
    finally { setLoading(''); }
  }

  // --- DirectAdmin Import ---
  async function listDaBackups() {
    const data = await request('/maintenance/da-import/backups');
    if (data) setDaBackups(Array.isArray(data) ? data : []);
  }

  async function uploadDaBackup(file) {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
      setError(''); setLoading('Uploading DA backup...');
      const csrfToken = readCookie('bpanel_csrf');
      const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
      const res = await fetch(`${API}/maintenance/da-import/upload`, {
        method: 'POST', credentials: 'include', headers, body: form,
      });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text || `HTTP ${res.status}` }; }
      if (!res.ok) { if (handleAuthExpired(res.status, data.detail)) return; setError(formatApiError(data.detail, 'Upload failed.')); return; }
      setNotice(`Uploaded: ${data.filename}`);
      await listDaBackups();
    } catch (err) { setError(t('DA backup upload failed.')); }
    finally { setLoading(''); }
  }

  async function scanDaBackup(archivePath) {
    setDaScanResult(null);
    const data = await request('/maintenance/da-import/scan', { method: 'POST', body: JSON.stringify({ archive_path: archivePath }) }, t('Scanning DA backup...'));
    if (data) setDaScanResult(data);
  }

  async function importDaBackup(archivePath, force = daReplaceExisting) {
    const message = t(force
      ? 'Import and REPLACE? Any existing panel user, website, files and databases with the same names are deleted first.'
      : 'Import this DirectAdmin backup? This will create users, websites, databases, and nginx configs.');
    if (!confirm(message)) return;
    setDaImportJob(null);
    const data = await request('/maintenance/da-import/import', { method: 'POST', body: JSON.stringify({ archive_path: archivePath, force }) }, t('Starting DA import...'));
    if (data?.job_id) {
      setNotice(t('DA import started. Polling for result...'));
      setDaImportJob(data);
      pollDaImportJob(data.job_id);
    }
  }

  async function pollDaImportJob(jobId) {
    let attempts = 0;
    const maxAttempts = 360;
    while (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 5000));
      const data = await request(`/maintenance/da-import/jobs/${jobId}`, { silent: true });
      if (!data) { attempts++; continue; }
      setDaImportJob(data);
      if (data.status === 'completed') { setNotice(t('DA import completed successfully!')); await listDaBackups(); return; }
      if (data.status === 'failed') { setError(`DA import failed: ${data.error || 'Unknown error'}`); return; }
      attempts++;
    }
  }

  async function deleteDaBackup(archivePath) {
    if (!confirm(t('Delete this DA backup file?'))) return;
    const data = await request('/maintenance/da-import/backups', { method: 'DELETE', body: JSON.stringify({ archive_path: archivePath }) }, t('Deleting DA backup...'));
    if (data) { setNotice(`Deleted: ${data.deleted}`); setDaScanResult(null); await listDaBackups(); }
  }

  function toggleDaBackupSelect(path) {
    setSelectedDaBackups(prev => prev.includes(path) ? prev.filter(p => p !== path) : [...prev, path]);
  }

  function toggleSelectAllDaBackups() {
    setSelectedDaBackups(prev => prev.length === daBackups.length ? [] : daBackups.map(f => f.path));
  }

  async function bulkImportDaBackups(force = daReplaceExisting) {
    if (selectedDaBackups.length === 0) return;
    const message = force
      ? `Restore and REPLACE ${selectedDaBackups.length} backup(s)? Existing users, websites, files and databases with the same names are deleted first.`
      : `Restore ${selectedDaBackups.length} backup(s)? This will create users, websites, databases, and nginx configs for each.`;
    if (!confirm(message)) return;
    setDaBulkImportJob(null);
    setDaImportJob(null);
    setDaScanResult(null);
    const data = await request('/maintenance/da-import/bulk-import', { method: 'POST', body: JSON.stringify({ archive_paths: selectedDaBackups, force }) }, t('Starting bulk restore...'));
    if (data?.job_id) {
      setNotice(`Bulk restore started: ${data.total} backup(s). Processing sequentially...`);
      setSelectedDaBackups([]);
      pollDaBulkImportJob(data.job_id);
    }
  }

  async function pollDaBulkImportJob(jobId) {
    let attempts = 0;
    const maxAttempts = 720;
    while (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 5000));
      const data = await request(`/maintenance/da-import/bulk-jobs/${jobId}`, { silent: true });
      if (!data) { attempts++; continue; }
      setDaBulkImportJob(data);
      if (data.status === 'completed') {
        const ok = (data.results || []).filter(r => r.status === 'completed').length;
        const fail = (data.results || []).filter(r => r.status === 'failed').length;
        setNotice(`Bulk restore done: ${ok} succeeded, ${fail} failed.`);
        await listDaBackups();
        return;
      }
      attempts++;
    }
  }

  async function bulkDeleteDaBackups() {
    if (selectedDaBackups.length === 0) return;
    if (!confirm(`Delete ${selectedDaBackups.length} selected backup file(s)?`)) return;
    for (const path of selectedDaBackups) {
      await request('/maintenance/da-import/backups', { method: 'DELETE', body: JSON.stringify({ archive_path: path }) }, t('Deleting...'));
    }
    setNotice(`Deleted ${selectedDaBackups.length} backup(s).`);
    setSelectedDaBackups([]);
    setDaScanResult(null);
    await listDaBackups();
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
    } catch (err) { setError(t('Cannot open phpMyAdmin.')); }
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
      setNotice(t('Database SQL downloaded.'));
    } catch (err) { setError(t('Database download failed.')); }
    finally { setLoading(''); }
  }

  async function deleteBackup(file) {
    if (!confirm(`Delete this backup?\n${file}`)) return;
    const data = await request(`/maintenance/backups/${selectedWebsiteId}?backup_file=${encodeURIComponent(file)}`, { method: 'DELETE' }, t('Deleting backup...'));
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
    } catch (err) { setError(t('Upload backup failed.')); }
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

  async function loadPhpTune(version) {
    const data = await request(`/maintenance/php-tune?php_version=${encodeURIComponent(version)}`, { silent: true });
    setPhpTune(data || null);
    setPhpTuneApplied(false);
  }

  async function toggleOpcache() {
    const version = phpTune?.php_version || phpConfig.php_version;
    const next = !phpTune?.opcache_enabled;
    const data = await request('/maintenance/php-opcache', {
      method: 'POST',
      body: JSON.stringify({ php_version: version, enabled: next }),
    }, next ? `Enabling OPcache for PHP ${version}...` : `Disabling OPcache for PHP ${version}...`);
    if (data) {
      setNotice(data.message || 'OPcache setting changed.');
      await loadPhpTune(version);
    }
  }

  async function applyPhpTune() {
    const version = phpTune?.php_version || phpConfig.php_version;
    const data = await request('/maintenance/php-tune', {
      method: 'POST',
      body: JSON.stringify({ php_version: version }),
    }, t('Tuning PHP for this machine...'));
    if (data) {
      if (data.plan) setPhpTune(data.plan);
      setPhpTuneApplied(true);
      await loadPhpConfig(version);
    }
  }

  async function loadPhpConfig(version = phpConfig.php_version) {
    const data = await request(`/maintenance/php-config?php_version=${encodeURIComponent(version)}`, {}, t('Loading PHP config...'));
    if (data) setPhpConfig(prev => ({ ...prev, ...data, php_version: version }));
  }

  async function updatePhpConfig() {
    const data = await request('/maintenance/php-config', {
      method: 'POST',
      body: JSON.stringify({ ...phpConfig, max_execution_time: Number(phpConfig.max_execution_time), max_input_time: Number(phpConfig.max_input_time), max_input_vars: Number(phpConfig.max_input_vars) }),
    }, t('Updating PHP config...'));
    if (data?.target) { setNotice(`Updated PHP config: ${data.target}`); await loadPhpConfig(phpConfig.php_version); }
  }

  async function restorePhpDefaults() {
    if (!confirm(`Restore default PHP ${phpConfig.php_version} values?`)) return;
    const data = await request('/maintenance/php-config/defaults', {
      method: 'POST',
      body: JSON.stringify({ php_version: phpConfig.php_version }),
    }, t('Restoring PHP defaults...'));
    if (data?.values) {
      setPhpConfig(prev => ({ ...prev, ...data.values }));
      setNotice(`Restored PHP ${phpConfig.php_version} defaults.`);
    }
  }

  async function loadPhpVersions() {
    const data = await request('/maintenance/php-versions', {}, t('Loading PHP versions...'));
    if (data) setPhpVersions({
      installed: sortPhpVersions(data.installed || []),
      supported: sortPhpVersions(data.supported || []),
    });
  }

  async function loadPhpExtensions() {
    const data = await request('/maintenance/php-extensions', { silent: true });
    if (data) setPhpExtensions({ versions: data.versions || [], extensions: data.extensions || [] });
  }

  // One version at a time, so "every version" is several short apt runs and
  // the table fills in as each one lands.
  async function installPhpExtension(extension, versions) {
    for (const version of versions) {
      const data = await request('/maintenance/php-extensions', {
        method: 'POST',
        body: JSON.stringify({ php_version: version, extension }),
      }, t('Installing php{version}-{extension}...', { version, extension }));
      if (!data) return;
      setPhpExtensions({ versions: data.versions || [], extensions: data.extensions || [] });
    }
    setNotice(t('{extension} installed for PHP {versions}.', { extension, versions: versions.join(', ') }));
  }

  async function installPhpVersion(version) {
    if (!confirm(`Install PHP ${version}? This will install php${version}-fpm via apt.`)) return;
    const data = await request(`/maintenance/php-versions/${version}/install`, { method: 'POST' }, `Installing PHP ${version}...`);
    if (data) { setNotice(`PHP ${version} installed successfully.`); await loadPhpVersions(); await loadServiceNames(); }
  }

  async function loadFirewall() {
    const data = await request('/firewall/status', {}, t('Loading firewall...'));
    if (data) setFirewallStatus(data);
  }

  async function loadFail2ban() {
    // 409 when the addon is not installed, which is an answer, not an error.
    const data = await request('/fail2ban/status', { silent: true });
    setF2b(data || null);
  }

  async function loadBannedPage(offset = 0) {
    const data = await request(`/fail2ban/banned?limit=50&offset=${offset}`, { silent: true });
    if (data) setF2bBanned(data);
  }

  async function unbanAddress(ip) {
    const data = await request('/fail2ban/unban', { method: 'POST', body: JSON.stringify({ ip }) },
      `Unbanning ${ip}...`);
    if (data) {
      setF2bBanned({ items: data.items, total: data.total, offset: data.offset, limit: data.limit });
      setF2b(prev => (prev ? { ...prev, banned: data.total } : prev));
      setNotice(`${ip} unbanned.`);
    }
  }

  function openFwDetail(which) {
    const next = fwDetail === which ? null : which;
    setFwDetail(next);
    setFwFilter('');
    if (next === 'banned') loadBannedPage(0);
  }

  async function submitFirewallRule() {
    if (fwAction === 'port') return openFirewallPort();
    if (fwAction === 'allow') return allowFirewallIp();
    return blockFirewallIp();
  }

  async function runFirewallAction(path, options = {}, label = 'Updating firewall...') {
    const data = await request(path, options, label);
    if (data) { setNotice((data.stdout || data.stderr || 'Firewall updated.').trim()); await loadFirewall(); }
  }

  async function enableFirewall() {
    if (!confirm(t('Enable the firewall now? SSH, the panel port and 80/443/465/587 stay open automatically.'))) return;
    await runFirewallAction('/firewall/enable', { method: 'POST' }, t('Enabling firewall...'));
  }
  async function disableFirewall() {
    if (!confirm(t('Disable the firewall? Every port will be reachable again.'))) return;
    await runFirewallAction('/firewall/disable', { method: 'POST' }, t('Disabling firewall...'));
  }
  async function reloadFirewall() { await runFirewallAction('/firewall/reload', { method: 'POST' }, t('Reloading firewall...')); }
  async function openFirewallPort() { await runFirewallAction('/firewall/allow-port', { method: 'POST', body: JSON.stringify({ port: firewallPort, protocol: firewallProtocol }) }, t('Opening port...')); }
  async function allowFirewallIp() { await runFirewallAction('/firewall/allow-ip', { method: 'POST', body: JSON.stringify({ ip: firewallAllowIp, port: firewallAllowPort || null, protocol: firewallAllowProtocol }) }, t('Allowing IP...')); }
  async function blockFirewallIp() {
    if (!confirm(`Block ${firewallBlockIp || 'this IP'}?`)) return;
    await runFirewallAction('/firewall/block-ip', { method: 'POST', body: JSON.stringify({ ip: firewallBlockIp, port: firewallBlockPort || null, protocol: firewallBlockProtocol }) }, t('Blocking IP...'));
  }
  async function deleteFirewallRule(numberOverride = firewallDeleteNumber) {
    const ruleNumber = String(numberOverride || '').trim();
    if (!ruleNumber) return;
    if (!confirm(`Delete firewall rule #${ruleNumber}?`)) return;
    await runFirewallAction(`/firewall/rules/${encodeURIComponent(ruleNumber)}`, { method: 'DELETE' }, t('Deleting rule...'));
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
    const data = await request('/firewall/blocklists', {}, t('Loading IP blocklists...'));
    if (data) setFirewallBlocklists(data);
  }

  async function addFirewallBlocklistUrl() {
    const url = firewallBlocklistUrl.trim();
    if (!url) return;
    const data = await request('/firewall/blocklists', { method: 'POST', body: JSON.stringify({ url }) }, t('Adding IP blocklist URL...'));
    if (data) {
      setNotice((data.stdout || data.stderr || 'IP blocklist URL added.').trim());
      setFirewallBlocklistUrl('');
      await loadFirewallBlocklists();
    }
  }

  async function deleteFirewallBlocklistUrl(url) {
    if (!confirm(`Delete blocklist URL?\n${url}`)) return;
    const data = await request('/firewall/blocklists/delete', { method: 'POST', body: JSON.stringify({ url }) }, t('Deleting IP blocklist URL...'));
    if (data) {
      setNotice((data.stdout || data.stderr || 'IP blocklist URL removed.').trim());
      await loadFirewallBlocklists();
    }
  }

  async function updateFirewallBlocklistsNow() {
    const data = await request('/firewall/blocklists/update', { method: 'POST' }, t('Refreshing IP blocklists...'));
    if (data) {
      setNotice((data.stdout || data.stderr || 'IP blocklists refreshed.').trim());
      await loadFirewall();
      await loadFirewallBlocklists();
    }
  }

  async function loadWafRules() {
    const data = await request('/waf/rules', {}, t('Loading WAF rules...'));
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
      setSiteBotText((data.blocked_bots || []).join('\n'));
    }
  }

  async function openWafSite(websiteId) {
    await loadWebsiteWafConfig(websiteId);
    navigateToPage('waf-site');
  }

  async function saveSiteBots() {
    if (!selectedWafWebsiteId) return;
    const data = await request(`/waf/websites/${selectedWafWebsiteId}/bots`, {
      method: 'PUT',
      body: JSON.stringify({ blocked_bots: siteBotText }),
    }, t('Saving blocked bots...'));
    if (data) {
      setSiteBotText((data.blocked_bots || []).join('\n'));
      setNotice(data.message || 'Blocked bots saved.');
      await loadBotBlocks();
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

  async function loadBotBlocks() {
    const data = await request('/waf/bots', {}, t('Loading blocked bots...'));
    if (data) {
      setBotBlocks(data);
      setGlobalBots(data.global_blocked_bots || []);
    }
  }

  async function saveGlobalBots(nextList) {
    const data = await request('/waf/bots/global', {
      method: 'PUT',
      body: JSON.stringify({ blocked_bots: nextList.join('\n') }),
    }, t('Saving global bad bots...'));
    if (data) {
      setGlobalBots(data.global_blocked_bots || []);
      setNotice(data.failed?.length
        ? `${data.message} Failed: ${data.failed.map(f => `${f.domain} (${f.error})`).join('; ')}`
        : (data.message || 'Global bad bots saved.'));
      await loadBotBlocks();
    }
  }

  async function loadCrs() {
    const data = await request('/waf/crs', { silent: true });
    if (data) setCrs(data);
  }

  async function saveCrsMode(mode) {
    if (mode === 'block' && !confirm(
      t('Switch OWASP CRS to blocking?') + '\n\n'
      + t('Websites with CRS on will start refusing requests that score above the threshold. Run Detect only first and read the logs, or a request somebody depends on may be the one it stops.')
    )) return;
    const data = await request('/waf/crs', {
      method: 'PUT',
      body: JSON.stringify({ mode }),
    }, `Switching OWASP CRS to ${mode}...`);
    if (data) await loadCrs();
  }

  async function toggleSiteCrs(config) {
    const turningOn = !config.crs_enabled;
    const domain = config.domain;
    if (turningOn && !confirm(t('Turn on OWASP CRS for {domain}? It uses about {n} MB of server RAM.', { domain, n: crs?.rss_mb_per_site || 50 }))) return;
    const data = await request(`/waf/websites/${config.website_id}/crs`, {
      method: 'PUT',
      body: JSON.stringify({ enabled: turningOn }),
    }, turningOn ? t('Turning CRS on for {domain}...', { domain }) : t('Turning CRS off for {domain}...', { domain }));
    if (data) {
      setNotice(turningOn ? t('OWASP CRS is on for {domain}.', { domain }) : t('OWASP CRS is off for {domain}.', { domain }));
      await loadWebsiteWafConfig(config.website_id, false);
      if (isAdmin) await loadCrs();
    }
  }

  function addGlobalBots(text) {
    const incoming = String(text || '').split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
    if (incoming.length === 0) return;
    const seen = new Set(globalBots.map(s => s.toLowerCase()));
    const merged = [...globalBots];
    for (const name of incoming) {
      if (!seen.has(name.toLowerCase())) { seen.add(name.toLowerCase()); merged.push(name); }
    }
    setGlobalBots(merged);
  }

  async function saveWebsiteWafRules() {
    if (!selectedWafWebsiteId || !wafSiteConfig) return;
    const data = await request(`/waf/websites/${selectedWafWebsiteId}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled_rule_ids: wafSiteConfig.enabled_rule_ids || [], custom_rules: wafCustomRules }),
    }, t('Saving website WAF rules...'));
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
    }, t('Saving HTTP Flood settings...'));
    if (data) {
      setNotice(`HTTP Flood settings saved for ${data.domain}.`);
      await refreshAll();
      await loadWebsiteWafConfig(selectedWafWebsiteId, false);
    }
  }

  async function loadWafAccessLogs(filters = wafAccessLogFilters, showLoading = true) {
    const params = new URLSearchParams();
    if (filters.websiteId) params.set('website_id', filters.websiteId);
    params.set('verdict', filters.verdict || 'all');
    params.set('limit', String(filters.limit || 50));
    params.set('lines', '5000');
    if (filters.query?.trim()) params.set('q', filters.query.trim());
    const data = await request(`/waf/access-logs?${params.toString()}`, {}, showLoading ? 'Loading access logs...' : '');
    if (data) setWafAccessLogs(data);
  }

  async function applyWafAccessLogFilters() {
    await loadWafAccessLogs(wafAccessLogFilters, true);
  }

  function updateWafAccessLogFilters(patch, shouldLoad = false) {
    setWafAccessLogFilters(prev => {
      const next = { ...prev, ...patch };
      if (shouldLoad) loadWafAccessLogs(next, false);
      return next;
    });
  }

  async function clearWafAccessLogs() {
    const selected = websites.find(site => String(site.id) === String(wafAccessLogFilters.websiteId));
    const label = selected?.domain || 'all websites';
    if (!confirm(`Clear access logs for ${label}?`)) return;
    const params = new URLSearchParams();
    if (wafAccessLogFilters.websiteId) params.set('website_id', wafAccessLogFilters.websiteId);
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const data = await request(`/waf/access-logs${suffix}`, { method: 'DELETE' }, t('Clearing access logs...'));
    if (data) {
      setNotice(data.message || 'Access logs cleared.');
      await loadWafAccessLogs(wafAccessLogFilters, false);
    }
  }

  function exportWafAccessLogs() {
    const rows = wafAccessLogs.items || [];
    const header = ['verdict', 'time', 'domain', 'method', 'path', 'ip', 'country', 'country_code', 'reason', 'status', 'duration_ms', 'user_agent'];
    const csv = [
      header.join(','),
      ...rows.map(item => header.map(key => csvCell(key === 'time' ? item.timestamp : item[key])).join(',')),
    ].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const site = websites.find(item => String(item.id) === String(wafAccessLogFilters.websiteId));
    link.href = url;
    link.download = `bpanel-access-logs-${site?.domain || 'all'}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function loadUpdates(force = false) {
    const data = await request(`/updates/status${force ? '?refresh=true' : ''}`, {}, t('Loading update status...'));
    if (data) setUpdatesStatus(data);
  }

  async function toggleUpdateLog() {
    if (!showUpdateLog && !updatesStatus) await loadUpdates();
    setShowUpdateLog(prev => !prev);
  }

  async function runOsUpdate() {
    if (!confirm(t('Run apt-get update && apt-get upgrade now?'))) return;
    setOsUpdating(true);
    const data = await request('/updates/os/run', { method: 'POST' }, t('Updating OS packages...'));
    setOsUpdating(false);
    if (data) { setNotice((data.stdout || data.stderr || 'OS update completed.').trim()); if (showUpdateLog) await loadUpdates(); }
  }

  async function saveOsAutoUpdate() {
    const data = await request('/updates/os/auto', { method: 'POST', body: JSON.stringify(osAutoUpdate) }, t('Saving OS auto update...'));
    if (data) { setNotice((data.stdout || data.stderr || 'OS auto update saved.').trim()); if (showUpdateLog) await loadUpdates(); }
  }

  async function runPanelUpdate() {
    if (!confirm(t('Update BPanel from GitHub now? The API may restart and this page will reload when done.'))) return;
    setPanelUpdating(true);
    setShowUpdateLog(true);
    setPanelUpdateLog([]);
    const data = await request('/updates/panel/run', { method: 'POST' }, t('Updating BPanel...'));
    if (!data) {
      setPanelUpdating(false);
      return;
    }
    // Poll /updates/status every 2s until the update finishes, then reload.
    const pollOnce = async () => {
      const status = await request('/updates/status', {}, null);
      if (!status) return;
      setUpdatesStatus(status);
      if (Array.isArray(status.panel_update_log)) {
        setPanelUpdateLog(status.panel_update_log);
      } else if (typeof status.panel_update_log === 'string' && status.panel_update_log) {
        setPanelUpdateLog(status.panel_update_log.split('\n'));
      }
      const st = status.panel || {};
      const done = st.last_update_status === 'completed' || st.last_update_status === 'failed';
      if (done) {
        if (panelUpdateInterval.current) {
          clearInterval(panelUpdateInterval.current);
          panelUpdateInterval.current = null;
        }
        setPanelUpdating(false);
        if (st.last_update_status === 'completed' && Number(st.progress_percent) === 100) {
          setNotice(t('Panel update completed. Reloading to apply the new version...'));
          setTimeout(() => { window.location.reload(); }, 2000);
        } else if (st.last_update_status === 'failed') {
          setNotice((st.progress_message || st.last_update_message || 'Panel update failed.').trim());
        }
      }
    };
    await pollOnce();
    if (panelUpdateInterval.current) clearInterval(panelUpdateInterval.current);
    panelUpdateInterval.current = setInterval(pollOnce, 2000);
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
    setFileAppId(standaloneEditor.appId || '');
    setFilePath(standaloneEditor.path);
    readFile(standaloneEditor.path);
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
    if (isAuthenticated && page === 'dashboard') loadDashboardSummary();
  }, [isAuthenticated, page]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'dashboard' || !isAdmin) return undefined;
    loadResourceUsage();
    const timer = setInterval(loadResourceUsage, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page, isAdmin]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'services' || !isAdmin) return undefined;
    checkAllServices();
    const timer = setInterval(checkAllServices, 10000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page, isAdmin]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'websites') return undefined;
    const timer = window.setTimeout(() => {
      loadWebsiteList(websiteSearch, false);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [isAuthenticated, page, websiteSearch]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'databases') return undefined;
    const timer = window.setTimeout(() => {
      loadDatabases(dbSearch, false);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [isAuthenticated, page, dbSearch]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'security') return;
    loadPasskeyStatus();
  }, [isAuthenticated, page]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'sftp') return;
    setCreatedSftpInfo(null);
    loadSftpAccounts();
  }, [isAuthenticated, page, selectedWebsiteId]);

  useEffect(() => {
    if (!currentSite) return;
    const modeMap = { manual: 'manual', cloudflare: 'wildcard', shared: 'shared' };
    setSslMode(modeMap[currentSite.ssl_mode] || 'letsencrypt');
    setManualSslForm({ certificate: '', private_key: '', ca_bundle: '' });
    setManualSslFiles({ certificate: null, private_key: null, ca_bundle: null });
    setWildcardToken('');
    setSharedSource('');
    setCfZone({ zone: null, has_token: false });
    setSslSources([]);
  }, [currentSite?.id]);

  useEffect(() => {
    if (page === 'ssl' && selectedWebsiteId) { loadCfZone(selectedWebsiteId); loadSslSources(selectedWebsiteId); }
  }, [page, selectedWebsiteId]);

  useEffect(() => { if (selectedWebsiteId && page === 'backups') { listBackups(); loadBackupJobs(); } }, [selectedWebsiteId, page]);

  // No selectedWebsiteId guard: a DirectAdmin archive belongs to the server,
  // not to a website, and importing one is what you do on a server that has
  // no websites yet. Gated on a selection, the list never loaded on a fresh
  // machine and the page read "No DirectAdmin backups uploaded" however many
  // archives were sitting in the directory.
  useEffect(() => { if (page === 'backups' && backupTab === 'da-import') { listDaBackups(); setSelectedDaBackups([]); setDaBulkImportJob(null); } }, [backupTab, page]);
  // The catalogue reaches out to every S3 bucket, so it is fetched when the
  // tab is opened rather than on every visit to the Backups page.
  useEffect(() => { if (page === 'backups' && backupTab === 'restore' && isAdmin) loadRestoreCatalogue(); }, [backupTab, page]);

  useEffect(() => { if (selectedWebsiteId && page === 'cron') listCron(); }, [selectedWebsiteId, page]);
  // Which optional features exist decides what the nav shows, so this is asked
  // once per session rather than per page.
  useEffect(() => { if (currentUser) loadAddons(); }, [currentUser]);

  // The websites page needs the list too, for the Application picker on create.
  useEffect(() => {
    if (!currentUser || !applicationAddonInstalled) return;
    if (page === 'applications') { loadSiteApps(); loadSiteRuntimes(); }
    else if (page === 'websites' || page === 'files') loadSiteApps();
  }, [page, currentUser, applicationAddonInstalled]);

  useEffect(() => {
    if (page !== 'files' || !hasFileTarget()) return;
    // An app has no public_html; its root is the code directory itself.
    listFiles(fileAppId ? '' : 'public_html');
  }, [selectedWebsiteId, fileAppId, page]);

  useEffect(() => { if (selectedBackupUserId && page === 'backups') listUserBackups(selectedBackupUserId); }, [selectedBackupUserId, page]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'backups') return undefined;
    loadBackupJobs();
    const timer = setInterval(loadBackupJobs, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page, selectedWebsiteId, selectedBackupUserId]);

  useEffect(() => {
    if (isAuthenticated && page === 'users') { loadUsers(); loadPackages(); }
    if (isAuthenticated && page === 'php') { loadPhpConfig(); loadPhpTune(phpConfig.php_version); loadPhpExtensions(); }
    if (isAuthenticated && page === 'firewall') { loadFirewall(); loadFirewallBlocklists(); loadFail2ban(); }
    if (isAuthenticated && ['waf', 'waf-site'].includes(page)) {
      loadBotBlocks();
      // /waf/rules and /waf/crs describe the whole server and stay admin-only.
      if (isAdmin) { loadWafRules(); loadCrs(); }
    }
    if (isAuthenticated && page === 'malware' && isAdmin) {
      loadMalwareScanStatus();
      loadMalwareScanJobs();
      loadLatestMalwareScanJob();
      loadMalwareSchedule();
      if (websites.length === 0) loadWebsiteList('', false);
    }
    if (isAuthenticated && page === 'access-logs' && currentUser?.role === 'admin') {
      loadWafAccessLogs(wafAccessLogFilters, true);
    }
    if (isAuthenticated && page === 'updates' && currentUser?.role === 'admin') loadUpdates();
    if (isAuthenticated && page === 'security') {
      loadTwoFactorStatus();
      if (isAdmin) { loadMalwareScanStatus(); loadMalwareScanJobs(); loadLatestMalwareScanJob(); }
      if (!websites.length) refreshAll();
    }
    if (isAuthenticated && page === 'settings') { loadPanelSettings(); if (isAdmin) loadApiTokens(); }
    if (isAuthenticated && page === 'mcp' && mcpAddonInstalled) loadMcpTokens();
    if (isAuthenticated && page === 'backups' && currentUser?.role === 'admin') { loadUsers(); loadSftpTargets(); loadBackupSchedules(); loadRestoreBackups(); }
  }, [isAuthenticated, page, currentUser?.role]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'access-logs' || currentUser?.role !== 'admin') return undefined;
    if (!wafAccessLogFilters.refresh) return undefined;
    const timer = setInterval(() => loadWafAccessLogs(wafAccessLogFilters, false), Number(wafAccessLogFilters.refresh) * 1000);
    return () => clearInterval(timer);
  }, [isAuthenticated, page, currentUser?.role, wafAccessLogFilters]);

  useEffect(() => {
    if (!scanJob?.job_id || !['queued', 'running'].includes(scanJob.status)) return undefined;
    setScanLoading(true);
    const poll = () => loadMalwareScanJob(scanJob.job_id);
    const timer = window.setInterval(poll, 2000);
    poll();
    return () => window.clearInterval(timer);
  }, [scanJob?.job_id, scanJob?.status]);

  useEffect(() => {
    // Only on the per-site page: the overview does not need one selected, and
    // picking one there used to load a site's rules nobody had asked for.
    if (!isAuthenticated || page !== 'waf-site' || selectedWafWebsiteId || websites.length === 0) return;
    loadWebsiteWafConfig(websites[0].id, false);
  }, [isAuthenticated, page, selectedWafWebsiteId, websites.length]);

  useEffect(() => { setMobileMenuOpen(false); }, [page]);

  // The account menu closes on a click anywhere else, on Escape, and on navigation.
  useEffect(() => {
    if (!userMenuOpen) return undefined;
    const onPointer = event => { if (!userMenuRef.current?.contains(event.target)) setUserMenuOpen(false); };
    const onKey = event => { if (event.key === 'Escape') setUserMenuOpen(false); };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onPointer); document.removeEventListener('keydown', onKey); };
  }, [userMenuOpen]);

  useEffect(() => { setUserMenuOpen(false); }, [page]);

  function roleLabel(role) {
    return role === 'admin' ? 'Admin' : 'End user';
  }

  // The sidebar in three labelled groups, as OPanel has it - what a site
  // needs, what guards it, and the server itself - so nothing hides behind a
  // collapsed "Settings". Labels are English and go through t() when drawn.
  const navSections = [
    { key: 'home', items: [['dashboard', 'Dashboard', Home]] },
    { key: 'hosting', title: 'Hosting', items: [
      ['websites', 'Websites', Globe],
      ...(appsFeatureEnabled ? [['applications', 'Applications', Boxes]] : []),
      ['ssl', 'SSL', Lock],
      ['databases', 'Databases', Database],
      ['cron', 'Cron', Clock],
      ['files', 'File manager', FolderOpen],
      ['sftp', 'SFTP accounts', Upload],
      ['backups', 'Backups', Archive],
    ] },
    { key: 'security', title: 'Security', items: [
      ...(isAdmin ? [['firewall', 'Firewall', BrickWall]] : []),
      ['waf', 'WAF', ShieldAlert],
      ...(isAdmin ? [['malware', 'Malware scanner', Bug]] : []),
      ...(isAdmin ? [['access-logs', 'Access logs', ScrollText]] : []),
      ['security', 'Account security', LockKeyhole],
    ] },
    { key: 'system', title: 'System', items: [
      ...(isAdmin ? [['services', 'Services', Activity]] : []),
      ...(isAdmin ? [['php', 'PHP config', Code2]] : []),
      ...(isAdmin ? [['users', 'Panel users', Users]] : []),
      ...(isAdmin ? [['settings', 'Panel settings', SettingsIcon]] : []),
      ...(isAdmin ? [['updates', 'Updates', RefreshCw]] : []),
      ...(isAdmin ? [['addons', 'Addons', PackageOpen]] : []),
      // A customer sees this only once an administrator has turned the addon
      // on. An admin always sees it, so there is somewhere to go and read why
      // it is off.
      ...(mcpAddonInstalled || isAdmin ? [['mcp', 'AI assistants', Bot]] : []),
    ] },
  ].filter(section => section.items.length > 0);

  const navItems = navSections.flatMap(section => section.items);
  const navPage = NAV_PARENT_PAGE[page] || page;
  const activeNavItem = navItems.find(([key]) => key === navPage) || navItems[0];

  function renderNotifications() {
    const errorMessage = formatApiError(error, '').trim();
    const noticeMessage = formatApiError(notice, '').trim();
    if (!errorMessage && !noticeMessage) return null;
    return <div className="app-toast-stack" aria-label={t('Notifications')}>
      <NotificationToast type="error" message={errorMessage} onClose={() => setError('')} />
      <NotificationToast type="success" message={noticeMessage} onClose={() => setNotice('')} />
    </div>;
  }

  function websiteUrl(site) {
    const value = (site?.domain || '').trim();
    if (/^https?:\/\//i.test(value)) return value;
    return `${site?.ssl_enabled ? 'https' : 'http'}://${value}`;
  }

  // The file manager browses either a website root or an application root.
  function fileTargetBody() {
    return fileAppId ? { app_id: Number(fileAppId) } : { website_id: Number(selectedWebsiteId) };
  }

  function fileTargetBase() {
    return fileAppId ? `/maintenance/app-files/${fileAppId}` : `/maintenance/files/${selectedWebsiteId}`;
  }

  function fileTargetKey() {
    return fileAppId ? `app:${fileAppId}` : (selectedWebsiteId ? `site:${selectedWebsiteId}` : '');
  }

  function hasFileTarget() {
    return !!(fileAppId || selectedWebsiteId);
  }

  function currentFileApp() {
    return siteApps.items.find(app => String(app.id) === String(fileAppId)) || null;
  }

  function FileTargetSelect() {
    return <select
      value={fileAppId ? `app:${fileAppId}` : selectedWebsiteId}
      onChange={e => {
        const value = e.target.value;
        if (value.startsWith('app:')) setFileAppId(value.slice(4));
        else { setFileAppId(''); setSelectedWebsiteId(value); }
        setFileListPath(value.startsWith('app:') ? '' : 'public_html');
        setFiles([]);
        setSelectedFilePaths([]);
      }}
    >
      <option value="">-- Select website or application --</option>
      {websites.map(site => <option key={`site-${site.id}`} value={site.id}>{site.domain}</option>)}
      {siteApps.items.map(app => <option key={`app-${app.id}`} value={`app:${app.id}`}>{t('App:')} {app.name}</option>)}
    </select>;
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

  function isTextEditable(item) {
    if (!item || item.is_dir) return false;
    const name = (item.name || '').toLowerCase();
    const editableDotfiles = new Set(['.env', '.env.example', '.htaccess', '.user.ini', '.gitignore', '.gitattributes']);
    return editableDotfiles.has(name) || /\.(txt|md|json|css|js|jsx|ts|tsx|html|htm|xml|yml|yaml|ini|conf|log|php|env|htaccess)$/.test(name) || !name.includes('.');
  }

  function isArchiveFile(item) {
    if (!item || item.is_dir) return false;
    const name = (item.name || '').toLowerCase();
    return name.endsWith('.zip') || name.endsWith('.tar.gz') || name.endsWith('.tgz');
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
    /* Translated here rather than at each call site. Several callers pass a
     * ternary - message={searching ? 'No matches.' : 'None yet.'} - and a
     * wrapper looking for message="..." cannot see inside one. Doing it here
     * covers every caller, including the ones written tomorrow. */
    return <div className="empty-state"><Icon size={40} /><p>{t(message)}</p></div>;
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

  // dd/mm/yyyy hh:mm in the reader's clock; with seconds for a tooltip.
  // The API sends Unix seconds.
  function formatFileTime(seconds, withSeconds = false) {
    const d = new Date(Number(seconds) * 1000);
    if (!seconds || Number.isNaN(d.getTime())) return '';
    const two = n => String(n).padStart(2, '0');
    const stamp = `${two(d.getDate())}/${two(d.getMonth() + 1)}/${d.getFullYear()} ${two(d.getHours())}:${two(d.getMinutes())}`;
    return withSeconds ? `${stamp}:${two(d.getSeconds())}` : stamp;
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
    // -1 means the panel has not measured this account yet and did not hold
    // the list up to do it. Saying so beats drawing a zero that reads as fact.
    if (Number(user?.storage_used_bytes) < 0) return t('measuring...');
    const used = Number(user?.storage_used_bytes || 0);
    const limit = storageLimitBytes(user);
    if (limit === null) return formatBytes(used);
    return `${formatBytes(used)} / ${formatBytes(limit)}`;
  }

  function ResourceCard({ icon: Icon, label, value, detail, percent }) {
    const safePercent = percent == null ? null : clampPercent(percent);
    // Amber from 80%, red from 90%: a disk at 93% should not look like one at
    // 30%. Named level-* because .danger and .warn are a button and a badge.
    const level = safePercent == null ? '' : safePercent >= 90 ? ' level-critical' : safePercent >= 80 ? ' level-warn' : '';
    return <article className={`resource-card${level}`}>
      <div className="resource-head"><span className="resource-icon"><Icon size={16}/></span><span>{label}</span></div>
      <strong>{value}</strong>
      {/* A meter without a percentage keeps an empty track, so every card's
          value and detail sit on the same lines as its neighbours'. */}
      {safePercent !== null ? <div className="resource-track"><span style={{ width: `${safePercent}%` }}></span></div> : <div className="resource-track is-empty" aria-hidden="true"></div>}
      <small>{detail}</small>
    </article>;
  }

  function renderDashboard() {
    const cpu = resourceUsage?.cpu || {};
    const memory = resourceUsage?.memory || {};
    const disk = resourceUsage?.disk || {};
    const network = resourceUsage?.network || {};
    const networkTotal = (Number(network.rx_per_sec) || 0) + (Number(network.tx_per_sec) || 0);

    // How things stand, not a second copy of the sidebar: the three groups of
    // links that were here repeated it item for item. Until the summary
    // arrives, the lists already loaded stand in for it.
    const sum = dashSummary || {};
    const sites = sum.websites || { total: websites.length, suspended: 0, waf_on: websites.filter(site => site.waf_enabled).length };
    const ssl = sum.ssl || { total: websites.length, secured: websites.filter(site => site.ssl_enabled).length, unsecured: [], unsecured_count: 0 };
    const dbCount = sum.databases?.total ?? databases.length;
    // dd/mm hh:mm. Backup times are stored without a zone, in the server's
    // local time, which is what a Date then shows them as.
    const shortDate = value => {
      const d = value ? new Date(value) : null;
      if (!d || Number.isNaN(d.getTime())) return '—';
      const two = n => String(n).padStart(2, '0');
      return `${two(d.getDate())}/${two(d.getMonth() + 1)} ${two(d.getHours())}:${two(d.getMinutes())}`;
    };

    // Each card says how one thing stands, and how loudly: ok / warn / bad /
    // neutral, drawn as the colour of its left edge. A customer's plan-usage
    // card already counts websites and databases, so theirs start at SSL.
    const sslCard = { key: 'ssl', icon: Lock, label: t('SSL'), value: `${ssl.secured}/${ssl.total}`,
      detail: !ssl.total ? t('No websites yet') : ssl.unsecured_count ? t('{n} without SSL', { n: ssl.unsecured_count }) : t('All secured'),
      tone: !ssl.total ? 'neutral' : ssl.unsecured_count ? 'warn' : 'ok' };
    const cards = [];
    if (isAdmin) {
      cards.push({ key: 'websites', icon: Globe, label: t('Websites'), value: String(sites.total),
        detail: sites.suspended ? t('{n} suspended', { n: sites.suspended }) : sites.total ? t('All running') : t('No websites yet'),
        tone: sites.suspended ? 'warn' : sites.total ? 'ok' : 'neutral' });
      cards.push(sslCard);
      cards.push({ key: 'databases', icon: Database, label: t('Databases'), value: String(dbCount), detail: 'MariaDB', tone: 'neutral' });
      const backups = sum.backups;
      cards.push({ key: 'backups', icon: Archive, label: t('Backups'),
        value: backups?.last_run_at ? shortDate(backups.last_run_at) : '—',
        detail: !backups ? t('Checking...') : !backups.schedules ? t('No schedule') : backups.failed ? t('Last run failed') : t('{n} schedule(s)', { n: backups.schedules }),
        tone: !backups ? 'neutral' : !backups.schedules ? 'warn' : backups.failed ? 'bad' : 'ok' });
      const firewallOn = sum.firewall?.enabled;
      cards.push({ key: 'firewall', icon: BrickWall, label: t('Firewall'),
        value: firewallOn === true ? t('On') : firewallOn === false ? t('Off') : '—', detail: 'iptables + ipset',
        tone: firewallOn === true ? 'ok' : firewallOn === false ? 'bad' : 'neutral' });
      const engine = sum.waf?.engine;
      cards.push({ key: 'waf', icon: ShieldAlert, label: 'WAF',
        value: engine === 'on' ? t('On') : engine === 'off' ? t('Not installed') : '—', detail: t('ModSecurity engine'),
        tone: engine === 'on' ? 'ok' : engine === 'off' ? 'warn' : 'neutral' });
      const scanner = sum.malware;
      const lastScan = scanner?.last_scan;
      cards.push({ key: 'malware', icon: Bug, label: t('Malware scanner'),
        value: !scanner ? '—' : !scanner.installed ? t('Not installed') : lastScan?.infected ? t('{n} threat(s)', { n: lastScan.infected }) : lastScan ? t('Clean') : t('No scan yet'),
        detail: scanner?.running ? t('Scanning...') : lastScan ? t('Last scan {when}', { when: shortDate(lastScan.finished_at) }) : t('Last scan'),
        tone: !scanner ? 'neutral' : !scanner.installed ? 'warn' : lastScan?.infected ? 'bad' : lastScan ? 'ok' : 'neutral' });
      const services = sum.services;
      cards.push({ key: 'services', icon: Activity, label: t('Services'),
        value: services ? `${services.running}/${services.total}` : '—',
        detail: services?.stopped?.length ? t('Stopped: {names}', { names: services.stopped.join(', ') }) : services ? t('All running') : t('Checking...'),
        tone: !services ? 'neutral' : services.stopped?.length ? 'bad' : 'ok' });
    } else {
      cards.push(sslCard);
      const wafOn = sites.waf_on ?? 0;
      cards.push({ key: 'waf', icon: ShieldAlert, label: 'WAF', value: `${wafOn}/${sites.total}`,
        detail: !sites.total ? t('No websites yet') : wafOn === sites.total ? t('On for every website') : t('{n} website(s) without WAF', { n: sites.total - wafOn }),
        tone: !sites.total ? 'neutral' : wafOn === sites.total ? 'ok' : 'warn' });
      const twoFactor = !!currentUser?.totp_enabled;
      cards.push({ key: 'security', icon: LockKeyhole, label: t('Two-factor sign-in'),
        value: twoFactor ? t('On') : t('Off'), detail: t('Account security'), tone: twoFactor ? 'ok' : 'warn' });
    }

    // Only what is actually wrong, worst first, each with a way to the page
    // that fixes it.
    const attention = [];
    const flag = (tone, text, target, action = t('Open'), icon = AlertCircle) => attention.push({ tone, text, target, action, icon });
    if (isAdmin && sum.services?.stopped?.length) flag('bad', t('Stopped: {names}', { names: sum.services.stopped.join(', ') }), 'services');
    if (isAdmin && sum.firewall?.enabled === false) flag('bad', t('The firewall is off.'), 'firewall');
    if (isAdmin && sum.malware?.last_scan?.infected) flag('bad', t('The last malware scan found {n} threat(s).', { n: sum.malware.last_scan.infected }), 'malware');
    if (isAdmin && sum.backups?.failed) flag('bad', t('{n} scheduled backup(s) failed on their last run.', { n: sum.backups.failed }), 'backups');
    if (ssl.unsecured_count) flag('warn', t('{n} website(s) without SSL: {domains}', {
      n: ssl.unsecured_count, domains: ssl.unsecured.join(', ') + (ssl.unsecured_count > ssl.unsecured.length ? ', ...' : ''),
    }), 'ssl', t('Install SSL'));
    if (sites.suspended) flag('warn', t('{n} website(s) suspended.', { n: sites.suspended }), 'websites');
    if (isAdmin && sum.backups && !sum.backups.schedules) flag('warn', t('No scheduled backup is set up.'), 'backups', t('Set up'));
    if (isAdmin && sum.waf?.engine === 'off') flag('warn', t('The WAF engine is not installed.'), 'waf');
    if (isAdmin && sum.malware && !sum.malware.installed) flag('warn', t('The malware scanner is not installed.'), 'malware');
    if (!isAdmin && currentUser && !currentUser.totp_enabled) flag('info', t('Two-factor sign-in is off for your account.'), 'security', t('Turn on'), LockKeyhole);
    if (isAdmin && sum.updates?.update_available) flag('info', t('Panel update {version} is available.', { version: sum.updates.latest_version }), 'updates', t('Open'), RefreshCw);

    // The create forms open with the page, so "New website" is one click.
    const quickActions = [
      { key: 'site', icon: Plus, label: t('New website'), primary: true, run: () => { setCreateFormOpen(true); navigateToPage('websites'); } },
      { key: 'db', icon: Database, label: t('New database'), run: () => { setDbCreateOpen(true); navigateToPage('databases'); } },
      { key: 'ssl', icon: Lock, label: t('Install SSL'), run: () => navigateToPage('ssl') },
      { key: 'backup', icon: Archive, label: t('Back up a website'), run: () => navigateToPage('backups') },
      { key: 'sftp', icon: KeyRound, label: t('New SFTP account'), run: () => {
        navigateToPage('sftp');
        window.setTimeout(() => document.querySelector('.sftp-form input')?.focus(), 150);
      } },
      ...(isAdmin ? [{ key: 'users', icon: Users, label: t('Panel users'), run: () => navigateToPage('users') }] : []),
    ];

    return <div className="dashboard">
      {isAdmin && <section className="section dash-card dash-resources">
        <div className="dash-card-head"><span className="dash-card-icon"><Activity size={16}/></span><h2>{t('Server resources')}</h2></div>
        <div className="resource-grid">
          <ResourceCard icon={Cpu} label="CPU" value={formatPercent(cpu.percent)} percent={cpu.percent} detail={cpu.load?.length ? t('Load {load}', { load: cpu.load.join(' / ') }) : t('{count} cores', { count: cpu.cores || '--' })} />
          <ResourceCard icon={MemoryStick} label="RAM" value={formatPercent(memory.percent)} percent={memory.percent} detail={`${formatBytes(memory.used)} / ${formatBytes(memory.total)}`} />
          <ResourceCard icon={HardDrive} label={t('Disk')} value={formatPercent(disk.percent)} percent={disk.percent} detail={`${formatBytes(disk.used)} / ${formatBytes(disk.total)}`} />
          <ResourceCard icon={Network} label={t('Network')} value={`${formatBytes(networkTotal)}/s`} detail={t('Down {down}/s · Up {up}/s', { down: formatBytes(network.rx_per_sec), up: formatBytes(network.tx_per_sec) })} />
        </div>
      </section>}
      {/* A customer never sees the server's meters; their counterpart is how
          much of the package is used. */}
      {!isAdmin && currentUser && (() => {
        const storageLimit = storageLimitBytes(currentUser);
        const siteLimit = Number(currentUser.website_limit) || 0;
        const usedBytes = Number(currentUser.storage_used_bytes) || 0;
        const pct = (used, limit) => limit > 0 ? (used / limit) * 100 : null;
        return <section className="section dash-card dash-resources" style={{ '--meter-cols': 3 }}>
          <div className="dash-card-head"><span className="dash-card-icon"><Activity size={16}/></span><h2>{t('Plan usage')}</h2></div>
          <div className="resource-grid">
            <ResourceCard icon={HardDrive} label={t('Storage')} value={storageLimit ? formatPercent(pct(usedBytes, storageLimit)) : formatBytes(usedBytes)} percent={storageLimit ? pct(usedBytes, storageLimit) : null} detail={storageLimit ? t('{used} of {limit}', { used: formatBytes(usedBytes), limit: formatBytes(storageLimit) }) : t('unlimited')} />
            <ResourceCard icon={Globe} label={t('Websites')} value={siteLimit ? `${websites.length} / ${siteLimit}` : String(websites.length)} percent={pct(websites.length, siteLimit)} detail={siteLimit ? t('{used} of {limit}', { used: websites.length, limit: siteLimit }) : t('unlimited')} />
            <ResourceCard icon={Database} label={t('Databases')} value={String(databases.length)} percent={null} detail={t('in your account')} />
          </div>
        </section>;
      })()}

      {/* Eight cards for an administrator go 4 + 4, three for a customer sit
          in one row; each opens its page. */}
      <div className={`status-grid${cards.length > 4 ? ' many' : ''}`} style={{ '--status-cols': Math.min(4, cards.length) }}>
        {cards.map(card => <button type="button" key={card.key} className={`status-card tone-${card.tone}`} onClick={() => navigateToPage(card.key)}>
          <span className="status-card-head"><card.icon size={15}/><span>{card.label}</span></span>
          <strong>{card.value}</strong>
          <small>{card.detail}</small>
        </button>)}
      </div>

      <div className="dash-bottom">
        <section className="section dash-card">
          <div className="dash-card-head"><span className="dash-card-icon"><AlertCircle size={16}/></span><h2>{t('Needs attention')}</h2></div>
          {attention.length === 0
            ? <div className="attention-ok"><CheckCircle size={16}/>{dashSummary ? t('Everything looks fine.') : t('Checking...')}</div>
            : <div className="attention-list">
                {attention.map(item => <div className={`attention-item tone-${item.tone}`} key={item.text}>
                  <item.icon size={15}/>
                  <span>{item.text}</span>
                  <button type="button" className="mini secondary" onClick={() => navigateToPage(item.target)}>{item.action}</button>
                </div>)}
              </div>}
        </section>
        <section className="section dash-card">
          <div className="dash-card-head"><span className="dash-card-icon"><Zap size={16}/></span><h2>{t('Quick actions')}</h2></div>
          <div className="quick-actions">
            {quickActions.map(action => <button type="button" key={action.key} className={action.primary ? '' : 'secondary'} onClick={action.run}><action.icon size={15}/>{action.label}</button>)}
          </div>
        </section>
      </div>
    </div>;
  }

  function renderAdminOnly() {
    // For pages that describe the machine rather than a customer's slice of it.
    // They stay reachable by URL, so they say so plainly instead of rendering
    // and firing a page full of requests the server will refuse.
    return <section className="section">
      <div className="section-title"><div><h2>{t('Administrators only')}</h2></div></div>
      <EmptyState
        icon={Server}
        message={t('This page reports on the server itself, so only administrators can see it.')}
      />
    </section>;
  }

  function renderAddonMissing() {
    return <section className="section">
      <div className="section-title"><div><h2>{t('Applications')}</h2></div></div>
      <EmptyState
        icon={Boxes}
        message={applicationAddonInstalled
          ? 'Your package does not include Applications. Contact an administrator to upgrade.'
          : 'The Applications addon is not installed on this server.'}
      />
      {isAdmin && !applicationAddonInstalled && <div className="site-app-form-actions">
        <button disabled={!!loading} onClick={() => navigateToPage('addons')}><Boxes size={14}/>{t('Go to Addons')}</button>
      </div>}
    </section>;
  }

  function renderAddons() {
    return <section className="section">
      <div className="section-title">
        <div>
          <h2>{t('Addons')}</h2>
          <p className="hint">
            {t('The parts that are not in a default install. Add what you need, remove what you do not — removing turns the feature off and deletes nothing it created.')}
          </p>
        </div>
        <button className="secondary-light" disabled={!!loading} onClick={loadAddons}><RefreshCw size={14}/>{t('Refresh')}</button>
      </div>
      <div className="addon-list">
        {addons.items.map(addon => <div className={`addon-card ${addon.installed ? 'installed' : ''}`} key={addon.slug}>
          <div className="addon-head">
            <strong>{t(addon.name)}</strong>
            <code>v{addon.installed ? (addon.installed_version || addon.version) : addon.version}</code>
            <span className={`badge ${addon.installed ? 'ok' : ''}`}>{addon.installed ? t('Installed') : t('Not installed')}</span>
            {addon.installed && addon.installed_version && addon.installed_version !== addon.version
              && <span className="badge">v{addon.version} available</span>}
          </div>
          <p className="addon-summary">{t(addon.summary)}</p>
          {/* The card is the summary and the button; what it installs and
              what to know first are one click away rather than a page. */}
          {(addon.details?.length > 0 || addon.notes?.length > 0) && <details className="addon-more">
            <summary>{t('Details')}</summary>
            {addon.details?.length > 0 && <ul className="addon-details">
              {addon.details.map((line, index) => <li key={index}>{t(line)}</li>)}
            </ul>}
            {addon.notes?.length > 0 && <div className="addon-notes">
              <strong><AlertCircle size={13}/>{t('Worth knowing first')}</strong>
              <ul>{addon.notes.map((line, index) => <li key={index}>{t(line)}</li>)}</ul>
            </div>}
          </details>}
          {addons.can_manage && <div className="addon-actions">
            {addon.installed
              ? <>
                  {addon.slug === 'application' && <button className="secondary-light" disabled={!!loading} onClick={() => navigateToPage('applications')}>{t('Open')} {t(addon.name)}</button>}
                  <button className="danger" disabled={!!loading} onClick={() => setAddonInstalled(addon.slug, false)}><Trash2 size={14}/>{t('Remove')}</button>
                </>
              : <button disabled={!!loading} onClick={() => setAddonInstalled(addon.slug, true)}><Download size={14}/>{t('Install')}</button>}
          </div>}
        </div>)}
        {addons.loaded && addons.items.length === 0 && <EmptyState icon={Boxes} message={t('No addons yet.')} />}
      </div>
    </section>;
  }

  function renderApplications() {
    const [portFrom, portTo] = siteApps.port_range || [21000, 21999];
    const atLimit = !isAdmin && siteApps.limit > 0 && siteApps.used >= siteApps.limit;
    const dockerReady = !!siteRuntimes.docker?.installed;
    const kindHint = (SITE_APP_KINDS.find(([value]) => value === siteAppDraft.kind) || [])[2];
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Applications')}</h2>
            <p className="hint">
              {t('Each application runs on its own port under its own systemd unit. Point a website at one by setting its mode to')} <strong>{t('Application')}</strong>.
              {siteApps.limit > 0 && <> {t('Using {used} of {limit} allowed.', { used: siteApps.used, limit: siteApps.limit })}</>}
            </p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={() => { loadSiteApps(); loadSiteRuntimes(); }}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        <div className="site-runtime-strip">
          <span>{t('Docker:')}{' '}<strong>{dockerReady ? (siteRuntimes.docker.version || 'installed') : 'not installed'}</strong></span>
          <span>{t('Node:')}{' '}<strong>{siteRuntimes.node_majors?.length ? siteRuntimes.node_majors.map(major => `v${major}`).join(', ') : 'system version only'}</strong></span>
          {isAdmin && !dockerReady && <button className="mini secondary-light" disabled={!!loading} onClick={installDockerEngine}>{t('Install Docker')}</button>}
          {isAdmin && <button className="mini secondary-light" disabled={!!loading} onClick={() => { const major = prompt('Install which Node major version?', '22'); if (major) installNodeMajor(major.trim()); }}>{t('Add Node version')}</button>}
        </div>
        {isAdmin && dockerReady && siteRuntimes.docker?.disk?.length > 0 && <div className="site-runtime-strip">
          <span>{t('Docker disk (whole server, not counted against customer quotas):')}</span>
          {siteRuntimes.docker.disk.map(row => <span key={row.type}>
            {row.type}: <strong>{row.size}</strong>{row.reclaimable && !row.reclaimable.startsWith('0B') ? <> · {row.reclaimable} reclaimable</> : null}
          </span>)}
          <button className="mini secondary-light" disabled={!!loading} onClick={pruneDocker}>{t('Prune unused layers')}</button>
        </div>}
        {!atLimit && <div className="site-app-form">
          <label><span>{t('Name')}</span>
            <input value={siteAppDraft.name} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, name: e.target.value }))} />
          </label>
          <label><span>{t('Runtime')}</span>
            <select value={siteAppDraft.kind} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, kind: e.target.value }))}>
              {SITE_APP_KINDS.map(([value, label]) => <option key={value} value={value} disabled={value === 'docker' && !dockerReady}>{t(label)}</option>)}
            </select>
          </label>
          <label><span>{t('Port')}</span>
            <input
              type="number"
              value={siteAppDraft.port}
              min={portFrom}
              max={portTo}
              disabled={!!loading}
              placeholder={`auto (${portFrom}-${portTo})`}
              onChange={e => setSiteAppDraft(prev => ({ ...prev, port: e.target.value }))}
            />
          </label>
          <label><span>{t('Memory (MB)')}</span>
            <input
              type="number"
              value={siteAppDraft.memory_limit_mb}
              min={64}
              max={siteApps.memory_ceiling_mb || 512}
              disabled={!!loading}
              placeholder={String(siteApps.memory_ceiling_mb || 512)}
              onChange={e => setSiteAppDraft(prev => ({ ...prev, memory_limit_mb: e.target.value }))}
            />
          </label>
          {siteAppDraft.kind === 'node' && <>
            <label><span>{t('Start with')}</span>
              <select value={siteAppDraft.start_kind} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, start_kind: e.target.value }))}>
                <option value="npm">npm run</option>
                <option value="npx">npx</option>
                <option value="yarn">yarn</option>
                <option value="node">node</option>
              </select>
            </label>
            <label><span>{siteAppDraft.start_kind === 'node' ? 'Entry file' : 'Script or package'}</span>
              <input value={siteAppDraft.start_arg} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, start_arg: e.target.value }))} placeholder={siteAppDraft.start_kind === 'node' ? 'server.js' : 'start'} />
            </label>
            <label><span>{t('Node version')}</span>
              <select value={siteAppDraft.node_major} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, node_major: e.target.value }))}>
                {(siteRuntimes.node_majors?.length ? siteRuntimes.node_majors : ['22']).map(major => <option key={major} value={major}>Node {major}</option>)}
              </select>
            </label>
          </>}
          {siteAppDraft.kind === 'compose' && <>
            <label className="site-app-env"><span>docker-compose.yml</span>
              <textarea
                className="code-editor"
                rows={12}
                value={siteAppDraft.compose_source}
                disabled={!!loading}
                onChange={e => { setSiteAppDraft(prev => ({ ...prev, compose_source: e.target.value })); setComposePlan(null); }}
                placeholder={'services:\n  app:\n    image: myorg/app:1.0\n    ports: ["3000:3000"]\n  db:\n    image: postgres:16\n    volumes: ["pgdata:/var/lib/postgresql/data"]\nvolumes:\n  pgdata:'}
              />
            </label>
            {composePlan?.services?.length > 0 && <label><span>{t('Service behind the domain')}</span>
              <select value={siteAppDraft.web_service} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, web_service: e.target.value }))}>
                <option value="">{t('Choose for me')}</option>
                {composePlan.services.map(service => <option key={service.name} value={service.name}>{service.name}{service.container_port ? ` · :${service.container_port}` : ''}</option>)}
              </select>
            </label>}
            {composeWebPorts(composePlan, siteAppDraft.web_service).length > 1 && <label><span>{t('Port behind the domain')}</span>
              <select value={siteAppDraft.container_port} disabled={!!loading} onChange={e => { setSiteAppDraft(prev => ({ ...prev, container_port: e.target.value })); setComposePlan(null); }}>
                {composeWebPorts(composePlan, siteAppDraft.web_service).map(port => <option key={port} value={port}>{port}</option>)}
              </select>
            </label>}
            <label><span>{t('CPU per service')}</span>
              <input value={siteAppDraft.cpu_limit} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, cpu_limit: e.target.value }))} placeholder="1" />
            </label>
            <p className="compose-hint">{t('Where the file refers to')}{' '}<code>{'${VAR}'}</code>, set the value in the <strong>.env</strong> box below,
              exactly as an <code>.env</code> file beside <code>docker-compose.yml</code> would. For a public address
              (an OAuth callback, a webhook) use <code>{'${BPANEL_URL}'}</code> / <code>{'${BPANEL_DOMAIN}'}</code>:
              the app only ever sees its internal port, and the panel fills in the domain of the website pointing at it.</p>
          </>}
          {siteAppDraft.kind === 'docker' && <>
            <label><span>{t('Image')}</span>
              <input value={siteAppDraft.image} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, image: e.target.value }))} placeholder="n8nio/n8n:latest" />
            </label>
            <label><span>{t('Port in container')}</span>
              <input type="number" value={siteAppDraft.container_port} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, container_port: e.target.value }))} placeholder="3000" />
            </label>
            <label><span>CPU</span>
              <input value={siteAppDraft.cpu_limit} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, cpu_limit: e.target.value }))} placeholder="1" />
            </label>
          </>}
          <label className="site-app-env"><span>{siteAppDraft.kind === 'compose' ? '.env (KEY=value, one per line)' : 'Environment (KEY=value, one per line)'}</span>
            <textarea
              className="code-editor"
              rows={4}
              value={siteAppDraft.env}
              disabled={!!loading}
              onChange={e => setSiteAppDraft(prev => ({ ...prev, env: e.target.value }))}
              placeholder={'N8N_ENCRYPTION_KEY=...\nGENERIC_TIMEZONE=Asia/Ho_Chi_Minh'}
            />
          </label>
          <div className="site-app-form-actions">
            {siteAppDraft.kind === 'compose' && <button className="secondary-light" disabled={!!loading || !siteAppDraft.compose_source.trim()} onClick={checkComposeFile}>{t('Check file')}</button>}
            <button className="secondary-light" disabled={!!loading} onClick={suggestSiteAppPort}>{t('Pick free port')}</button>
            <button disabled={!!loading || !siteAppDraft.name.trim()} onClick={createSiteApp}><Plus size={14}/>{t('Install application')}</button>
          </div>
          {composePlan && <div className={`compose-report ${composePlan.ok ? 'ok' : 'bad'}`}>
            {composePlan.ok
              ? <p><Check size={14}/> {t('{n} service(s) will run.', { n: composePlan.services.length })} <strong>{composePlan.web_service}</strong> {t('serves the domain.')}</p>
              : <p><AlertCircle size={14}/> {t('{n} thing(s) to fix before importing:', { n: composePlan.issues.length })}</p>}
            {composePlan.issues.length > 0 && <ul>
              {composePlan.issues.map((issue, index) => <li key={index}>
                {issue.service && <code>{issue.service}</code>} {issue.message}
              </li>)}
            </ul>}
            {composePlan.notes?.length > 0 && <ul className="compose-notes">
              {composePlan.notes.map((note, index) => <li key={index}>{note}</li>)}
            </ul>}
            {composePlan.ok && <ul className="compose-services">
              {composePlan.services.map(service => <li key={service.name}>
                <code>{service.name}</code> {service.image}
                {service.web ? ' · serves the domain' : ' · internal only'}
                {service.container_port ? ` · port ${service.container_port}` : ''}
              </li>)}
            </ul>}
          </div>}
        </div>}
        {atLimit && <p className="hint">{t('This package allows {n} application(s). Delete one to install another.', { n: siteApps.limit })}</p>}
        {kindHint && <p className="hint site-apps-note">{kindHint} {t('Containers publish on 127.0.0.1 only, run as your own user with no capabilities, and are capped at the memory shown.')} {t('Images come from {list}.', { list: (siteRuntimes.allowed_registries || []).join(', ') || t('the allowed registries') })}</p>}
      </section>

      <section className="section">
        <div className="section-title">
          <div><h2>{t('Installed')}</h2><p className="hint">{t('{n} application(s)', { n: siteApps.items.length })}</p></div>
        </div>
        {siteApps.items.length === 0 && <EmptyState icon={Server} message={t('No applications yet. Install one above.')} />}
        <div className="site-app-list">
          {siteApps.items.map(app => <div className="site-app-item" key={app.id}>
            <div className="site-app-head">
              <strong>{app.name}</strong>
              <span className="badge">{SITE_APP_KIND_LABELS[app.kind] || app.kind}</span>
              <code>127.0.0.1:{app.port}</code>
              <span className={`badge ${app.status === 'running' ? 'ok' : app.status === 'error' ? 'bad' : ''}`}>
                {app.status === 'running' ? 'Running' : app.status === 'error' ? 'Failed' : 'Stopped'}
              </span>
              {app.websites?.length > 0 && <span className="site-app-domains">{app.websites.join(', ')}</span>}
            </div>
            {app.last_error && <p className="site-app-error">{app.last_error}</p>}
            <dl className="site-app-meta">
              <div><dt>{t('Upload code to')}</dt><dd><code>{app.directory}</code></dd></div>
              {app.kind === 'node' && <div><dt>{t('Start')}</dt><dd><code>{app.start_kind} {app.start_arg}</code></dd></div>}
              {app.kind === 'node' && <div><dt>Node</dt><dd>v{app.node_major || '22'}</dd></div>}
              {app.kind === 'compose' && <div><dt>{t('Serves domain')}</dt><dd><code>{app.web_service}</code></dd></div>}
              {app.kind === 'docker' && <div><dt>{t('Image')}</dt><dd><code>{app.image}</code></dd></div>}
              {app.kind === 'docker' && <div><dt>{t('In container')}</dt><dd>port {app.container_port} · {app.cpu_limit} CPU</dd></div>}
              <div><dt>{t('Unit')}</dt><dd><code>{app.unit}</code></dd></div>
            </dl>
            <div className="site-app-actions">
              <div className="site-app-fields">
                <label className="site-app-port">
                  <span>{t('Port')}</span>
                  <input
                    type="number"
                    defaultValue={app.port}
                    min={portFrom}
                    max={portTo}
                    disabled={!!loading}
                    onBlur={e => {
                      const next = Number(e.target.value);
                      if (next && next !== app.port) updateSiteApp(app, { port: next }, t('Moving application port...'));
                    }}
                  />
                </label>
                <label className="site-app-port">
                  <span>{t('Memory (MB)')}</span>
                  <input
                    type="number"
                    defaultValue={app.memory_limit_mb}
                    min={64}
                    max={isAdmin ? 16384 : (siteApps.memory_ceiling_mb || 512)}
                    disabled={!!loading}
                    onBlur={e => {
                      const next = Number(e.target.value);
                      if (next && next !== app.memory_limit_mb) updateSiteApp(app, { memory_limit_mb: next }, t('Applying the new memory limit...'));
                    }}
                  />
                </label>
                {app.kind === 'docker' && <label className="site-app-port">
                  <span>CPU</span>
                  <input
                    defaultValue={app.cpu_limit}
                    disabled={!!loading}
                    onBlur={e => {
                      const next = e.target.value.trim();
                      if (next && next !== app.cpu_limit) updateSiteApp(app, { cpu_limit: next }, t('Applying the new CPU limit...'));
                    }}
                  />
                </label>}
              </div>
              <div className="site-app-buttons">
                <button className="mini secondary-light" disabled={!!loading} onClick={() => openSiteAppEdit(app)}><Pencil size={13}/> {app.kind === 'compose' ? 'Compose' : 'Environment'}</button>
                <button className="mini secondary-light" disabled={!!loading} onClick={() => openAppFileManager(app)}><FolderOpen size={13}/>{t('Files')}</button>
                <button className="mini" disabled={!!loading} onClick={() => deploySiteApp(app)}><Play size={13}/>{t('Deploy')}</button>
                <button className="mini secondary-light" disabled={!!loading} onClick={() => controlSiteApp(app, 'restart')}><RotateCcw size={13}/>{t('Restart')}</button>
                <button className="mini secondary-light" disabled={!!loading} onClick={() => controlSiteApp(app, 'stop')}><Square size={13}/>{t('Stop')}</button>
                <button className="mini secondary-light" disabled={!!loading} onClick={() => openSiteAppLog(app)}><FileText size={13}/>{t('Log')}</button>
                <button className="mini danger" disabled={!!loading} onClick={() => deleteSiteApp(app)}><Trash2 size={13}/>{t('Delete')}</button>
              </div>
            </div>
            {siteAppEdit?.id === app.id && <div className="site-app-editor">
              {app.kind === 'compose' ? <>
                <label className="site-app-env"><span>docker-compose.yml</span>
                  <textarea
                    className="code-editor"
                    rows={14}
                    value={siteAppEdit.compose_source}
                    disabled={!!loading}
                    onChange={e => { setSiteAppEdit(prev => ({ ...prev, compose_source: e.target.value })); setSiteAppEditPlan(null); }}
                  />
                </label>
                <p className="compose-hint">{t('The panel reads this file and generates the one it actually runs.')}{' '}<code>{'${VAR}'}</code> comes
                  from the .env box; for a public address use <code>{'${BPANEL_URL}'}</code> / <code>{'${BPANEL_DOMAIN}'}</code>
                  {app.websites?.length > 0 ? ` (currently ${app.websites[0]})` : ' (point a website at this app first)'}.</p>
                <label className="site-app-env"><span>.env (KEY=value, one per line)</span>
                  <textarea
                    className="code-editor"
                    rows={6}
                    value={siteAppEdit.env}
                    disabled={!!loading}
                    onChange={e => { setSiteAppEdit(prev => ({ ...prev, env: e.target.value })); setSiteAppEditPlan(null); }}
                  />
                </label>
                {siteAppEditPlan?.services?.length > 0 && <label><span>{t('Service behind the domain')}</span>
                  <select value={siteAppEdit.web_service} disabled={!!loading} onChange={e => setSiteAppEdit(prev => ({ ...prev, web_service: e.target.value }))}>
                    <option value="">{t('Choose for me')}</option>
                    {siteAppEditPlan.services.map(service => <option key={service.name} value={service.name}>{service.name}{service.container_port ? ` · :${service.container_port}` : ''}</option>)}
                  </select>
                </label>}
                {composeWebPorts(siteAppEditPlan, siteAppEdit.web_service).length > 1 && <label><span>{t('Port behind the domain')}</span>
                  <select value={siteAppEdit.container_port} disabled={!!loading} onChange={e => { setSiteAppEdit(prev => ({ ...prev, container_port: e.target.value })); setSiteAppEditPlan(null); }}>
                    {composeWebPorts(siteAppEditPlan, siteAppEdit.web_service).map(port => <option key={port} value={port}>{port}</option>)}
                  </select>
                </label>}
              </> : <label className="site-app-env"><span>{t('Environment (KEY=value, one per line)')}</span>
                <textarea
                  className="code-editor"
                  rows={8}
                  value={siteAppEdit.env}
                  disabled={!!loading}
                  onChange={e => setSiteAppEdit(prev => ({ ...prev, env: e.target.value }))}
                />
              </label>}
              <div className="site-app-form-actions">
                {app.kind === 'compose' && <button className="secondary-light" disabled={!!loading || !siteAppEdit.compose_source.trim()} onClick={checkSiteAppEdit}>{t('Check file')}</button>}
                <button disabled={!!loading} onClick={() => saveSiteAppEdit(app)}><Save size={14}/>{t('Save')}</button>
                <button className="secondary-light" disabled={!!loading} onClick={() => { setSiteAppEdit(null); setSiteAppEditPlan(null); }}><X size={14}/>{t('Cancel')}</button>
              </div>
              {siteAppEditPlan && <div className={`compose-report ${siteAppEditPlan.ok ? 'ok' : 'bad'}`}>
                {siteAppEditPlan.ok
                  ? <p><Check size={14}/> {t('{n} service(s) will run.', { n: siteAppEditPlan.services.length })} <strong>{siteAppEditPlan.web_service}</strong> {t('serves the domain.')}</p>
                  : <p><AlertCircle size={14}/> {t('{n} thing(s) to fix:', { n: siteAppEditPlan.issues.length })}</p>}
                {siteAppEditPlan.issues.length > 0 && <ul>
                  {siteAppEditPlan.issues.map((issue, index) => <li key={index}>
                    {issue.service && <code>{issue.service}</code>} {issue.message}
                  </li>)}
                </ul>}
                {siteAppEditPlan.notes?.length > 0 && <ul className="compose-notes">
                  {siteAppEditPlan.notes.map((note, index) => <li key={index}>{note}</li>)}
                </ul>}
              </div>}
            </div>}
          </div>)}
        </div>
        {siteAppLog && <div className="site-app-log">
          <div className="site-app-log-head">
            <h4>{siteAppLog.name} log</h4>
            <button className="mini secondary-light" onClick={() => setSiteAppLog(null)}><X size={13}/>{t('Close')}</button>
          </div>
          <pre>{siteAppLog.log}</pre>
        </div>}
      </section>
    </>;
  }

  function renderNginxEditor() {
    if (!nginxCustomEditing) return null;
    const fullConfig = nginxCustomEditing.mode === 'full';
    const selectedAppType = websiteSettingsForm.app_type || nginxCustomEditing.site?.app_type || 'wordpress';
    const rewriteDisabled = selectedAppType !== 'php';
    const proxied = isProxiedAppType(selectedAppType);
    const settingsSite = nginxCustomEditing.site || {};
    const siteDomains = settingsSite.aliases || [];
    const aliasMode = aliasModes[nginxCustomEditing.id] || 'alias';
    return <section className="section nginx-modal inline-nginx-editor">
      <div className="section-title">
        <div className="nginx-config-title">
          <h2>{fullConfig ? 'Full Nginx config' : 'Website settings'} - {nginxCustomEditing.domain}</h2>
          <p className="hint">{fullConfig
            ? 'This is read-only. BPanel manages the main vhost template.'
            : 'Managed settings rewrite the main vhost safely. Custom Nginx is still stored as a separate include.'}</p>
        </div>
        <div className="actions">
          {!fullConfig && isAdmin && <button className="secondary-light" disabled={!!loading} onClick={viewFullNginxConfig}><FileText size={14}/>{t('View all')}</button>}
          {fullConfig && <button className="secondary-light" disabled={!!loading} onClick={() => setNginxCustomEditing(prev => ({ ...prev, mode: 'custom', content: prev?.customContent ?? prev?.content ?? '' }))}><SettingsIcon size={14}/>{t('Settings')}</button>}
          <button className="secondary-light" onClick={() => setNginxCustomEditing(null)}><X size={14}/>{t('Close')}</button>
        </div>
      </div>
      {!fullConfig && <div className="website-settings-grid">
        <label><span>{t('Website mode')}</span><select
          value={websiteSettingsForm.app_type}
          onChange={e => setWebsiteSettingsForm(prev => ({
            ...prev,
            app_type: e.target.value,
            nginx_rewrite_mode: e.target.value === 'php' ? prev.nginx_rewrite_mode || 'none' : e.target.value === 'wordpress' ? 'front_controller' : 'none',
          }))}
          disabled={!!loading}
        >
          {WEBSITE_MODES.map(([value, label]) => <option
            key={value}
            value={value}
            disabled={value === 'application' && !appsFeatureEnabled}
          >{t(label)}</option>)}
        </select></label>
        {proxied && <label><span>{t('Application')}</span><select
          value={websiteSettingsForm.app_id || ''}
          onChange={e => setWebsiteSettingsForm(prev => ({ ...prev, app_id: e.target.value }))}
          disabled={!!loading}
        >
          <option value="">{t('Select an application')}</option>
          {siteApps.items.map(app => <option key={app.id} value={app.id}>{app.name} · {SITE_APP_KIND_LABELS[app.kind] || app.kind} · :{app.port}</option>)}
        </select></label>}
        {selectedAppType !== 'static' && !proxied && <label><span>{t('PHP version')}</span><select
          value={websiteSettingsForm.php_version}
          onChange={e => setWebsiteSettingsForm(prev => ({ ...prev, php_version: e.target.value }))}
          disabled={!!loading}
        >
          {phpVersions.installed.map(v => <option key={v} value={v}>PHP {v}</option>)}
        </select></label>}
        <label><span>{t('Nginx rewrite')}</span><select
          value={rewriteDisabled ? (selectedAppType === 'wordpress' ? 'front_controller' : 'none') : websiteSettingsForm.nginx_rewrite_mode}
          onChange={e => setWebsiteSettingsForm(prev => ({ ...prev, nginx_rewrite_mode: e.target.value }))}
          disabled={!!loading || rewriteDisabled}
        >
          {NGINX_REWRITE_MODES.map(mode => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
        </select></label>
        <div className="website-settings-actions">
          <button disabled={!!loading} onClick={saveWebsiteSettings}><Save size={14}/>{t('Save settings')}</button>
        </div>
      </div>}
      {!fullConfig && <div className="site-aliases settings-domain-manager">
        <div className="domain-manager-head">
          <h3>{t('Domains')}</h3>
          <p className="hint">{t('Alias serves the same app. Redirect sends visitors to {domain}.', { domain: nginxCustomEditing.domain })}</p>
        </div>
        <div className="alias-list">
          <span className="alias-chip primary-domain"><Globe size={12}/>{nginxCustomEditing.domain}<span>{t('Main')}</span></span>
          {siteDomains.length === 0
            ? <span className="alias-empty">{t('No extra domains')}</span>
            : siteDomains.map(alias => <span className="alias-chip" key={alias.id}>
              <Globe size={12}/>{alias.domain}<span>{alias.mode === 'redirect' ? 'Redirect' : 'Alias'}</span>
              <button type="button" disabled={!!loading} title={`Remove ${alias.domain}`} aria-label={`Remove ${alias.domain}`} onClick={() => deleteWebsiteAlias(settingsSite, alias)}><X size={12}/></button>
            </span>)}
        </div>
        <div className="alias-form settings-domain-form">
          <input
            value={aliasDrafts[nginxCustomEditing.id] || ''}
            onChange={e => setAliasDrafts(prev => ({ ...prev, [nginxCustomEditing.id]: e.target.value }))}
            onKeyDown={e => { if (e.key === 'Enter') addWebsiteAlias(settingsSite); }}
            placeholder="domain-alias.com"
            disabled={!!loading}
          />
          <select
            value={aliasMode}
            onChange={e => setAliasModes(prev => ({ ...prev, [nginxCustomEditing.id]: e.target.value }))}
            disabled={!!loading}
          >
            <option value="alias">{t('Alias')}</option>
            <option value="redirect">{t('Redirect')}</option>
          </select>
          <button className="secondary-light" disabled={!!loading || !(aliasDrafts[nginxCustomEditing.id] || '').trim()} onClick={() => addWebsiteAlias(settingsSite)}><Plus size={14}/>{t('Add domain')}</button>
        </div>
      </div>}
      <div className="custom-nginx-block">
        {!fullConfig && <h3>{t('Custom Nginx')}</h3>}
        <textarea
          className="code-editor"
          value={nginxCustomEditing.content}
          onChange={e => setNginxCustomEditing(prev => ({ ...prev, content: e.target.value, customContent: e.target.value }))}
          placeholder={fullConfig
            ? `server {\n    listen 80;\n    server_name ${nginxCustomEditing.domain};\n}`
            : `# Optional extra directives only. Use Nginx rewrite above for location / routing.`}
          spellCheck={false}
          rows={fullConfig ? 18 : 10}
          readOnly={fullConfig}
        />
      </div>
      <div className="actions">
        {!fullConfig && <button disabled={!!loading} onClick={saveNginxCustom}>{t('Save and reload Nginx')}</button>}
        {!fullConfig && <button className="secondary-light" disabled={!!loading} onClick={resetNginxDefault}><RotateCcw size={14}/>{t('Reset custom')}</button>}
        <button className="secondary-light" disabled={!!loading} onClick={() => setNginxCustomEditing(null)}>{fullConfig ? 'Close' : 'Cancel'}</button>
      </div>
    </section>;
  }

  function renderWordPressInstaller() {
    if (!wordpressInstaller) return null;
    return <section className="section nginx-modal inline-nginx-editor wordpress-install-modal">
      <div className="section-title">
        <div className="nginx-config-title">
          <h2>{t('Install WordPress -')} {wordpressInstaller.domain}</h2>
          <p className="hint">PHP {wordpressInstaller.php_version || '8.4'}</p>
        </div>
        <button className="secondary-light" onClick={() => setWordpressInstaller(null)}><X size={14}/>{t('Close')}</button>
      </div>
      <div className="website-settings-grid">
        <label><span>{t('Site title')}</span><input
          value={wordpressInstaller.title}
          onChange={e => setWordpressInstaller(prev => ({ ...prev, title: e.target.value }))}
          disabled={!!loading}
        /></label>
        <label><span>{t('Admin user')}</span><input
          value={wordpressInstaller.admin_user}
          onChange={e => setWordpressInstaller(prev => ({ ...prev, admin_user: e.target.value }))}
          disabled={!!loading}
        /></label>
        <label><span>{t('Admin email')}</span><input
          value={wordpressInstaller.admin_email}
          onChange={e => setWordpressInstaller(prev => ({ ...prev, admin_email: e.target.value }))}
          disabled={!!loading}
        /></label>
        <label><span>{t('Admin password')}</span><input
          value={wordpressInstaller.admin_password}
          onChange={e => setWordpressInstaller(prev => ({ ...prev, admin_password: e.target.value }))}
          disabled={!!loading}
        /></label>
        <div className="website-settings-actions">
          <button className="secondary-light" disabled={!!loading} onClick={() => setWordpressInstaller(prev => prev ? ({ ...prev, admin_password: generateRandomPassword(20) }) : prev)}><Dices size={14}/>{t('Generate')}</button>
          <button disabled={!!loading || !wordpressInstaller.admin_user || !wordpressInstaller.admin_email || !wordpressInstaller.admin_password} onClick={installWordPressOnSite}><WordPressIcon size={14}/>{t('Install')}</button>
        </div>
      </div>
    </section>;
  }


  function renderWebsiteTerminal() {
    if (!terminalViewer) return null;
    return <section className="section nginx-modal terminal-modal">
      <div className="section-title">
        <h2>{t('Terminal -')} {terminalViewer.domain}</h2>
        <button className="secondary-light" onClick={() => setTerminalViewer(null)}><X size={14}/>{t('Close')}</button>
      </div>
      <div style={{ height: '500px', marginTop: '8px' }}>
        <Terminal websiteId={terminalViewer.id} apiBase={API} />
      </div>
    </section>;
  }

  function renderWebsiteLogViewer() {
    if (!logViewer) return null;
    return <section className="section nginx-modal log-viewer">
      <div className="section-title">
        <div className="nginx-config-title">
          <h2>{t('Nginx logs -')} {logViewer.domain}</h2>
          <p className="hint">{logViewer.path || `/var/log/nginx/${logViewer.domain}.${logViewer.kind}.log`}</p>
        </div>
        <button className="secondary-light" onClick={() => setLogViewer(null)}><X size={14}/>{t('Close')}</button>
      </div>
      <div className="log-toolbar">
        <div className="segmented-control">
          <button className={logViewer.kind === 'access' ? 'active' : ''} disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, 'access', logViewer.lines, logViewer.domain)}>{t('Access')}</button>
          <button className={logViewer.kind === 'error' ? 'active' : ''} disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, 'error', logViewer.lines, logViewer.domain)}>{t('Error')}</button>
        </div>
        <select value={logViewer.lines} onChange={e => loadWebsiteLog(logViewer.id, logViewer.kind, Number(e.target.value), logViewer.domain)} disabled={!!loading}>
          <option value={100}>100 lines</option>
          <option value={200}>200 lines</option>
          <option value={500}>500 lines</option>
          <option value={1000}>1000 lines</option>
          <option value={2000}>2000 lines</option>
        </select>
        <button className="secondary-light" disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, logViewer.kind, logViewer.lines, logViewer.domain)}><RefreshCw size={14}/>{t('Refresh')}</button>
      </div>
      <pre className="log-output">{logViewer.exists ? (logViewer.content || 'Log is empty.') : 'Log file has not been created yet.'}</pre>
    </section>;
  }

  function renderWebsites() {
    const wpFieldsEnabled = siteType === 'wordpress' && installWordPress;
    const searchActive = !!websiteSearch.trim();
    const visibleWebsites = searchActive ? websiteList : (websiteList.length ? websiteList : websites);
    const createTitle = websites.length ? 'Create website' : 'Attach first domain';
    const createHint = websites.length
      ? null
      : 'This creates the first hosted site for the current account.';
    const createOpen = createFormOpen || websites.length === 0;
    // What secures a site, in OPanel's words: a wildcard, a certificate
    // borrowed from another site, one uploaded by hand, or Let's Encrypt.
    const sslBadge = site => !site.ssl_enabled ? t('No SSL')
      : site.ssl_mode === 'cloudflare' ? t('Wildcard')
        : site.ssl_mode === 'shared' ? t('Shared cert')
          : site.ssl_mode === 'manual' ? t('Manual SSL') : 'SSL OK';
    return <>
      {createOpen && <section className="section create-site-section">
        <div className="section-title">
          <div>
            <h2>{t(createTitle)}</h2>
            {createHint && <p className="hint">{t(createHint)}</p>}
          </div>
          {websites.length > 0 && <button
            type="button"
            className="secondary-light"
            onClick={() => setCreateFormOpen(false)}
          ><X size={15}/>{t('Close')}</button>}
        </div>
        <div className="form-row create-site-row">
          <input value={domain} onChange={e => setDomain(e.target.value)} placeholder="domain.com" />
          <select value={siteType} onChange={e => setSiteType(e.target.value)}>
            {WEBSITE_MODES.map(([value, label]) => <option
              key={value}
              value={value}
              disabled={value === 'application' && !appsFeatureEnabled}
            >{t(label)}</option>)}
          </select>
          {siteType === 'application'
            ? <select value={createSiteAppId} onChange={e => setCreateSiteAppId(e.target.value)}>
              <option value="">{t('Select an application')}</option>
              {siteApps.items.map(app => <option key={app.id} value={app.id}>{app.name} · {SITE_APP_KIND_LABELS[app.kind] || app.kind} · :{app.port}</option>)}
            </select>
            : <select value={phpVersion} onChange={e => setPhpVersion(e.target.value)}>
              {phpVersions.installed.map(v => <option key={v} value={v}>PHP {v}</option>)}
            </select>}
          {wpFieldsEnabled && <input value={adminEmail} onChange={e => setAdminEmail(e.target.value)} placeholder="admin@domain.com" />}
          {wpFieldsEnabled && <input value={wpAdminUser} onChange={e => setWpAdminUser(e.target.value)} placeholder={t('WP admin user')} />}
          {wpFieldsEnabled && <input value={wpAdminPassword} onChange={e => setWpAdminPassword(e.target.value)} placeholder={t('WP admin password')} type="password" />}
          <button disabled={!!loading || !domain} onClick={createWordPress}><Plus size={15}/>{t('Create')}</button>
        </div>
        {siteType === 'application' && siteApps.items.length === 0 && <p className="hint">{t('No applications installed yet. Install one on the')}<button type="button" className="link-button" onClick={() => navigateToPage('applications')}>{t('Applications')}</button> page first.
        </p>}
        {siteType === 'wordpress' && <label className="check-line">
          <input type="checkbox" checked={installWordPress} onChange={e => setInstallWordPress(e.target.checked)} />{t('Install WordPress (creates database, downloads WP, configures vhost)')}</label>}
        <div className="create-ssl-row">
          <span className="create-ssl-label">{t('SSL after creating')}</span>
          <div className="segmented ssl-mode-tabs">
            <button type="button" className={createSslMode === 'none' ? 'active' : ''} onClick={() => setCreateSslMode('none')}>{t('Off')}</button>
            <button type="button" className={createSslMode === 'letsencrypt' ? 'active' : ''} onClick={() => setCreateSslMode('letsencrypt')}><Lock size={13}/> Let's Encrypt</button>
            <button type="button" className={createSslMode === 'wildcard' ? 'active' : ''} onClick={() => setCreateSslMode('wildcard')}><Globe size={13}/>{t('Wildcard')}</button>
            <button type="button" className={createSslMode === 'shared' ? 'active' : ''} onClick={() => setCreateSslMode('shared')}><Copy size={13}/>{t('Existing cert')}</button>
            <button type="button" className={createSslMode === 'manual' ? 'active' : ''} onClick={() => setCreateSslMode('manual')}><KeyRound size={13}/>{t('Manual')}</button>
          </div>
        </div>
        {createSslMode !== 'none' && <div className="ssl-sub-form create-ssl-sub">
          {createSslMode === 'letsencrypt' && <p className="hint">{t('A certificate is issued right after the site is created — the domain must already point to this server.')}</p>}
          {createSslMode === 'wildcard' && <>
            <p className="hint">{t('Issues')}{' '}<code>zone + *.zone</code> over Cloudflare DNS. Leave the token blank to reuse one already saved for the zone.</p>
            <input type="password" autoComplete="off" placeholder={t('Cloudflare API token (Zone → DNS → Edit)')}
              value={createSslToken} onChange={e => setCreateSslToken(e.target.value)} />
          </>}
          {createSslMode === 'shared' && <p className="hint">{t('After the site is created the panel points it at an existing certificate that covers this domain (a wildcard first). If none does, the site is created without SSL.')}</p>}
          {createSslMode === 'manual' && <p className="hint">{t('The site is created, then the panel opens the SSL page so you can paste the certificate and key.')}</p>}
        </div>}
        <p className="hint">{t(wpFieldsEnabled
          ? 'WordPress will be installed and the panel will show the URL, admin account, and password after creation.'
          : siteType === 'application'
            ? 'Nginx will forward this domain to the selected application on 127.0.0.1, including WebSocket upgrades.'
            : 'A PHP-FPM vhost will be created with public_html/ folder. Upload your PHP, HTML, or static files via File Manager.')}</p>
      </section>}
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Website list')}</h2></div>
          <div className="actions">
            <button className="secondary" disabled={!!loading || websiteSearching} onClick={() => loadWebsiteList(websiteSearch, true)}><RefreshCw size={15} className={websiteSearching ? 'spin' : ''}/>{t('Refresh')}</button>
            {!createOpen && <button type="button" onClick={() => setCreateFormOpen(true)}><Plus size={15}/>{t('New website')}</button>}
          </div>
        </div>
        <div className="website-search">
          <Search size={15}/>
          <NoAutofillInput
            type="search"
            name="website-search"
            value={websiteSearch}
            onChange={e => setWebsiteSearch(e.target.value)}
            placeholder={t('Search domain, alias, path, or Linux user')}
            aria-label={t('Search websites')}
          />
          {websiteSearch && <button className="mini secondary-light" type="button" onClick={() => setWebsiteSearch('')} aria-label={t('Clear website search')} title={t('Clear search')}><X size={13}/></button>}
          <span className="hint">{searchActive ? t('{n} result(s)', { n: visibleWebsites.length }) : t('{n} website(s)', { n: visibleWebsites.length })}</span>
        </div>
        {visibleWebsites.length === 0 && <EmptyState icon={Globe} message={searchActive ? "No websites match this search." : "No websites yet."} />}
        <div className="site-grid">
          {visibleWebsites.map(site => <div className="site-stack" key={site.id}>
          <article className="site-card">
            <div className="site-head">
              <div>
                <a className="site-link" href={websiteUrl(site)} target="_blank" rel="noopener noreferrer">{site.domain}</a>
                <small>{site.root_path}</small>
              </div>
            </div>
            <div className="site-meta">
              <span className={`badge site-ssl-badge ${site.ssl_enabled ? 'ok' : 'warn'}`}>{sslBadge(site)}</span>
              <span>{APP_TYPE_LABELS[site.app_type || 'wordpress'] || site.app_type}</span>
              {site.app_type !== 'static' && <span>PHP{' '}<strong>{site.php_version}</strong></span>}
              {site.app_type === 'php' && site.nginx_rewrite_mode && site.nginx_rewrite_mode !== 'none' && <span>{t('Rewrite')}{' '}<strong>{site.nginx_rewrite_mode}</strong></span>}
              {site.nginx_custom && <span className="badge ok">{t('Custom Nginx')}</span>}
              {site.waf_enabled && <span className="badge ok">WAF</span>}
              {site.http_flood_enabled && <span className="badge ok">{t('HTTP Flood')}</span>}
              {(site.aliases || []).length > 0 && <span>{t('Domains')}{' '}<strong>{(site.aliases || []).length + 1}</strong></span>}
            </div>
            <div className="site-actions" aria-label={`Website actions for ${site.domain}`}>
              <div className="site-feature-actions">
                <button className="site-icon-button secondary-light" data-tooltip="Files" title={t('Files')} aria-label={`Open file manager for ${site.domain}`} disabled={!!loading} onClick={() => openWebsiteFileManager(site)}><FolderOpen size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Logs" title={t('Logs')} aria-label={`View logs for ${site.domain}`} disabled={!!loading} onClick={() => openWebsiteLogs(site)}><FileText size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Terminal" title={t('Terminal')} aria-label={`Open terminal for ${site.domain}`} disabled={!!loading} onClick={() => openWebsiteTerminal(site)}><TerminalIcon size={15}/></button>
                {site.wordpress_installed ? <>
                  <button className="site-icon-button secondary-light" data-tooltip="Update WordPress" title={t('Update WordPress (core + plugins + themes)')} aria-label={`Update WordPress for ${site.domain}`} disabled={!!loading} onClick={() => updateWordPressAll(site)}><RefreshCw size={15}/></button>
                </> : <button className="site-icon-button secondary-light" data-tooltip="Install WP" title={t('Install WordPress')} aria-label={`Install WordPress for ${site.domain}`} disabled={!!loading} onClick={() => openWordPressInstaller(site)}><WordPressIcon size={15}/></button>}
                <button className="site-icon-button secondary-light" data-tooltip="Settings" title={t('Settings')} aria-label={`Edit settings for ${site.domain}`} disabled={!!loading} onClick={() => openNginxCustom(site)}><SettingsIcon size={15}/></button>
                <button className="site-icon-button danger" data-tooltip="Delete" title={t('Delete')} aria-label={`Delete ${site.domain}`} disabled={!!loading} onClick={() => deleteWebsite(site.id)}><Trash2 size={15}/></button>
              </div>
            </div>
          </article>
          {String(wordpressInstaller?.website_id || '') === String(site.id) && renderWordPressInstaller()}
          {nginxCustomEditing?.id === site.id && renderNginxEditor()}
          {logViewer?.id === site.id && renderWebsiteLogViewer()}
          {terminalViewer?.id === site.id && renderWebsiteTerminal()}
          </div>)}
        </div>
      </section>
    </>;
  }

  function renderSsl() {
    const sslLabels = {
      manual: 'Manual SSL', cloudflare: 'Wildcard (Cloudflare)', shared: `Using ${currentSite?.ssl_source_domain || ''}`,
    };
    const sslLabel = currentSite?.ssl_enabled
      ? (sslLabels[currentSite?.ssl_mode] || 'SSL Enabled')
      : 'SSL Disabled';
    const locale = language === 'vi' ? 'vi-VN' : 'en-GB';
    const sslUpdated = currentSite?.ssl_updated_at ? new Date(currentSite.ssl_updated_at).toLocaleString(locale) : '';
    // Every site on one list, as OPanel has it: the unsecured first, then the
    // rest by name, each a click from the form above.
    const sslSites = [...websites].sort((a, b) => (a.ssl_enabled === b.ssl_enabled
      ? String(a.domain).localeCompare(String(b.domain)) : a.ssl_enabled ? 1 : -1));
    const securedCount = websites.filter(site => site.ssl_enabled).length;
    const siteSslLabel = site => !site.ssl_enabled ? t('No SSL')
      : site.ssl_mode === 'manual' ? t('Manual SSL')
        : site.ssl_mode === 'shared' ? t('Shared cert')
          : site.ssl_mode === 'cloudflare' ? t('Wildcard') : 'SSL OK';
    return <>
    <section className="section" id="ssl-manage">
      <h2>{t('SSL Certificate')}</h2>
      <WebsiteSelect />
      {currentSite && <div className="info-box" style={{marginTop:8}}>
        <strong>{currentSite.domain}</strong>
        <span className={currentSite.ssl_enabled ? 'badge ok' : 'badge'} style={{justifySelf:'start'}}>{t(sslLabel)}</span>
        {sslUpdated && <span className="hint">{t('Updated')} {sslUpdated}</span>}
        {currentSite.ssl_mode === 'manual' && currentSite.ssl_has_ca && <span className="badge ok" style={{justifySelf:'start'}}>{t('CA Bundle')}</span>}
      </div>}
      <div className="segmented ssl-mode-tabs">
        <button className={sslMode === 'letsencrypt' ? 'active' : ''} onClick={() => setSslMode('letsencrypt')}><Lock size={14}/> Let's Encrypt</button>
        <button className={sslMode === 'manual' ? 'active' : ''} onClick={() => setSslMode('manual')}><KeyRound size={14}/>{t('Manual')}</button>
        <button className={sslMode === 'wildcard' ? 'active' : ''} onClick={() => setSslMode('wildcard')}><Globe size={14}/>{t('Wildcard (Cloudflare)')}</button>
        <button className={sslMode === 'shared' ? 'active' : ''} onClick={() => setSslMode('shared')}><Copy size={14}/>{t('Use existing')}</button>
      </div>
      {sslMode === 'letsencrypt' && <>
        <button className="ssl-install" disabled={!selectedWebsiteId || !!loading} onClick={() => enableSsl(selectedWebsiteId)}><Lock size={15}/>{t('Install / Renew SSL')}</button>
        <p className="hint">{t('The domain must point to the correct VPS IP before issuing SSL.')}</p>
      </>}
      {sslMode === 'wildcard' && <div className="ssl-sub-form">
        <p className="hint">{t('Issues')}{' '}<code>{cfZone.zone ? `${cfZone.zone} + *.${cfZone.zone}` : 'zone + *.zone'}</code> over
          Cloudflare DNS. Needs an API token with <strong>{t('Zone → DNS → Edit')}</strong> for the zone.
        </p>
        {cfZone.has_token
          ? <p className="hint">✓ Token saved for <strong>{cfZone.zone}</strong>. Leave the field blank to reuse it.</p>
          : null}
        <input type="password" autoComplete="off" placeholder={t('Cloudflare API token')}
          value={wildcardToken} onChange={e => setWildcardToken(e.target.value)} />
        <button disabled={!selectedWebsiteId || !!loading} onClick={installWildcardSsl}>
          <Globe size={15}/>{t('Issue wildcard certificate')}</button>
      </div>}
      {sslMode === 'shared' && <div className="ssl-sub-form">
        <p className="hint">{t('Point this site at another BPanel website\'s certificate (e.g. a wildcard). No new certificate is issued.')}</p>
        {sslSources.length === 0
          ? <p className="hint">{t('No other website has a certificate that covers')}{' '}<strong>{currentSite?.domain}</strong>.</p>
          : <>
            <select value={sharedSource} onChange={e => setSharedSource(e.target.value)}>
              <option value="">{t('Select a source website…')}</option>
              {sslSources.map(s => <option key={s.domain} value={s.domain}>
                {s.domain}{s.wildcard ? ' (wildcard)' : ''}{s.not_after ? ` — expires ${s.not_after}` : ''}
              </option>)}
            </select>
            <button disabled={!selectedWebsiteId || !sharedSource || !!loading} onClick={installSharedSsl}>
              <Copy size={15}/>{t('Use this certificate')}</button>
          </>}
      </div>}
      {sslMode === 'manual' && <div className="manual-ssl-grid">
        <label>{t('Certificate (.crt/.pem)')}<input type="file" accept=".crt,.pem" onChange={e => setManualSslFiles(prev => ({ ...prev, certificate: e.target.files?.[0] || null }))} />
        </label>
        <label>{t('Private key (.key/.pem)')}<input type="file" accept=".key,.pem" onChange={e => setManualSslFiles(prev => ({ ...prev, private_key: e.target.files?.[0] || null }))} />
        </label>
        <label>{t('CA bundle (.ca/.crt/.pem)')}<input type="file" accept=".ca,.crt,.pem" onChange={e => setManualSslFiles(prev => ({ ...prev, ca_bundle: e.target.files?.[0] || null }))} />
        </label>
        <textarea rows={7} disabled={!!manualSslFiles.certificate} value={manualSslForm.certificate} onChange={e => setManualSslForm(prev => ({ ...prev, certificate: e.target.value }))} placeholder="-----BEGIN CERTIFICATE-----" />
        <textarea rows={7} disabled={!!manualSslFiles.private_key} value={manualSslForm.private_key} onChange={e => setManualSslForm(prev => ({ ...prev, private_key: e.target.value }))} placeholder="-----BEGIN PRIVATE KEY-----" />
        <textarea rows={7} disabled={!!manualSslFiles.ca_bundle} value={manualSslForm.ca_bundle} onChange={e => setManualSslForm(prev => ({ ...prev, ca_bundle: e.target.value }))} placeholder={t('Optional CA bundle')} />
        <button className="manual-ssl-submit" disabled={!selectedWebsiteId || !!loading} onClick={installManualSsl}><Upload size={15}/>{t('Install Manual SSL')}</button>
      </div>}
    </section>
    {websites.length > 0 && <section className="section">
      <div className="section-title">
        <div><h2>{t('All websites')}</h2><p className="hint">{t('{secured} of {total} secured', { secured: securedCount, total: websites.length })}</p></div>
      </div>
      <div className="table ssl-overview">
        {sslSites.map(site => <div className={`row ssl-overview-row${String(site.id) === String(selectedWebsiteId) ? ' selected' : ''}`} key={site.id}>
          <span className="ssl-overview-domain"><strong>{site.domain}</strong>{site.ssl_updated_at && <small>{t('Updated')} {new Date(site.ssl_updated_at).toLocaleDateString(locale)}</small>}</span>
          <span className={`badge ${site.ssl_enabled ? 'ok' : 'warn'}`}>{siteSslLabel(site)}</span>
          <button type="button" className="mini secondary" onClick={() => { setSelectedWebsiteId(String(site.id)); document.getElementById('ssl-manage')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>{site.ssl_enabled ? t('Manage') : t('Set up SSL')}</button>
        </div>)}
      </div>
    </section>}
    </>;
  }

  function renderDatabases() {
    function copyToClipboard(text, field) {
      const doCopy = navigator.clipboard ? navigator.clipboard.writeText(text) : new Promise((resolve, reject) => {
        try { const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); resolve(); } catch(e) { reject(e); }
      });
      doCopy.then(() => { setCopiedField(field); setTimeout(() => setCopiedField(null), 2000); }).catch(() => setError(t('Copy failed.')));
    }
    const dbSearchActive = !!dbSearch.trim();
    // Like the website form: making one is occasional, finding one is why
    // the page is open. Open by itself only when there is nothing to find.
    const dbCreateVisible = dbCreateOpen || (databases.length === 0 && !dbSearchActive);
    return <section className="section">
      <div className="section-title">
        <h2>{t('Databases')}</h2>
        <div className="actions">
          <button className="secondary" disabled={!!loading || dbSearching} onClick={() => loadDatabases(dbSearch, true)}><RefreshCw size={15} className={dbSearching ? 'spin' : ''}/>{t('Refresh')}</button>
          {!dbCreateVisible && <button type="button" onClick={() => setDbCreateOpen(true)}><Plus size={15}/>{t('New database')}</button>}
        </div>
      </div>
      {dbCreateVisible && <div className="create-inline">
        <div className="create-inline-head">
          <strong>{t('Create database')}</strong>
          {databases.length > 0 && <button type="button" className="secondary icon-only mini" onClick={() => setDbCreateOpen(false)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>}
        </div>
        <div className="form-row">
          <input name="new-db-name" autoComplete="off" value={newDatabase.db_name} onChange={e => setNewDatabase(prev => ({ ...prev, db_name: e.target.value }))} placeholder="database_name" />
          <input name="new-db-user" autoComplete="off" value={newDatabase.db_user} onChange={e => setNewDatabase(prev => ({ ...prev, db_user: e.target.value }))} placeholder={t('db_user (default = db_name)')} />
          {/* new-password, or the browser offers the panel's own password here. */}
          <input name="new-db-password" autoComplete="new-password" value={newDatabase.db_password} onChange={e => setNewDatabase(prev => ({ ...prev, db_password: e.target.value }))} placeholder={t('password (min 12 chars)')} />
          <button type="button" className="mini secondary-light" title={t('Generate random password')} onClick={() => setNewDatabase(prev => ({ ...prev, db_password: generateRandomPassword() }))}><Dices size={13}/></button>
          <button disabled={!!loading || !newDatabase.db_name.trim()} onClick={createDatabase}><Plus size={15}/>{t('Create database')}</button>
        </div>
      </div>}
      <div className="list-search">
        <Search size={15}/>
        <NoAutofillInput
          type="search"
          name="database-search"
          value={dbSearch}
          onChange={e => setDbSearch(e.target.value)}
          placeholder={t('Search by database or user name')}
          aria-label={t('Search databases')}
        />
        {dbSearch && <button className="mini secondary-light" type="button" onClick={() => setDbSearch('')} aria-label={t('Clear database search')} title={t('Clear search')}><X size={13}/></button>}
        <span className="hint">{t('{count} databases', { count: databases.length })}</span>
      </div>
      {createdDbInfo && <div className="info-box db-created-box">
        <div className="db-created-head"><strong>{t('Database created successfully')}</strong><button className="mini secondary-light" onClick={() => setCreatedDbInfo(null)}><X size={13}/></button></div>
        <div className="db-created-grid">
          <label>{t('Database')}</label><span>{createdDbInfo.db_name} <button className="mini secondary-light" title={copiedField === 'db_name' ? 'Copied!' : 'Copy'} onClick={() => copyToClipboard(createdDbInfo.db_name, 'db_name')}>{copiedField === 'db_name' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
          <label>{t('User')}</label><span>{createdDbInfo.db_user} <button className="mini secondary-light" title={copiedField === 'db_user' ? 'Copied!' : 'Copy'} onClick={() => copyToClipboard(createdDbInfo.db_user, 'db_user')}>{copiedField === 'db_user' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
          <label>{t('Password')}</label><span><code>{createdDbInfo.db_password}</code> <button className="mini secondary-light" title={copiedField === 'db_password' ? 'Copied!' : 'Copy'} onClick={() => copyToClipboard(createdDbInfo.db_password, 'db_password')}>{copiedField === 'db_password' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
        </div>
      </div>}
      {databases.length === 0 && !createdDbInfo && <EmptyState icon={Database} message={dbSearchActive ? 'No databases match this search.' : 'No databases found.'} />}
      <div className="table">
        {databases.map(db => {
          // Name and the site it belongs to, the login user, then the actions:
          // phpMyAdmin as the one labelled button, the rest as glyphs.
          const dbSite = websites.find(site => String(site.id) === String(db.website_id));
          return <div className="row db-row" key={db.id}>
          <span><strong>{db.db_name}</strong>{dbSite && <small className="db-owner">{dbSite.domain}</small>}</span>
          <span className="db-user"><small>{t('User')}</small> {db.db_user}</span>
          <span className="db-actions">
            <button className="mini secondary" disabled={!!loading} onClick={() => openPhpMyAdmin(db.id)}>phpMyAdmin</button>
            <button className="mini secondary-light icon-only" disabled={!!loading} onClick={() => downloadDatabase(db.id, db.db_name)} title={t('Download SQL dump')} aria-label={`${t('Download SQL dump')} ${db.db_name}`}><Download size={14}/></button>
            <button className="mini secondary-light icon-only" disabled={!!loading} onClick={() => changeDbPassword(db.id)} title={t('Change password')} aria-label={`${t('Change password')} ${db.db_name}`}><KeyRound size={14}/></button>
            <button className="mini danger icon-only" disabled={!!loading} onClick={() => deleteDatabase(db.id, db.db_name)} title={t('Delete')} aria-label={`${t('Delete')} ${db.db_name}`}><Trash2 size={14}/></button>
          </span>
        </div>})}
      </div>
      <p className="hint">{t('Click phpMyAdmin to sign in directly. Token expires after 60s.')}</p>
    </section>;
  }

  function renderSftp() {
    function copySftp(text, field) {
      const doCopy = navigator.clipboard ? navigator.clipboard.writeText(text) : new Promise((resolve, reject) => {
        try { const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); resolve(); } catch(e) { reject(e); }
      });
      doCopy.then(() => { setCopiedField(field); setTimeout(() => setCopiedField(null), 2000); }).catch(() => setError(t('Copy failed.')));
    }
    const atLimit = !sftpLimits.unlimited && Number(sftpLimits.limit || 0) > 0
      && Number(sftpLimits.used || 0) >= Number(sftpLimits.limit || 0);
    const noAllowance = !sftpLimits.unlimited && Number(sftpLimits.limit || 0) <= 0;
    return <section className="section">
      <div className="section-title">
        <div><h2>{t('SFTP accounts')}</h2></div>
        <button className="secondary-light" disabled={!selectedWebsiteId || !!loading} onClick={loadSftpAccounts}><RefreshCw size={14}/>{t('Refresh')}</button>
      </div>

      <div className="info-box">
        <div className="db-created-head">
          <strong>{t('Your own SFTP login')}</strong>
          <button className="mini" onClick={changeOwnSftpPassword}><KeyRound size={13}/>{t('Set password')}</button>
        </div>
        <div className="db-created-grid">
          <label>{t('Username')}</label><span>{currentUser?.sftp_username || currentUser?.username}</span>
          <label>{t('Port')}</label><span>22 (SFTP)</span>
          <label>{t('Reaches')}</label><span>every website on this account</span>
        </div>
        {!currentUser?.sftp_password_set_at && <p className="hint" style={{color:'var(--red)'}}>
          {t('This login still uses your panel password. Anyone who guesses it over SFTP is also in the panel. Set a separate password — your panel password will stop working for SFTP the moment you do.')}
        </p>}
        {currentUser?.sftp_password_set_at && <p className="hint">{t('Separate from your panel password. Changing one does not change the other.')}</p>}
        {ownSftpPassword && <div className="db-created-grid" style={{marginTop:'0.5rem'}}>
          <label>{t('New password')}</label>
          <span><code>{ownSftpPassword}</code> <button className="mini secondary-light" onClick={() => { copySftp(ownSftpPassword, 'own_sftp'); }}>{copiedField === 'own_sftp' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
        </div>}
        {ownSftpPassword && <p className="hint">{t('Shown once. It is not stored anywhere the panel can read back.')}</p>}
      </div>
      <div className="sftp-form">
        <WebsiteSelect />
        <input
          value={newSftpAccount.label}
          onChange={e => setNewSftpAccount(prev => ({ ...prev, label: e.target.value }))}
          placeholder={t('Name, e.g. designer')}
          aria-label={t('SFTP account name')}
        />
        <input
          value={newSftpAccount.password}
          onChange={e => setNewSftpAccount(prev => ({ ...prev, password: e.target.value }))}
          placeholder={t('password (empty = generate)')}
          aria-label={t('SFTP password')}
        />
        <button className="mini secondary-light" title={t('Generate random password')} onClick={() => setNewSftpAccount(prev => ({ ...prev, password: generateRandomPassword() }))}><Dices size={13}/></button>
        <button disabled={!selectedWebsiteId || !!loading || !newSftpAccount.label.trim() || atLimit || noAllowance} onClick={createSftpAccount}><Plus size={14}/>{t('Create account')}</button>
      </div>

      {noAllowance && <p className="hint">{t('Your hosting package does not include SFTP accounts.')}</p>}
      {atLimit && <p className="hint">{t('You have used all {n} SFTP accounts in your package.', { n: sftpLimits.limit })}</p>}
      {!noAllowance && !sftpLimits.unlimited && !atLimit &&
        <p className="hint">{t('{used} of {limit} SFTP accounts used.', { used: sftpLimits.used, limit: sftpLimits.limit })}</p>}

      {createdSftpInfo && <div className="info-box db-created-box">
        <div className="db-created-head"><strong>{t('SFTP account ready')}</strong><button className="mini secondary-light" onClick={() => setCreatedSftpInfo(null)}><X size={13}/></button></div>
        <div className="db-created-grid">
          <label>Host</label><span>{createdSftpInfo.host} <button className="mini secondary-light" title={copiedField === 'sftp_host' ? 'Copied!' : 'Copy'} onClick={() => copySftp(createdSftpInfo.host, 'sftp_host')}>{copiedField === 'sftp_host' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
          <label>{t('Port')}</label><span>{createdSftpInfo.port} (SFTP)</span>
          <label>{t('Username')}</label><span>{createdSftpInfo.username} <button className="mini secondary-light" title={copiedField === 'sftp_user' ? 'Copied!' : 'Copy'} onClick={() => copySftp(createdSftpInfo.username, 'sftp_user')}>{copiedField === 'sftp_user' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span>
          {createdSftpInfo.password && <><label>{t('Password')}</label><span><code>{createdSftpInfo.password}</code> <button className="mini secondary-light" title={copiedField === 'sftp_pass' ? 'Copied!' : 'Copy'} onClick={() => copySftp(createdSftpInfo.password, 'sftp_pass')}>{copiedField === 'sftp_pass' ? <Check size={12} style={{color:'var(--green)'}}/> : <Copy size={12}/>}</button></span></>}
          <label>{t('Folder')}</label><span><code>{createdSftpInfo.path}</code></span>
        </div>
        {createdSftpInfo.password && <p className="hint">{t('This password is shown once. It is not stored anywhere the panel can read it back.')}</p>}
      </div>}

      {selectedWebsiteId && sftpAccounts.length === 0 && !createdSftpInfo &&
        <EmptyState icon={Upload} message={t('No SFTP accounts for this website yet.')} />}

      <div className="table">
        {sftpAccounts.map(account => <div className="row db-row" key={account.id}>
          <span><strong>{account.label}</strong></span>
          <span style={{color:'var(--text-muted)'}}>{account.username}</span>
          <span style={{color:'var(--text-muted)'}}><code>{account.path}</code></span>
          {!account.is_active && <span style={{color:'var(--red)'}}>suspended</span>}
          <button disabled={!!loading} onClick={() => resetSftpPassword(account)}><KeyRound size={14}/>{t('Password')}</button>
          <button className="danger" disabled={!!loading} onClick={() => deleteSftpAccount(account)}><Trash2 size={14}/></button>
        </div>)}
      </div>

      <p className="hint">
        {t('Each account reaches one website and nothing else — not your other sites, and not the server. It signs in over SFTP on port 22 with its own password, which is separate from your panel password.')}
      </p>
    </section>;
  }

  function renderCron() {
    const sitePhpVersion = cronPhpInfo.php_version || currentSite?.php_version || '';
    const sitePhpBinary = cronPhpInfo.php_binary || (sitePhpVersion ? `/usr/bin/php${sitePhpVersion}` : 'php');
    const cronExamples = [
      ['php -q cron.php', 'Path is relative to public_html.'],
      ['php cron.php >/dev/null 2>&1', 'Discard output so cron does not try to mail it.'],
      ['php cron.php >> ../logs/cron.log 2>&1', 'Keep output in a log file inside this website.'],
      ['wp cron event run --due-now', 'WP-CLI, for WordPress sites.'],
    ];
    const cronScheduleValue = cronScheduleCustom || !isPresetSchedule(CRON_SCHEDULE_PRESETS, cronSchedule) ? 'custom' : cronSchedule;
    return <section className="section">
      <div className="section-title">
        <div><h2>{t('Cron manager')}</h2></div>
        <button className="secondary-light" disabled={!selectedWebsiteId || !!loading} onClick={listCron}><RefreshCw size={14}/>{t('Refresh')}</button>
      </div>
      {/* The schedule is picked, not typed; "Custom" keeps the expression for
          whoever wants it. The command starts from a template and stays
          editable. */}
      <div className="cron-builder">
        <label><span>{t('Website')}</span><WebsiteSelect /></label>
        <label><span>{t('Schedule')}</span>
          <select value={cronScheduleValue} onChange={e => {
            if (e.target.value === 'custom') { setCronScheduleCustom(true); return; }
            setCronScheduleCustom(false);
            setCronSchedule(e.target.value);
          }}>
            {CRON_SCHEDULE_PRESETS.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            <option value="custom">{t('Custom...')}</option>
          </select>
        </label>
        {cronScheduleValue === 'custom' && <label><span>{t('Cron expression')}</span><input value={cronSchedule} onChange={e => setCronSchedule(e.target.value)} placeholder="*/15 * * * *" /></label>}
        <label><span>{t('Command template')}</span>
          <select value="" onChange={e => { if (e.target.value) setCronCommand(e.target.value); }}>
            <option value="">{t('Pick a template...')}</option>
            {cronExamples.map(([example, note]) => <option key={example} value={example}>{example} - {t(note)}</option>)}
          </select>
        </label>
        <label className="cron-command"><span>{t('Command')}</span><input value={cronCommand} onChange={e => setCronCommand(e.target.value)} placeholder="php -q cron.php >/dev/null 2>&1" /></label>
        <button className="cron-add" disabled={!selectedWebsiteId || !!loading} onClick={addCron}><Plus size={14}/>{t('Add cron')}</button>
      </div>
      {selectedWebsiteId && <p className="hint">
        {t('Cron runs as')}{' '}<strong>{cronUser || currentSite?.linux_user || 'www-data'}</strong>{' '}{t('for this website.')}{' '}
        {t('Write')} <code>php</code> {t('and BPanel rewrites it to')} <code>{sitePhpBinary}</code>.{' '}
        {t('Only PHP scripts inside public_html and the safe WP-CLI commands are allowed.')}
      </p>}
      <div className="cron-list">
        {selectedWebsiteId && cronItems.length === 0 && <EmptyState icon={Clock} message={t('No cron jobs found for this website.')} />}
        {cronItems.map(item => <div className="cron-item" key={`${item.index}-${item.line}`}>
          <span className="badge">#{item.index}</span>
          <span><strong>{item.schedule}</strong><small>{item.command || item.line}</small></span>
          <button className="mini danger" disabled={!!loading} onClick={() => deleteCron(item.index)}><Trash2 size={13}/></button>
        </div>)}
      </div>
    </section>;
  }

  function renderChmodDialog() {
    const targets = chmodTarget || [];
    if (targets.length === 0) return null;
    const bits = octalToPermissionBits(chmodMode);
    const onlyDirs = targets.every(item => item.is_dir);
    const hasFiles = targets.some(item => !item.is_dir);
    const worldWritable = !!(bits.other & 2);
    const setBit = (classKey, bitValue) => setChmodMode(permissionBitsToOctal({
      ...bits,
      [classKey]: bits[classKey] ^ bitValue,
    }));
    const title = targets.length === 1 ? targets[0].name : `${targets.length} selected items`;
    return <div className="chmod-backdrop" role="presentation" onClick={() => setChmodTarget(null)}>
      <div className="chmod-dialog" role="dialog" aria-modal="true" aria-label={t('Change permissions')} onClick={e => e.stopPropagation()}>
        <div className="chmod-head">
          <div>
            <h3><Lock size={15}/>{t('Permissions')}</h3>
            <p>{title}</p>
          </div>
          <button className="mini secondary-light" onClick={() => setChmodTarget(null)} aria-label={t('Close')}><X size={14}/></button>
        </div>
        <table className="chmod-grid">
          <thead>
            <tr><th scope="col"></th>{PERMISSION_BITS.map(bit => <th scope="col" key={bit.key}>{bit.label}</th>)}</tr>
          </thead>
          <tbody>
            {PERMISSION_CLASSES.map(group => <tr key={group.key}>
              <th scope="row">{group.label}</th>
              {PERMISSION_BITS.map(bit => <td key={bit.key}>
                <input
                  type="checkbox"
                  aria-label={`${group.label} ${bit.label}`}
                  checked={!!(bits[group.key] & bit.value)}
                  onChange={() => setBit(group.key, bit.value)}
                />
              </td>)}
            </tr>)}
          </tbody>
        </table>
        <div className="chmod-value">
          <label>
            <span>{t('Octal')}</span>
            <input value={chmodMode} inputMode="numeric" maxLength={4} onChange={e => setChmodMode(e.target.value.replace(/[^0-7]/g, '').slice(0, 4))} />
          </label>
          <code>{permissionSymbols(chmodMode)}</code>
        </div>
        <div className="chmod-presets">
          {(onlyDirs ? PERMISSION_PRESETS.dir : PERMISSION_PRESETS.file).map(([preset, label]) => <button
            key={preset}
            type="button"
            className={`mini ${chmodMode === preset ? '' : 'secondary-light'}`}
            onClick={() => setChmodMode(preset)}
          >{preset} <small>{t(label)}</small></button>)}
        </div>
        {onlyDirs && <label className="chmod-setgid">
          <input
            type="checkbox"
            checked={bits.special === 2}
            onChange={() => setChmodMode(permissionBitsToOctal({ ...bits, special: bits.special === 2 ? 0 : 2 }))}
          />
          <span>{t('Setgid — new files inside keep the folder\'s group. BPanel sets this on site folders; leave it on unless you know otherwise.')}</span>
        </label>}
        {worldWritable && <p className="chmod-note warn">
          <AlertCircle size={13}/> {hasFiles
            ? t('World-writable: anyone with an account on the server can change these files. Use 755 unless something really needs it.')
            : t('World-writable: anyone with an account on the server can change what is inside these folders. Use 755 unless something really needs it.')}
        </p>}
        <p className="chmod-note">
          {t('Any permission combination is allowed. The setuid and sticky bits are not — setgid on a folder is the only special bit the panel sets.')}
        </p>
        <div className="chmod-actions">
          <button className="secondary-light" disabled={!!loading} onClick={() => setChmodTarget(null)}>{t('Cancel')}</button>
          <button disabled={!!loading} onClick={applyChmod}><Check size={14}/> Apply {chmodMode}</button>
        </div>
      </div>
    </div>;
  }

  function renderFiles() {
    const allSelected = files.length > 0 && selectedFilePaths.length === files.length;
    const selectedArchiveFile = selectedFilePaths.length === 1
      ? files.find(item => item.path === selectedFilePaths[0] && isArchiveFile(item))
      : null;
    const activeFileApp = currentFileApp();
    const targetKey = fileTargetKey();
    const visibleFileJobs = fileJobs
      .filter(job => (job.target_key || `site:${job.website_id}`) === targetKey && job.status !== 'done')
      .slice(0, 4);
    const selectedChmodItems = files.filter(item => selectedFilePaths.includes(item.path));
    return <section className="section">
      {renderChmodDialog()}
      <div className="section-title">
        <div><h2>{t('File manager')}</h2></div>
        <button className="secondary-light" disabled={!hasFileTarget() || !!loading} onClick={() => listFiles(fileListPath)}><RefreshCw size={14}/>{t('Refresh')}</button>
      </div>
      <div className="file-manager">
        <div className="file-panel">
          <div className="file-controls">
            <FileTargetSelect />
            {activeFileApp
              ? <div className="file-meta">
                <span>{t('Application:')}{' '}<strong>{activeFileApp.name}</strong></span>
                <span>{t('Root:')}{' '}<strong>{activeFileApp.directory}{fileListPath ? `/${fileListPath}` : ''}</strong></span>
                {currentUser && !isAdmin && <span>{t('Storage:')}{' '}<strong>{storageUsageText(currentUser)}</strong></span>}
              </div>
              : currentSite && <div className="file-meta">
                <span>{t('Website:')}{' '}<strong>{currentSite.domain}</strong></span>
                <span>{t('Root:')}{' '}<strong>{currentSite.root_path}{fileListPath ? `/${fileListPath}` : ''}</strong></span>
                {currentUser && !isAdmin && <span>{t('Storage:')}{' '}<strong>{storageUsageText(currentUser)}</strong></span>}
              </div>}
            <div className="path-pill breadcrumb-line">
              <button className="crumb" disabled={!hasFileTarget() || fileListPath === ''} onClick={() => listFiles('')}>root</button>
              {fileBreadcrumbs(fileListPath).map(crumb => <button className="crumb" key={crumb.path} onClick={() => listFiles(crumb.path)}>{crumb.label}</button>)}
            </div>
            <div className="file-toolbar">
              <button className="secondary" disabled={!hasFileTarget() || fileListPath === '' || !!loading} onClick={() => listFiles(parentFilePath(fileListPath))}>{t('Up')}</button>
              <button className="secondary" disabled={!hasFileTarget() || !!loading} onClick={makeFileDirectory}><Plus size={14}/>{t('Folder')}</button>
              <button className="secondary" disabled={!hasFileTarget() || !!loading} onClick={makeFile}><FileText size={14}/>{t('File')}</button>
              <label className={`upload-button ${(!hasFileTarget() || !!loading) ? 'disabled' : ''}`}>
                <Upload size={14}/>{t('Upload')}<input type="file" disabled={!hasFileTarget() || !!loading} onChange={e => { uploadSiteFile(e.target.files?.[0]); e.target.value = ''; }} />
              </label>
              <select value={archiveFormat} onChange={e => setArchiveFormat(e.target.value)} disabled={!hasFileTarget() || !!loading}>
                <option value="zip">zip</option>
                <option value="tar.gz">tar.gz</option>
              </select>
              <button className="secondary" disabled={selectedFilePaths.length === 0 || !!loading} onClick={copySelectedFiles}><Copy size={14}/>{t('Copy')}</button>
              <button className="secondary" disabled={selectedFilePaths.length === 0 || !!loading} onClick={moveSelectedFiles}><MoveRight size={14}/>{t('Move')}</button>
              <button className="secondary" disabled={selectedFilePaths.length === 0 || !!loading} onClick={archiveSelectedFiles}><Archive size={14}/>{t('Archive')}</button>
              <button className="secondary" disabled={!selectedArchiveFile || !!loading} onClick={() => extractArchiveFile(selectedArchiveFile.path)}><ArchiveRestore size={14}/>{t('Extract')}</button>
              <button disabled={selectedChmodItems.length === 0 || !!loading} onClick={() => openChmodDialog(selectedChmodItems)}><Lock size={14}/>{t('Permissions')}</button>
              <button className="danger" disabled={selectedFilePaths.length === 0 || !!loading} onClick={deleteSelectedFiles}><Trash2 size={14}/>{t('Delete')}</button>
            </div>
            {visibleFileJobs.length > 0 && <div className="file-job-list">
              {visibleFileJobs.map(job => <div className={`file-job ${job.status}`} key={job.job_id}>
                <Clock size={14}/>
                <span><strong>{job.archive_path?.split('/').pop() || 'Archive'}</strong> {job.status === 'error' ? 'failed' : job.status}</span>
                {job.error && <small>{job.error}</small>}
                <button className="file-job-dismiss" onClick={() => dismissFileJob(job.job_id)} aria-label={t('Dismiss')}><X size={13}/></button>
              </div>)}
            </div>}
          </div>
          <div className="file-list-header">
            <label><input type="checkbox" checked={allSelected} onChange={toggleAllFiles} disabled={files.length === 0} /><span className="sr-only">{t('Select')}</span></label>
            <span>{t('Name')}</span>
            <span>{t('Mode')}</span>
            <span>{t('Size')}</span>
            <span>{t('Modified')}</span>
            <span className="file-list-count">{t('{n} item(s)', { n: files.length })}</span>
          </div>
          <div className="file-list">
            {files.length === 0 && <div className="empty-box">{t('No files in this folder.')}</div>}
            {files.map(item => <div className={`file-item ${selectedFilePaths.includes(item.path) ? 'selected' : ''}`} key={item.path}>
              <input type="checkbox" checked={selectedFilePaths.includes(item.path)} onChange={() => toggleFileSelection(item.path)} />
              <button className="file-name" onClick={() => item.is_dir ? listFiles(item.path) : (isTextEditable(item) ? openFileEditorTab(item.path) : downloadFile(item.path))}>
                {item.is_dir ? <FolderOpen size={16}/> : <FileText size={16}/>} <strong>{item.name}</strong>
              </button>
              <button
                className="file-mode"
                type="button"
                disabled={!!loading}
                title={`Permissions ${item.mode || '---'} (${permissionSymbols(item.mode)}) - click to change`}
                onClick={() => openChmodDialog(item)}
              >{item.mode || '---'}</button>
              <span className="file-size">{item.is_dir ? t('Folder') : formatBytes(item.size)}</span>
              <span className="file-modified" title={formatFileTime(item.modified, true)}>{formatFileTime(item.modified)}</span>
              <div className="file-row-actions">
                {!item.is_dir && <button className="mini secondary-light" disabled={!!loading} onClick={() => downloadFile(item.path)}><Download size={13}/></button>}
                {isArchiveFile(item) && <button className="mini secondary-light" disabled={!!loading} onClick={() => extractArchiveFile(item.path)}><ArchiveRestore size={13}/>{t('Extract')}</button>}
                <button className="mini secondary-light" disabled={!!loading} onClick={() => openChmodDialog(item)}><Lock size={13}/>{t('Perms')}</button>
                <button className="mini secondary-light" disabled={!!loading} onClick={() => renameFileItem(item)}>{t('Rename')}</button>
              </div>
            </div>)}
          </div>
        </div>
      </div>
    </section>;
  }

  function renderBackups() {
    const selectedBackupUser = users.find(user => String(user.id) === String(selectedBackupUserId));
    const jobTitle = job => ({ site_backup: 'Website backup', user_backup: 'Full user backup', sftp_backup: 'SFTP backup' }[job.kind] || 'Backup task');
    const jobDetail = job => job.error || job.remote_file || job.backup_file || job.message || job.status;
    const backupTabs = isAdmin
      ? [
        ['website', 'Backup website', Globe],
        ['user', 'Backup user', Users],
        ['schedule', 'Scheduled backups', Clock],
        ['restore', 'Restore', RotateCcw],
        ['destination', 'Backup Destination', Network],
        ['da-import', 'DA Import', ArchiveRestore],
      ]
      : [['website', 'Backup website', Globe]];
    const activeBackupTab = backupTabs.some(([id]) => id === backupTab) ? backupTab : 'website';
    const visibleBackupJobs = backupJobs.filter(job => job.status !== 'done');

    return <section className="section backups-page">
      <h2>{t('Backups')}</h2>
      <div className="segmented-control backup-tabs" role="tablist" aria-label={t('Backup sections')}>
        {backupTabs.map(([id, label, Icon]) => <button
          key={id}
          type="button"
          role="tab"
          aria-selected={activeBackupTab === id}
          className={activeBackupTab === id ? 'active' : ''}
          onClick={() => setBackupTab(id)}
        ><Icon size={14}/>{t(label)}</button>)}
      </div>
      {visibleBackupJobs.length > 0 && <div className="backup-job-list">
        {visibleBackupJobs.map(job => <div className={`backup-job ${job.status}`} key={job.job_id}>
          <Clock size={14}/>
          <span><strong>{jobTitle(job)}</strong><small>{jobDetail(job)}</small></span>
          <span className={job.status === 'done' ? 'badge ok' : job.status === 'error' ? 'badge bad' : 'badge'}>{job.status}</span>
        </div>)}
      </div>}

      {activeBackupTab === 'website' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup website')}</h3><p className="hint">{t('Backups include website source files and a database SQL export.')}</p></div>
        </div>
        <WebsiteSelect />
        <div className="actions backup-toolbar">
          <button disabled={!selectedWebsiteId || !!loading} onClick={createBackup}><Plus size={14}/>{t('Create backup')}</button>
          <button className="secondary-light" disabled={!selectedWebsiteId || !!loading} onClick={refreshBackupArea}><RefreshCw size={14}/>{t('Refresh')}</button>
          <label className="upload-button secondary">
            <Upload size={14}/>{t('Upload backup')}<input type="file" accept=".tar.gz,application/gzip" onChange={e => { uploadBackup(e.target.files?.[0]); e.target.value = ''; }} />
          </label>
        </div>
        {backups.length === 0 && selectedWebsiteId && <EmptyState icon={Archive} message={t('No backups found for this website.')} />}
        <div className="backup-list">
          {backups.map(file => <div className="backup-item" key={file}>
            <span>{file.split('/').pop()}</span>
            <div className="actions">
              <button className="secondary" disabled={!!loading} onClick={() => downloadBackup(file)}><Download size={14}/>{t('Download')}</button>
              <button className="secondary" disabled={!!loading} onClick={() => restoreBackup(file)}><RotateCcw size={14}/>{t('Restore')}</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteBackup(file)}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'user' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup user')}</h3><p className="hint">{t('Includes the panel user, all owned websites, source files, database dumps, and restore metadata.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={refreshUserBackupArea}><RefreshCw size={14}/>{t('Reload')}</button>
        </div>
        <div className="sftp-run-row user-backup-row backup-run-row">
          <select value={selectedBackupUserId} onChange={e => setSelectedBackupUserId(e.target.value)}>
            <option value="">{t('Select user')}</option>
            {users.map(user => <option key={user.id} value={user.id}>{user.username}</option>)}
          </select>
          <select value={selectedSftpTargetId} onChange={e => setSelectedSftpTargetId(e.target.value)}>
            <option value="">{t('Local only')}</option>
            {sftpTargets.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}
          </select>
          <button disabled={!selectedBackupUserId || !!loading} onClick={createUserBackup}><Archive size={14}/>{t('Create backup')}</button>
        </div>
        {selectedBackupUser && <p className="hint">{t('Current user:')}{' '}<strong>{selectedBackupUser.username}</strong></p>}
        <div className="actions backup-subactions">
          <button className="secondary" disabled={!selectedBackupUserId || !!loading} onClick={() => listUserBackups()}><RefreshCw size={14}/>{t('Refresh list')}</button>
        </div>
        {selectedBackupUserId && userBackups.length === 0 && <EmptyState icon={Archive} message={t('No user backups found.')} />}
        <div className="backup-list">
          {userBackups.map(file => <div className="backup-item" key={file}>
            <span>{file.split('/').pop()}</span>
            <div className="actions">
              <button className="secondary" disabled={!!loading} onClick={() => downloadUserBackup(file)}><Download size={14}/>{t('Download')}</button>
              <button className="secondary" disabled={!!loading} onClick={() => restoreUserBackup(file)}><RotateCcw size={14}/>{t('Restore user')}</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteUserBackup(file)}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>

        <div className="section-title restore-title backup-panel-heading backup-subtitle">
          <div><h3>{t('Restore folder')}</h3><p className="hint">{restoreBackupDir || '/var/backups/bpanel/users/restore'}</p></div>
          <div className="actions">
            <button className="secondary-light" disabled={!!loading} onClick={loadRestoreBackups}><RefreshCw size={14}/>{t('Refresh')}</button>
            <label className="upload-button secondary">
              <Upload size={14}/>{t('Upload backups')}<input type="file" multiple accept=".tar.gz,application/gzip" onChange={e => { uploadUserBackups(e.target.files); e.target.value = ''; }} />
            </label>
          </div>
        </div>
        <div className="backup-list">
          {restoreBackups.map(item => <div className="backup-item" key={item.backup_file}>
            <span>{item.filename || item.backup_file.split('/').pop()}<small>{item.valid ? `${item.source === 'opanel' ? 'opanel · ' : ''}` + t('{user} - {n} website(s)', { user: item.username || t('unknown user'), n: item.websites || 0 }) : (item.error || 'Invalid backup')}</small></span>
            <div className="actions">
              <button className="secondary" disabled={!!loading} onClick={() => downloadUserBackup(item.backup_file)}><Download size={14}/>{t('Download')}</button>
              <button className="secondary" disabled={!!loading || !item.valid} onClick={() => restoreUserBackup(item.backup_file)}><RotateCcw size={14}/>{t('Restore user')}</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteRestoreBackup(item.backup_file)}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>

      </div>}

      {isAdmin && activeBackupTab === 'schedule' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Scheduled backups')}</h3><p className="hint">{t('Run full user backups automatically with optional off-server destination.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={refreshScheduledBackupArea}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {/* Who, then when, where and under what name - each field labelled,
            and one per line on a phone. It was six unlabelled controls in one
            row of 130px cells. */}
        <div className="backup-schedule-builder">
          <div className="schedule-users">
          <label className="schedule-toggle">
            <input type="checkbox" checked={!!newBackupSchedule.all_users} onChange={e => setNewBackupSchedule(prev => ({ ...prev, all_users: e.target.checked }))} />
            <span>{t('All users')}</span>
          </label>
          <select multiple size={6} value={newBackupSchedule.user_ids || []} disabled={!!newBackupSchedule.all_users} onChange={e => setNewBackupSchedule(prev => ({ ...prev, user_ids: Array.from(e.target.selectedOptions, option => option.value) }))}>
            {users.map(user => <option key={user.id} value={String(user.id)}>{user.username}</option>)}
          </select>
          </div>
          <div className="schedule-fields">
          <label><span>{t('Schedule')}</span>
            <select value={backupScheduleCustom || !isPresetSchedule(BACKUP_SCHEDULE_PRESETS, newBackupSchedule.schedule) ? 'custom' : newBackupSchedule.schedule}
              onChange={e => {
                if (e.target.value === 'custom') { setBackupScheduleCustom(true); return; }
                setBackupScheduleCustom(false);
                setNewBackupSchedule(prev => ({ ...prev, schedule: e.target.value }));
              }}>
              {BACKUP_SCHEDULE_PRESETS.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
              <option value="custom">{t('Custom...')}</option>
            </select>
          </label>
          {(backupScheduleCustom || !isPresetSchedule(BACKUP_SCHEDULE_PRESETS, newBackupSchedule.schedule)) && <label><span>{t('Cron expression')}</span>
            <input value={newBackupSchedule.schedule} onChange={e => setNewBackupSchedule(prev => ({ ...prev, schedule: e.target.value }))} placeholder="0 2 * * *" /></label>}
          <label><span>{t('Destination')}</span>
          <select value={newBackupSchedule.target_id} onChange={e => setNewBackupSchedule(prev => ({ ...prev, target_id: e.target.value }))}>
            <option value="">{t('Local only')}</option>
            {sftpTargets.map(target => <option key={target.id} value={target.id}>{target.name} ({target.kind === 's3' ? 'S3' : 'SFTP'})</option>)}
          </select>
          </label>
          <label><span>{t('Stored file name')}</span>
          <select value={newBackupSchedule.name_suffix} aria-label={t('Stored file name')}
            onChange={e => setNewBackupSchedule(prev => ({ ...prev, name_suffix: e.target.value }))}>
            <option value="none">{t('Append: nothing')}</option>
            <option value="day_of_week">{t('Append: day of week')}</option>
            <option value="week_of_month">{t('Append: week of month')}</option>
            <option value="full_date">{t('Append: full date')}</option>
          </select>
          </label>
          <button className="schedule-submit" disabled={(!newBackupSchedule.all_users && (!newBackupSchedule.user_ids || newBackupSchedule.user_ids.length === 0)) || !!loading} onClick={createBackupSchedule}><Clock size={14}/>{t('Schedule')}</button>
          </div>
        </div>
        <p className="hint">{t('The name suffix decides how many copies are kept: nothing keeps one per account, day of week keeps seven, week of month five, and full date one a day until retention removes it.')}</p>
        <div className="backup-list">
          {backupSchedules.map(item => {
            const scheduleTarget = sftpTargets.find(target => target.id === item.target_id);
            return <div className="backup-item" key={item.id}>
              <span>
                {scheduleUserLabel(item)} - {item.schedule}{scheduleTarget ? ` - ${scheduleTarget.name}` : ''}{item.name_suffix && item.name_suffix !== 'full_date' ? ` - ${item.name_suffix.replace(/_/g, ' ')}` : ''}
                {item.last_status === 'running' && <span className="badge"> running</span>}
                <small>{item.last_status}: {item.last_message || 'not run yet'}</small>
              </span>
              <div className="actions schedule-actions">
                <button className="mini secondary-light" disabled={!!loading || item.last_status === 'running'} onClick={() => runBackupScheduleNow(item)}><Play size={14}/>{t('Run now')}</button>
                <button className="mini danger" disabled={!!loading} onClick={() => deleteBackupSchedule(item.id)}><Trash2 size={14}/>{t('Delete')}</button>
              </div>
            </div>;
          })}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'restore' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div>
            <h3>{t('Restore')}</h3>
            <p className="hint">{t('Everything that could be restored, wherever it is. Tick what you want back and restore it in one go.')}</p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={loadRestoreCatalogue}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>

        {!restoreCatalogue.loaded && <p className="hint">{t('Press Refresh to look on this server and in every S3 destination.')}</p>}

        {(restoreCatalogue.errors || []).map(row => <p className="hint alarm" key={row.target_id}>
          {row.target_name}: {row.error}
        </p>)}

        {restoreCatalogue.loaded && <>
          <div className="detail-head">
            <input id="restore-filter" value={restoreFilter} onChange={e => setRestoreFilter(e.target.value)}
              placeholder={t('Filter by account or file name...')} aria-label={t('Filter backups')} />
            <span className="hint">{restorePicks.length} selected</span>
            <button className="danger" disabled={!!loading || restorePicks.length === 0} onClick={restorePicked}>
              <RotateCcw size={14}/>{t('Restore selected')}</button>
          </div>

          {restoreCatalogue.items.length === 0 && <EmptyState icon={ArchiveRestore} message={t('No backups found, here or in any destination.')} />}

          <div className="detail-body restore-list">
            {restoreCatalogue.items
              .filter(item => {
                const needle = restoreFilter.trim().toLowerCase();
                if (!needle) return true;
                return `${item.username} ${item.name} ${item.target_name}`.toLowerCase().includes(needle);
              })
              .map(item => {
                const id = `${item.source}:${item.target_id || 0}:${item.key}`;
                return <label className="restore-row" key={id}>
                  <input type="checkbox" checked={restorePicks.includes(id)} disabled={!!loading}
                    onChange={() => toggleRestorePick(item)} />
                  <span className="restore-main">
                    <strong>{item.username || item.name}</strong>
                    <small>{item.name}</small>
                  </span>
                  <span className={item.source === 's3' ? 'badge' : 'badge ok'}>{item.source === 's3' ? item.target_name : 'This server'}</span>
                  <span className="hint">{formatBytes(item.size)}</span>
                  <span className="hint">{item.modified ? String(item.modified).slice(0, 19).replace('T', ' ') : '--'}</span>
                  {item.valid === false && <span className="badge bad">{item.error || 'not a usable backup'}</span>}
                </label>;
              })}
          </div>
          <p className="hint">
            A file in a bucket is downloaded here first, then restored the same way an uploaded one is.
            Restoring overwrites the account in the archive. One failure does not stop the rest -
            each is reported on its own.
          </p>
        </>}
      </div>}

      {isAdmin && activeBackupTab === 'destination' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup Destination')}</h3><p className="hint">{t('Somewhere off this machine to keep a copy. A backup that lives on the server it backs up is not a backup.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={loadSftpTargets}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        <div className="segmented" role="tablist" aria-label={t('Destination type')}>
          <button className={newSftpTarget.kind === 'sftp' ? 'active' : ''} disabled={!!loading}
            onClick={() => setNewSftpTarget(prev => ({ ...prev, kind: 'sftp' }))}>{t('SFTP server')}</button>
          <button className={newSftpTarget.kind === 's3' ? 'active' : ''} disabled={!!loading}
            onClick={() => setNewSftpTarget(prev => ({ ...prev, kind: 's3' }))}>{t('S3 storage')}</button>
        </div>
        {newSftpTarget.kind === 's3'
          ? <>
              <p className="hint">{t('Works with S3 and anything that speaks its API: Wasabi, Backblaze B2, DigitalOcean Spaces, Cloudflare R2, MinIO. The bucket is checked before the target is saved, so a destination that cannot be reached never gets attached to a schedule.')}</p>
              <div className="sftp-form sftp-target-form">
                <input id="s3-name" value={newSftpTarget.name} onChange={e => setNewSftpTarget(prev => ({ ...prev, name: e.target.value }))} placeholder={t('Target name')} />
                <input id="s3-endpoint" value={newSftpTarget.endpoint} onChange={e => setNewSftpTarget(prev => ({ ...prev, endpoint: e.target.value }))} placeholder="s3.wasabisys.com" />
                <input id="s3-bucket" value={newSftpTarget.bucket} onChange={e => setNewSftpTarget(prev => ({ ...prev, bucket: e.target.value }))} placeholder={t('Bucket')} />
                <input id="s3-region" value={newSftpTarget.region} onChange={e => setNewSftpTarget(prev => ({ ...prev, region: e.target.value }))} placeholder={t('Region (optional)')} />
                <input id="s3-access" value={newSftpTarget.access_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, access_key: e.target.value }))} placeholder={t('Access key')} />
                <input id="s3-secret" value={newSftpTarget.secret_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, secret_key: e.target.value }))} placeholder={t('Secret key')} type="password" />
                <input id="s3-prefix" value={newSftpTarget.prefix} onChange={e => setNewSftpTarget(prev => ({ ...prev, prefix: e.target.value }))} placeholder={t('Prefix, e.g. bpanel/nightly (optional)')} />
                <label className="check-line"><input id="s3-secure" type="checkbox" checked={!!newSftpTarget.secure} onChange={e => setNewSftpTarget(prev => ({ ...prev, secure: e.target.checked }))} /><span>{t('Use HTTPS')}</span></label>
                <button disabled={!!loading || !newSftpTarget.name || !newSftpTarget.endpoint || !newSftpTarget.bucket || !newSftpTarget.access_key || !newSftpTarget.secret_key} onClick={createSftpTarget}><Plus size={14}/>{t('Check and save')}</button>
              </div>
            </>
          : <div className="sftp-form sftp-target-form">
              <input value={newSftpTarget.name} onChange={e => setNewSftpTarget(prev => ({ ...prev, name: e.target.value }))} placeholder={t('Target name')} />
              <input value={newSftpTarget.host} onChange={e => setNewSftpTarget(prev => ({ ...prev, host: e.target.value }))} placeholder="Host" />
              <input value={newSftpTarget.port} onChange={e => setNewSftpTarget(prev => ({ ...prev, port: e.target.value }))} placeholder="22" inputMode="numeric" />
              <input value={newSftpTarget.username} onChange={e => setNewSftpTarget(prev => ({ ...prev, username: e.target.value }))} placeholder={t('Username')} />
              <input value={newSftpTarget.password} onChange={e => setNewSftpTarget(prev => ({ ...prev, password: e.target.value }))} placeholder={t('Password')} type="password" />
              <input value={newSftpTarget.remote_path} onChange={e => setNewSftpTarget(prev => ({ ...prev, remote_path: e.target.value }))} placeholder="/backups/bpanel" />
              <textarea value={newSftpTarget.private_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, private_key: e.target.value }))} placeholder={t('Private key (optional)')} rows={4} />
              <button disabled={!!loading || !newSftpTarget.name || !newSftpTarget.host || !newSftpTarget.username || (!newSftpTarget.password && !newSftpTarget.private_key)} onClick={createSftpTarget}><Plus size={14}/>{t('Save target')}</button>
            </div>}
        {sftpTargets.length === 0 && <EmptyState icon={Network} message={t('No backup destinations found.')} />}
        <div className="backup-list">
          {sftpTargets.map(target => <div className="backup-item" key={target.id}>
            <span>
              <span className="badge">{target.kind === 's3' ? 'S3' : 'SFTP'}</span> {target.name}
              <small>{target.kind === 's3'
                ? `${target.endpoint}/${target.bucket}${target.prefix ? '/' + target.prefix : ''}`
                : `${target.username}@${target.host}:${target.remote_path}`}</small>
            </span>
            <button className="danger" disabled={!!loading} onClick={() => deleteSftpTarget(target.id)}><Trash2 size={14}/></button>
          </div>)}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'da-import' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('DirectAdmin Import')}</h3><p className="hint">{t('Import websites, databases, and users from a DirectAdmin backup archive.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={() => listDaBackups()}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        <div className="da-toolbar">
          <label className="upload-button">
            <Upload size={14}/>{t('Upload DA backup')}<input ref={daFileInputRef} type="file" accept=".tar.zst,.tzst,.tar.gz,.tgz,.tar.bz2,.tbz2,.tar.xz,.txz,.tar" onChange={e => { uploadDaBackup(e.target.files?.[0]); e.target.value = ''; }} />
          </label>
          <label className="da-toggle">
            <input type="checkbox" checked={daReplaceExisting} onChange={e => setDaReplaceExisting(e.target.checked)} />{t('Replace existing users/websites')}</label>
        </div>
        {daReplaceExisting && <p className="hint da-warn">{t('Imports will delete any existing panel user, website, files and databases that share a name with the backup. Leave this off to have conflicting imports stop instead.')}</p>}
        {daBackups.length === 0 && <EmptyState icon={ArchiveRestore} message={t('No DirectAdmin backups uploaded. Upload a DA backup archive to get started.')} />}
        {daBackups.length > 0 && <>
          <div className="da-list-head">
            <label className="da-toggle">
              <input type="checkbox" checked={selectedDaBackups.length === daBackups.length && daBackups.length > 0} onChange={toggleSelectAllDaBackups} />
              {t('Select all ({n})', { n: daBackups.length })}
            </label>
            {selectedDaBackups.length > 0 && <div className="da-actions">
              <button disabled={!!loading} onClick={() => bulkImportDaBackups()} className="primary"><ArchiveRestore size={14}/> {t('Restore selected ({n})', { n: selectedDaBackups.length })}</button>
              <button disabled={!!loading} onClick={bulkDeleteDaBackups} className="danger"><Trash2 size={14}/> {t('Delete selected ({n})', { n: selectedDaBackups.length })}</button>
            </div>}
          </div>
          <div className="backup-list">
            {daBackups.map(file => <div className={`backup-item da-backup-row${selectedDaBackups.includes(file.path) ? ' selected' : ''}`} key={file.path}>
              <label className="da-backup-pick">
                <input type="checkbox" checked={selectedDaBackups.includes(file.path)} onChange={() => toggleDaBackupSelect(file.path)} />
                <span>{file.filename}<small>{(file.size / (1024 * 1024)).toFixed(1)} MB</small></span>
              </label>
              <div className="da-actions">
                <button disabled={!!loading} onClick={() => scanDaBackup(file.path)}><Search size={14}/>{t('Scan')}</button>
                <button disabled={!!loading} onClick={() => importDaBackup(file.path)}><ArchiveRestore size={14}/>{t('Import')}</button>
                <button className="danger" disabled={!!loading} onClick={() => deleteDaBackup(file.path)}><Trash2 size={14}/></button>
              </div>
            </div>)}
          </div>
        </>}

        {daScanResult && <div className="da-scan-result">
          <h4>{t('Scan result:')} {daScanResult.filename}</h4>
          {daScanResult.errors?.length > 0 && <div className="error-list">
            {daScanResult.errors.map((err, i) => <p key={i} className="error-text">{err}</p>)}
          </div>}
          {daScanResult.users?.map((user, i) => <div key={i} className="da-user-block">
            <p className="da-user-head"><Users size={13}/> <strong>{user.username}</strong>{user.email && <small>{user.email}</small>}</p>
            {user.domains?.length > 0 && <div className="da-table-wrap">
              <table className="da-scan-table">
                <thead><tr><th>{t('Domain')}</th><th>{t('Type')}</th><th>{t('Files')}</th><th>{t('Database')}</th><th>{t('SQL dump')}</th><th>{t('Pointers')}</th></tr></thead>
                <tbody>
                  {user.domains.map((d, j) => <tr key={j}>
                    <td><Globe size={12}/> {d.domain}</td>
                    <td>{d.app_type}</td>
                    <td>{d.has_files ? <Check size={13} className="da-yes"/> : <X size={13} className="da-no"/>}</td>
                    <td>{d.db_name || <span className="da-muted">—</span>}</td>
                    <td>{d.has_sql_dump ? <Check size={13} className="da-yes"/> : <X size={13} className="da-no"/>}</td>
                    <td>{d.aliases?.length > 0 ? d.aliases.map(a => `${a.domain} (${a.mode})`).join(', ') : <span className="da-muted">—</span>}</td>
                  </tr>)}
                </tbody>
              </table>
            </div>}
            {user.databases?.length > 0 && <div className="da-table-wrap">
              <p className="hint">{t('Unassigned databases ({n})', { n: user.databases.length })}</p>
              <table className="da-scan-table">
                <thead><tr><th>{t('Database')}</th><th>{t('SQL dump')}</th></tr></thead>
                <tbody>
                  {user.databases.map((db, j) => <tr key={j}>
                    <td><Database size={12}/> {db.db_name}</td>
                    <td>{db.has_sql_dump ? <Check size={13} className="da-yes"/> : <X size={13} className="da-no"/>}</td>
                  </tr>)}
                </tbody>
              </table>
            </div>}
          </div>)}
        </div>}

        {daImportJob && <div className={`backup-job da-job ${daImportJob.status}`}>
          <Clock size={14}/>
          <span><strong>{t('DA Import')}</strong><small>{daImportJob.archive || ''}</small></span>
          <span className={daImportJob.status === 'completed' ? 'badge ok' : daImportJob.status === 'failed' ? 'badge bad' : 'badge'}>{daImportJob.status}</span>
        </div>}
        {daImportJob?.status === 'completed' && daImportJob.result?.summary && <div className="da-scan-result">
          <h4>{t('Import summary')}</h4>
          {daImportJob.result.summary.map((item, i) => <div key={i} className="da-user-block">
            <p className="da-user-head"><strong>{item.username}</strong> <span className="badge ok">{t('{n} domain(s)', { n: item.imported_domains?.length || 0 })}</span> <span className="badge">{t('{n} database(s)', { n: item.databases?.length || 0 })}</span></p>
            {item.aliases?.length > 0 && <p className="hint">{t('Pointers:')} {item.aliases.join(', ')}</p>}
            {item.ssl_enabled_domains?.length > 0 && <p className="hint">{t('SSL enabled:')} {item.ssl_enabled_domains.join(', ')}</p>}
            {item.warnings?.length > 0 && <p className="hint da-warn">{t('Warnings:')} {item.warnings.join('; ')}</p>}
          </div>)}
          {daImportJob.result.credentials && <details className="da-creds-details">
            <summary>{t('Generated credentials (click to show)')}</summary>
            <pre className="da-credentials">{daImportJob.result.credentials.join('\n')}</pre>
          </details>}
        </div>}

        {daBulkImportJob && <div className={`backup-job da-job ${daBulkImportJob.status}`}>
          <Clock size={14}/>
          <span><strong>{t('Bulk restore')}</strong><small>{daBulkImportJob.status === 'running' ? `Processing ${daBulkImportJob.current + 1}/${daBulkImportJob.total}: ${daBulkImportJob.current_archive}` : `${daBulkImportJob.total} backup(s)`}</small></span>
          <span className={daBulkImportJob.status === 'completed' ? 'badge ok' : 'badge'}>{daBulkImportJob.status === 'running' ? `${daBulkImportJob.current}/${daBulkImportJob.total}` : daBulkImportJob.status}</span>
        </div>}
        {daBulkImportJob?.status === 'completed' && daBulkImportJob.results && <div className="da-scan-result">
          <h4>{t('Bulk restore results')}</h4>
          {daBulkImportJob.results.map((item, i) => <div key={i} className={`da-user-block ${item.status === 'completed' ? 'ok' : 'bad'}`}>
            <p className="da-user-head"><strong>{item.archive}</strong> <span className={item.status === 'completed' ? 'badge ok' : 'badge bad'}>{item.status}</span></p>
            {item.result?.summary?.map((s, j) => <p key={j} className="hint">{s.username}: {t('{d} domain(s), {b} db(s)', { d: s.imported_domains?.length || 0, b: s.databases?.length || 0 })}</p>)}
            {item.result?.credentials && <details className="da-creds-details">
              <summary>{t('Credentials')}</summary>
              <pre className="da-credentials">{item.result.credentials.join('\n')}</pre>
            </details>}
            {item.error && <p className="error-text">{item.error}</p>}
          </div>)}
        </div>}
      </div>}
    </section>;
  }

  function renderServices() {
    return <section className="section">
      <div className="section-title">
        <div>
          <h2>{t('Services')}</h2>
          <p className="hint">{t('Auto-refreshes every 10s')}</p>
        </div>
        <button className="secondary" disabled={!!loading} onClick={checkAllServices}><RefreshCw size={15}/>{t('Refresh')}</button>
      </div>
      {/* A running service's Start and a stopped one's Stop are disabled, so
          the enabled button is the obvious next step. */}
      <div className="service-grid">
        {serviceNames.map(name => {
          const state = serviceStates[name];
          const text = `${state?.stdout || ''} ${state?.stderr || ''}`;
          const active = text.includes('active (running)');
          const inactive = text.includes('inactive') || text.includes('failed');
          const canStop = !['bpanel-api', 'redis-server'].includes(name);
          return <div className="service-card" key={name}>
            <div><strong>{name}</strong><span className={active ? 'badge ok' : inactive ? 'badge bad' : 'badge'}>{active ? t('Running') : inactive ? t('Stopped') : '...'}</span></div>
            {isAdmin && <div className="service-actions">
              <button className="secondary" disabled={active} onClick={() => runServiceAction(name, 'start')}><Play size={13}/>{t('Start')}</button>
              {canStop && <button className="danger-light" disabled={inactive} onClick={() => runServiceAction(name, 'stop')}><Square size={13}/>{t('Stop')}</button>}
              <button className="secondary" onClick={() => runServiceAction(name, 'restart')}><RotateCcw size={13}/>{t('Restart')}</button>
            </div>}
          </div>;
        })}
      </div>
    </section>;
  }

  function renderPhpConfig() {
    if (!isAdmin) return <section className="section"><h2>{t('PHP config')}</h2><p className="hint">{t('You do not have permission to edit PHP config.')}</p></section>;
    const notInstalled = sortPhpVersions(phpVersions.supported.filter(v => !phpVersions.installed.includes(v)));
    // The only thing worth an administrator's attention: settings Auto tune
    // would actually change. A row that already matches, or one pinned by the
    // form below (it always wins - PHP reads it last), is not a decision to
    // make, so it does not belong in a list someone has to read every time.
    const tuneChanges = (phpTune?.settings || []).filter(row => row.changes && !row.overridden_value);
    // Every pool on a server is sized from the same CPU/RAM/pool-count budget,
    // so they normally all carry identical numbers - a row per pool (this test
    // box alone has 49) is a wall of the same four numbers repeated. Collapse
    // to "N/N pools run X", and only list the ones that do not match: those are
    // the only ones worth an administrator's attention.
    const poolKey = p => `${p.max_children}|${p.idle_timeout}|${p.max_requests}|${p.request_terminate_timeout}`;
    const poolGroups = {};
    (phpTune?.pools || []).forEach(p => { (poolGroups[poolKey(p)] ||= []).push(p); });
    const [commonPools, ...restPoolGroups] = Object.values(poolGroups).sort((a, b) => b.length - a.length);
    const poolOutliers = restPoolGroups.flat();
    return <section className="section">
      <div className="section-title">
        <div><h2>{t('PHP Configuration')}</h2></div>
      </div>
      <div className="user-create-card">
        <label><span>{t('PHP version')}</span><select value={phpConfig.php_version} onChange={e => { const v = e.target.value; setPhpConfig(prev => ({ ...prev, php_version: v })); loadPhpConfig(v); loadPhpTune(v); }}>
          {phpVersions.installed.map(v => <option key={v} value={v}>PHP {v}</option>)}
        </select></label>
        <label><span>display_errors</span><select value={phpConfig.display_errors} onChange={e => setPhpConfig(prev => ({ ...prev, display_errors: e.target.value }))}>
          <option value="Off">{t('Off (production)')}</option><option value="On">{t('On (debug)')}</option>
        </select></label>
        <label><span>max_execution_time</span><input type="number" value={phpConfig.max_execution_time} onChange={e => setPhpConfig(prev => ({ ...prev, max_execution_time: e.target.value }))} /></label>
        <label><span>max_input_time</span><input type="number" value={phpConfig.max_input_time} onChange={e => setPhpConfig(prev => ({ ...prev, max_input_time: e.target.value }))} /></label>
        <label><span>max_input_vars</span><input type="number" value={phpConfig.max_input_vars} onChange={e => setPhpConfig(prev => ({ ...prev, max_input_vars: e.target.value }))} /></label>
        <label><span>memory_limit</span><input value={phpConfig.memory_limit} onChange={e => setPhpConfig(prev => ({ ...prev, memory_limit: e.target.value }))} placeholder="1024M" /></label>
        <label><span>post_max_size</span><input value={phpConfig.post_max_size} onChange={e => setPhpConfig(prev => ({ ...prev, post_max_size: e.target.value }))} placeholder="1024M" /></label>
        <label><span>upload_max_filesize</span><input value={phpConfig.upload_max_filesize} onChange={e => setPhpConfig(prev => ({ ...prev, upload_max_filesize: e.target.value }))} placeholder="1024M" /></label>
        <button className="secondary-light" disabled={!!loading} onClick={restorePhpDefaults}><RotateCcw size={14}/>{t('Restore defaults')}</button>
        <button disabled={!!loading} onClick={updatePhpConfig}>{t('Save')}</button>
        {phpTune && tuneChanges.length > 0 && <div className="php-tune-diff">
          <strong><AlertCircle size={14}/> {t('Auto tune will change {n} setting(s) for PHP {version}', { n: tuneChanges.length, version: phpTune.php_version })}</strong>
          <span>{tuneChanges.map(row => `${row.key} ${row.current || 'unset'} → ${row.value}`).join(', ')}.</span>
          <button className="mini" disabled={!!loading} onClick={applyPhpTune}>{t('Auto tune PHP')}</button>
        </div>}
        {phpTune && tuneChanges.length === 0 && <div className="notice php-tune-diff">
          <Check size={14}/> PHP {phpTune.php_version} already matches what auto tune recommends for this machine ({phpTune.facts.cpu_count} CPU, {phpTune.facts.total_memory_mb} MB RAM).
        </div>}
      </div>
      {phpTune && <div className="php-tune" style={{ marginTop: 16 }}>
        <div className="php-tune-actions">
          <button disabled={!!loading} onClick={applyPhpTune}><Cpu size={14}/>{t('Auto tune PHP')}</button>
          <button className="secondary-light" disabled={!!loading} onClick={toggleOpcache}>
            {phpTune.opcache_enabled
              ? <><Ban size={14}/> {t('Disable OPcache (PHP {version})', { version: phpTune.php_version })}</>
              : <><Play size={14}/> {t('Enable OPcache (PHP {version})', { version: phpTune.php_version })}</>}
          </button>
        </div>
        {phpTuneApplied && <div className="notice php-tune-result">
          <strong><Check size={14}/> PHP {phpTune.php_version} tuned.</strong>
        </div>}
        {commonPools && <p className="hint">{t('PHP-FPM pools:')} {commonPools.length}/{phpTune.pools.length} running pm.max_children={commonPools[0].max_children || '—'},
          idle {commonPools[0].idle_timeout || '—'}, up to {commonPools[0].max_requests || '—'} requests per process.
          {poolOutliers.length > 0 && ` ${poolOutliers.length} other pool(s) run different settings:`}
        </p>}
        {poolOutliers.length > 0 && <ul className="php-tune-pool-outliers">
          {poolOutliers.map(p => <li key={p.pool}>
            <code>{p.pool}</code>
            <span>pm.max_children={p.max_children || '—'}, idle {p.idle_timeout || '—'}, up to {p.max_requests || '—'} requests</span>
          </li>)}
        </ul>}
      </div>}
      {phpExtensions.versions.length > 0 && <div className="php-ext-card">
        <h3>{t('PHP extensions')}</h3>
        <p className="hint">{t('Installed from the system packages; PHP-FPM reloads so websites can use it straight away. Removing is not offered here, since a website may depend on it.')}</p>
        <div className="php-ext-table" role="table" style={{ '--php-cols': phpExtensions.versions.length }}>
          <div className="php-ext-row php-ext-head" role="row">
            <span role="columnheader">{t('Name')}</span>
            {phpExtensions.versions.map(v => <span role="columnheader" key={v}>PHP {v}</span>)}
            <span role="columnheader" className="php-ext-all" aria-hidden="true"></span>
          </div>
          {phpExtensions.extensions.map(ext => {
            const missing = phpExtensions.versions.filter(v => ext.versions[v] === 'available');
            return <div className="php-ext-row" role="row" key={ext.name}>
              <code role="cell">{ext.name}</code>
              {phpExtensions.versions.map(v => {
                const state = ext.versions[v];
                return <span role="cell" key={v}>
                  {(state === 'installed' || state === 'builtin') && <span className="badge ok" title={state === 'builtin' ? t('Built into PHP') : t('Installed')}><Check size={12}/></span>}
                  {state === 'available' && <button className="mini secondary" disabled={!!loading} aria-label={t('Install')} title={`php${v}-${ext.name}`} onClick={() => installPhpExtension(ext.name, [v])}><Plus size={12}/><span className="php-ext-install-label">{t('Install')}</span></button>}
                  {state === 'unavailable' && <span className="php-ext-none" title={t('Not in the package repository for this version')}>—</span>}
                </span>;
              })}
              <span role="cell" className="php-ext-all">
                {missing.length > 1 && <button className="mini secondary" disabled={!!loading} onClick={() => installPhpExtension(ext.name, missing)}>{t('All versions')}</button>}
              </span>
            </div>;
          })}
        </div>
      </div>}
      {notInstalled.length > 0 && <div className="user-create-card" style={{ marginTop: 16 }}>
        <h3>{t('Install PHP')}</h3>
        <div className="php-install-grid">
          {notInstalled.map(v => <button key={v} disabled={!!loading} onClick={() => installPhpVersion(v)}>+ PHP {v}</button>)}
        </div>
      </div>}
    </section>;
  }

  function renderFirewall() {
    if (!isAdmin) return <section className="section"><h2>{t('Firewall')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const firewallText = firewallStatus?.stdout || firewallStatus?.stderr || 'Press Refresh to load the status.';
    const blocklistText = firewallBlocklists?.stdout || firewallBlocklists?.stderr || 'Blocklist status not loaded yet.';
    const blocklistUrls = parseFirewallBlocklistUrls(blocklistText);
    const allRules = firewallStatus?.rules || [];
    const userRules = allRules.filter(rule => !rule.protected);
    const panelRules = allRules.filter(rule => rule.protected);
    const f2bInstalled = addons.items.find(item => item.slug === 'fail2ban')?.installed;
    // The helper prints `Status: enabled|disabled` as its first line. Read that
    // rather than pattern-matching the whole dump, which carries the word
    // "disabled" in other contexts too.
    const statusLine = (firewallText.split('\n').find(line => line.startsWith('Status:')) || '').toLowerCase();
    const enabled = statusLine.includes('enabled');
    const stateKnown = statusLine !== '';
    const keep = value => !fwFilter.trim() || String(value).toLowerCase().includes(fwFilter.trim().toLowerCase());
    const shownRules = userRules.filter(rule => keep(`${rule.id} ${rule.action} ${rule.to} ${rule.from}`));
    const shownUrls = blocklistUrls.filter(keep);
    const shownBanned = (f2bBanned.items || []).filter(keep);

    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Firewall')}</h2>
            <p className="hint">iptables + ipset. SSH, the panel port and 80/443/465/587 are always kept open.</p>
          </div>
          <div className="actions">
            <button className="secondary-light" disabled={!!loading} onClick={loadFirewall}><RefreshCw size={14}/>{t('Refresh')}</button>
            {/* One of these, never both: the other is not an action available now. */}
            {stateKnown && (enabled
              ? <button className="danger" disabled={!!loading} onClick={disableFirewall}>{t('Turn off')}</button>
              : <button disabled={!!loading} onClick={enableFirewall}><Shield size={14}/>{t('Turn on')}</button>)}
            {enabled && <button className="secondary" disabled={!!loading} onClick={reloadFirewall}>{t('Reload')}</button>}
          </div>
        </div>

        <div className="chip-row">
          <span className={enabled ? 'badge ok' : 'badge warn'}>{enabled ? 'On' : 'Off'}</span>
          {panelRules.length > 0 && <span className="hint">protected ports: {panelRules.map(rule => rule.to).join(', ')}</span>}
        </div>

        <div className="detail-tabs">
          <button className={fwDetail === 'rules' ? 'chip on' : 'chip'} disabled={!!loading}
            onClick={() => openFwDetail('rules')}>{t('Your rules')}{' '}<b>{userRules.length}</b></button>
          <button className={fwDetail === 'urls' ? 'chip on' : 'chip'} disabled={!!loading}
            onClick={() => openFwDetail('urls')}>{t('Blocklist URL')}{' '}<b>{blocklistUrls.length}</b></button>
          <button className={fwDetail === 'raw' ? 'chip on' : 'chip'} disabled={!!loading}
            onClick={() => openFwDetail('raw')}>{t('Raw status')}</button>
        </div>

        {fwDetail && <div className="detail-panel">
          {fwDetail !== 'raw' && <div className="detail-head">
            <input id="fw-filter" value={fwFilter} onChange={e => setFwFilter(e.target.value)}
              placeholder={t('Filter this list...')} aria-label={t('Filter list')} />
            <button className="secondary-light" onClick={() => setFwDetail(null)}><X size={14}/>{t('Close')}</button>
          </div>}

          {fwDetail === 'rules' && <div className="detail-body">
            {shownRules.length === 0 && <p className="hint">{userRules.length === 0
              ? 'No rules yet. Only the protected ports are open.'
              : 'No rules match that filter.'}</p>}
            {shownRules.map(rule => <div className="firewall-rule" key={rule.id}>
              <span>
                <strong>#{rule.id}</strong>{' '}
                <span className={rule.action === 'DENY' ? 'badge danger' : 'badge ok'}>{rule.action}</span>{' '}
                {rule.to} from {rule.from}
              </span>
              <div className="firewall-rule-actions">
                <button className="danger" disabled={!!loading} onClick={() => deleteFirewallRule(rule.id)}><Trash2 size={14}/>{t('Delete')}</button>
              </div>
            </div>)}
          </div>}

          {fwDetail === 'urls' && <div className="detail-body">
            <div className="firewall-form firewall-blocklist-form">
              <label><span>TXT URL</span><input id="fw-blocklist-url" value={firewallBlocklistUrl}
                onChange={e => setFirewallBlocklistUrl(e.target.value)} placeholder="https://example.com/blocklist.txt" /></label>
              <button disabled={!!loading || !firewallBlocklistUrl.trim()} onClick={addFirewallBlocklistUrl}><Plus size={14}/>{t('Add')}</button>
              <button className="secondary-light" disabled={!!loading} onClick={updateFirewallBlocklistsNow}><RefreshCw size={14}/>{t('Update now')}</button>
            </div>
            <p className="hint">{t('Fetched daily at 01:00 into an ipset, so even a million-entry list costs one kernel lookup per packet.')}</p>
            {shownUrls.length === 0 && <p className="hint">{t('No URLs yet.')}</p>}
            {shownUrls.map(url => <div className="firewall-rule" key={url}>
              <span className="wrap-any">{url}</span>
              <div className="firewall-rule-actions"><button className="danger" disabled={!!loading} onClick={() => deleteFirewallBlocklistUrl(url)}><Trash2 size={14}/>{t('Delete')}</button></div>
            </div>)}
          </div>}

          {fwDetail === 'raw' && <div className="detail-body">
            <div className="detail-head">
              <strong>{t('Firewall status')}</strong>
              <button className="secondary-light" onClick={() => setFwDetail(null)}><X size={14}/>{t('Close')}</button>
            </div>
            <pre>{firewallText}</pre>
            <strong>{t('Blocklist status')}</strong>
            <pre>{blocklistText}</pre>
            <div className="firewall-delete-inline">
              <label><span>{t('Delete rule #')}</span><input id="fw-delete-number" value={firewallDeleteNumber}
                onChange={e => setFirewallDeleteNumber(e.target.value)} placeholder="12" inputMode="numeric" /></label>
              <button className="danger" disabled={!!loading || !firewallDeleteNumber} onClick={() => deleteFirewallRule()}>{t('Delete')}</button>
            </div>
          </div>}
        </div>}

        <div className="firewall-form rule-form">
          <label><span>{t('Action')}</span>
            <select id="fw-action" value={fwAction} onChange={e => setFwAction(e.target.value)}>
              <option value="block">{t('Block IP')}</option>
              <option value="allow">{t('Allow IP')}</option>
              <option value="port">{t('Open port')}</option>
            </select>
          </label>
          {fwAction === 'block' && <label><span>{t('IP / CIDR')}</span><input id="fw-block-ip" value={firewallBlockIp}
            onChange={e => setFirewallBlockIp(e.target.value)} placeholder="5.6.7.8" /></label>}
          {fwAction === 'allow' && <label><span>{t('IP / CIDR')}</span><input id="fw-allow-ip" value={firewallAllowIp}
            onChange={e => setFirewallAllowIp(e.target.value)} placeholder="1.2.3.4" /></label>}
          <label><span>Port{fwAction === 'port' ? '' : ' (optional)'}</span>
            {fwAction === 'block' && <input id="fw-block-port" value={firewallBlockPort} onChange={e => setFirewallBlockPort(e.target.value)} placeholder={t('All ports')} inputMode="numeric" />}
            {fwAction === 'allow' && <input id="fw-allow-port" value={firewallAllowPort} onChange={e => setFirewallAllowPort(e.target.value)} placeholder="22" inputMode="numeric" />}
            {fwAction === 'port' && <input id="fw-port" value={firewallPort} onChange={e => setFirewallPort(e.target.value)} placeholder="80" inputMode="numeric" />}
          </label>
          <label><span>{t('Protocol')}</span>
            {fwAction === 'block' && <select id="fw-block-proto" value={firewallBlockProtocol} onChange={e => setFirewallBlockProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>}
            {fwAction === 'allow' && <select id="fw-allow-proto" value={firewallAllowProtocol} onChange={e => setFirewallAllowProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>}
            {fwAction === 'port' && <select id="fw-proto" value={firewallProtocol} onChange={e => setFirewallProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>}
          </label>
          <button className={fwAction === 'block' ? 'danger' : ''} disabled={!!loading
            || (fwAction === 'block' && !firewallBlockIp)
            || (fwAction === 'allow' && !firewallAllowIp)
            || (fwAction === 'port' && !firewallPort)} onClick={submitFirewallRule}>
            {fwAction === 'block' ? 'Block' : fwAction === 'allow' ? 'Allow' : 'Open port'}
          </button>
        </div>
      </section>

      {f2bInstalled && <section className="section">
        <div className="section-title">
          <div>
            <h2>Fail2ban</h2>
            <p className="hint">{t('Five failed attempts within an hour bans an address for an hour, and longer each time it comes back, up to a week. The server never bans its own addresses.')}</p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={loadFail2ban}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {!f2b && <p className="hint">{t('Status not loaded. Press Refresh.')}</p>}
        {f2b && <>
          {f2b.warning && <p className="hint alarm">{f2b.warning}</p>}
          <div className="chip-row">
            <span className={f2b.running ? 'badge ok' : 'badge warn'}>{f2b.running ? 'Running' : 'Not running'}</span>
            <span className={f2b.bans_reach_kernel ? 'badge ok' : 'badge warn'}>{f2b.bans_reach_kernel ? 'Bans take effect' : 'Bans NOT reaching iptables'}</span>
            <span className={f2b.filter_sees_journal ? 'badge ok' : 'badge warn'}>{f2b.filter_sees_journal ? 'Reading the log' : 'Seeing NO log'}</span>
            <span className="hint">{f2b.ssh_unit || '—'} · {f2b.banaction || '—'} · {t('{n} failures seen', { n: f2b.total_failed ?? 0 })}</span>
          </div>
          <div className="detail-tabs">
            <button className={fwDetail === 'banned' ? 'chip on' : 'chip'} disabled={!!loading}
              onClick={() => openFwDetail('banned')}>{t('Banned addresses')}{' '}<b>{f2b.banned ?? 0}</b></button>
          </div>
          {fwDetail === 'banned' && <div className="detail-panel">
            <div className="detail-head">
              <input id="f2b-filter" value={fwFilter} onChange={e => setFwFilter(e.target.value)}
                placeholder={t('Filter by address...')} aria-label={t('Filter banned addresses')} />
              <button className="secondary-light" onClick={() => setFwDetail(null)}><X size={14}/>{t('Close')}</button>
            </div>
            <div className="detail-body">
              {shownBanned.length === 0 && <p className="hint">{f2bBanned.total === 0
                ? 'No addresses are banned right now.' : 'No addresses match that filter.'}</p>}
              {shownBanned.map(ip => <div className="firewall-rule" key={ip}>
                <span><code>{ip}</code></span>
                <div className="firewall-rule-actions">
                  <button className="danger" disabled={!!loading} onClick={() => unbanAddress(ip)}>{t('Unban')}</button>
                </div>
              </div>)}
            </div>
            {f2bBanned.total > f2bBanned.limit && <div className="detail-foot">
              <button className="secondary-light" disabled={!!loading || f2bBanned.offset === 0}
                onClick={() => loadBannedPage(Math.max(0, f2bBanned.offset - f2bBanned.limit))}>{t('Previous')}</button>
              <span className="hint">{f2bBanned.offset + 1}–{Math.min(f2bBanned.offset + f2bBanned.limit, f2bBanned.total)} trong {f2bBanned.total}</span>
              <button className="secondary-light" disabled={!!loading || f2bBanned.offset + f2bBanned.limit >= f2bBanned.total}
                onClick={() => loadBannedPage(f2bBanned.offset + f2bBanned.limit)}>{t('Next')}</button>
            </div>}
          </div>}
        </>}
      </section>}
    </>;
  }

  function renderWaf() {
    const statusText = wafRules.status?.stdout || wafRules.status?.stderr || 'Click Refresh to load WAF status.';
    // The effective list, not the site's own: a site with nothing of its own
    // still enforces the global list, and reporting "No bots" for it was a lie.
    const rowFor = id => botBlocks?.websites?.find(w => w.website_id === id);
    const botCountFor = id => (rowFor(id)?.effective_blocked_bots || []).length;
    const ownCountFor = id => (rowFor(id)?.blocked_bots || []).length;
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>WAF</h2>
            <p className="hint">{isAdmin
              ? t('Protection for each website. Open one to set its rules, flood limit and blocked bots.')
              : t('Protection for your websites. Open one to set its rules and blocked bots.')}</p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={() => { loadBotBlocks(); if (isAdmin) { loadWafRules(); loadCrs(); } }}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {/* Folded. This is systemctl and timer output - the first thing on the
            page was eleven lines of paths and a timer table, above the
            controls somebody came to use. What the WAF is actually doing is
            said by the badges below in words; this is here for the operator
            who is diagnosing, and they know to open it. */}
        {isAdmin && <details className="info-box firewall-status output-details">
          <summary><strong>{t('Status')}</strong><span>{t('Module, rule files and timers')}</span></summary>
          <pre>{statusText}</pre>
        </details>}
      </section>

      {isAdmin && <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('OWASP Core Rule Set')}</h2>
            <p className="hint">{t('Inspects each request for SQL injection, XSS and similar attacks. Each website turns it on from its own page.')}</p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={loadCrs}><RefreshCw size={14}/>{t('Check')}</button>
        </div>
        {!crs && <p className="hint">{t('Click Check to read the current state.')}</p>}
        {crs && <>
          <div className="waf-overview-badges" style={{ marginBottom: 12 }}>
            <span className={crs.mode === 'block' ? 'badge ok' : 'badge'}>
              {crs.mode === 'off' ? t('Off') : (crs.mode === 'detect' ? t('Detect only') : t('Blocking'))}
            </span>
            <span className={crs.installed ? 'badge ok' : 'badge'}>
              {crs.installed ? t('{n} rule file(s) installed', { n: crs.rule_files }) : t('Not installed')}
            </span>
            <span className="badge">{t('{n} website(s) with CRS on', { n: crs.sites_opted_in ?? 0 })}</span>
            {/* The memory essay is gone; a low-RAM warning is what is left of
                it, because every site that turns CRS on carries it (~50 MB). */}
            {(crs.ram_available_mb || 0) > 0 && crs.ram_available_mb < 1024 && <span className="badge danger">
              {t('{n} MB RAM free', { n: crs.ram_available_mb })}
            </span>}
          </div>
          <div className="segmented-control">
            {[['off', 'Off'], ['detect', 'Detect only'], ['block', 'Block']].map(([value, label]) => (
              <button
                key={value}
                className={crs.mode === value ? 'active' : ''}
                disabled={!!loading || crs.mode === value}
                onClick={() => saveCrsMode(value)}
              >{t(label)}</button>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            {crs.mode === 'off' && t('Off: requests are not inspected.')}
            {crs.mode === 'detect' && t('Detect only: attacks are logged, nothing is blocked.')}
            {crs.mode === 'block' && t('Block: attacks are refused on websites with CRS on.')}
          </p>
          {crs.mode !== 'off' && crs.panel_mode !== crs.mode && (
            <p className="hint">{t('Panel setting says "{panel}" but the server reports "{server}".', { panel: crs.panel_mode, server: crs.mode })}</p>
          )}
        </>}
      </section>}

      <section className="section">
        <div className="section-title"><h2>{t('Websites')}</h2></div>
        {websites.length === 0 && <EmptyState icon={Globe} message={t('No websites yet.')} />}
        <div className="table waf-overview-list">
          {websites.map(site => {
            const bots = botCountFor(site.id);
            // No CRS here: "WAF on" beside "CRS block" read as two things to
            // worry about. CRS is switched on the site's own page.
            return <div className="waf-overview-row" key={site.id}>
              <span className="waf-overview-domain"><strong>{site.domain}</strong></span>
              <div className="waf-overview-badges">
                <span className={site.waf_enabled ? 'badge ok' : 'badge'}>{site.waf_enabled ? t('WAF on') : t('WAF off')}</span>
                <span className={site.http_flood_enabled ? 'badge ok' : 'badge'}>{site.http_flood_enabled ? t('Flood on') : t('Flood off')}</span>
                <span
                  className={bots > 0 ? 'badge ok' : 'badge'}
                  title={ownCountFor(site.id) > 0 ? `${ownCountFor(site.id)} set on this site, the rest from the global list` : 'All from the global list'}
                >{bots > 0 ? t('{n} bot(s)', { n: bots }) : t('No bots')}</span>
              </div>
              <button className="secondary" disabled={!!loading} onClick={() => openWafSite(site.id)}><SettingsIcon size={14}/>{t('Configure')}</button>
            </div>;
          })}
        </div>
      </section>

      {isAdmin && <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Global bad bots')}</h2>
            <p className="hint">
              Blocked on every website on this server. A site can add more of its own from its page.
              {globalBots.length > 0 ? ` Currently ${globalBots.length} bot(s).` : ' Nothing blocked globally yet.'}
            </p>
          </div>
          <button disabled={!!loading} onClick={() => setBulkBotOpen(open => !open)}>{bulkBotOpen ? 'Hide' : 'Edit'}</button>
        </div>

        {bulkBotOpen && <div className="global-bots">
          <div className="global-bots-add">
            <input
              value={newBotName}
              placeholder={t('Add one bot, e.g. Amazonbot')}
              onChange={e => setNewBotName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { addGlobalBots(newBotName); setNewBotName(''); } }}
            />
            <button type="button" disabled={!newBotName.trim()} onClick={() => { addGlobalBots(newBotName); setNewBotName(''); }}>
              <Plus size={14}/>{t('Add')}</button>
            <input
              className="global-bots-filter"
              value={globalBotFilter}
              placeholder={t('Filter the list')}
              onChange={e => setGlobalBotFilter(e.target.value)}
            />
          </div>

          <div className="global-bots-list">
            {globalBots.length === 0 && <p className="hint">{t('No bots yet. Add one above, or paste a list below.')}</p>}
            {globalBots
              .filter(name => !globalBotFilter.trim() || name.toLowerCase().includes(globalBotFilter.trim().toLowerCase()))
              .map(name => <span className="global-bot-chip" key={name}>
                <code>{name}</code>
                <button
                  type="button"
                  title={`Remove ${name}`}
                  onClick={() => setGlobalBots(prev => prev.filter(n => n !== name))}
                ><X size={12}/></button>
              </span>)}
          </div>

          <details className="global-bots-paste">
            <summary>{t('Paste a list')}</summary>
            <textarea
              className="code-editor"
              rows={6}
              spellCheck={false}
              value={globalBotPaste}
              onChange={e => setGlobalBotPaste(e.target.value)}
              placeholder={'AhrefsBot\nSemrushBot\nMJ12bot'}
            />
            <button type="button" disabled={!globalBotPaste.trim()} onClick={() => { addGlobalBots(globalBotPaste); setGlobalBotPaste(''); }}>
              <Plus size={14}/>{t('Add to list')}</button>
          </details>

          <div className="global-bots-actions">
            <button disabled={!!loading} onClick={() => saveGlobalBots(globalBots)}>
              <Shield size={14}/> {t('Save and apply to all {n} website(s)', { n: websites.length })}
            </button>
            <button
              className="secondary-light"
              disabled={!!loading}
              onClick={() => setGlobalBots(botBlocks?.global_blocked_bots || [])}
            >{t('Reset')}</button>
            <span className="hint">
              {globalBots.length} bot(s)
              {botBlocks?.max_bots ? ` - max ${botBlocks.max_bots}` : ''}
              {JSON.stringify(globalBots) !== JSON.stringify(botBlocks?.global_blocked_bots || []) ? ' - unsaved changes' : ''}
            </span>
          </div>
        </div>}
      </section>}
    </>;
  }

  function renderWafSite() {
    const selectedSite = websites.find(site => String(site.id) === String(selectedWafWebsiteId));
    const groupedRules = (wafSiteConfig?.default_rules || wafRules.default_rule_definitions || []).reduce((groups, rule) => {
      const category = rule.category || 'General';
      groups[category] = groups[category] || [];
      groups[category].push(rule);
      return groups;
    }, {});
    const siteBotNames = siteBotText.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
    const siteBotUnique = new Set(siteBotNames.map(s => s.toLowerCase()));
    return <>
      <section className="section">
        <div className="section-title waf-site-header">
          <div>
            <h2>{wafSiteConfig?.domain || selectedSite?.domain || 'Website'}</h2>
            <p className="hint">{t('WAF rules, flood limits and blocked bots for this website.')}</p>
          </div>
          <div className="waf-site-header-actions">
            <select value={selectedWafWebsiteId} onChange={e => loadWebsiteWafConfig(e.target.value)}>
              {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
            </select>
            <button className="secondary-light" onClick={() => navigateToPage('waf')}><ArrowLeft size={14}/>{t('All websites')}</button>
          </div>
        </div>
        {/* One row per protection: what it does, its state, its switch. CRS
            is here and not in the list - whether a site carries it, and its
            memory, is for whoever manages this site to decide. */}
        <div className="waf-switches">
          <div className="waf-switch-row">
            <div className="waf-switch-text">
              <strong>WAF</strong>
              <span className="hint">{t('Blocks known bad paths.')}</span>
            </div>
            <span className={selectedSite?.waf_enabled ? 'badge ok' : 'badge'}>{selectedSite?.waf_enabled ? t('WAF on') : t('WAF off')}</span>
            <button
              className={selectedSite?.waf_enabled ? 'secondary' : ''}
              disabled={!selectedWafWebsiteId || !!loading}
              onClick={() => selectedSite && toggleWebsiteWaf(selectedSite)}
            ><Shield size={14}/>{selectedSite?.waf_enabled ? t('Turn WAF off') : t('Turn WAF on')}</button>
          </div>
          {wafSiteConfig && <div className="waf-switch-row">
            <div className="waf-switch-text">
              <strong>OWASP CRS</strong>
              <span className="hint">
                {t('Inspects each request for SQL injection, XSS and similar attacks. Uses about {n} MB of server RAM.', { n: crs?.rss_mb_per_site || 50 })}
                {wafSiteConfig.crs_enabled && !selectedSite?.waf_enabled ? ' ' + t('It loads when the WAF is on.') : ''}
                {wafSiteConfig.crs_enabled && selectedSite?.waf_enabled && wafSiteConfig.crs_mode === 'off' ? ' ' + t('CRS is off for the whole server, so nothing is loaded yet.') : ''}
                {wafSiteConfig?.crs_active && wafSiteConfig.crs_mode === 'detect' ? ' ' + t('Detect only: attacks are logged, nothing is blocked.') : ''}
                {wafSiteConfig?.crs_active && wafSiteConfig.may_edit_custom_rules ? ' ' + t('Add SecRuleRemoveById <id> to the custom rules below to excuse this site from one rule.') : ''}
              </span>
            </div>
            <span className={wafSiteConfig?.crs_active ? 'badge ok' : 'badge'}>{wafSiteConfig.crs_enabled ? t('CRS on') : t('CRS off')}</span>
            <button
              className={wafSiteConfig.crs_enabled ? 'secondary' : ''}
              disabled={!!loading || (!wafSiteConfig.crs_enabled && !selectedSite?.waf_enabled)}
              title={!wafSiteConfig.crs_enabled && !selectedSite?.waf_enabled ? t('Turn the WAF on first') : ''}
              onClick={() => toggleSiteCrs(wafSiteConfig)}
            ><Shield size={14}/>{wafSiteConfig.crs_enabled ? t('Turn CRS off') : t('Turn CRS on')}</button>
          </div>}
        </div>
      </section>

      {!wafSiteConfig && websites.length === 0 && <section className="section"><EmptyState icon={Globe} message={t('No websites yet.')} /></section>}

      {wafSiteConfig && <section className="section bot-block-panel">
        <div className="section-title">
          <div>
            <h2>{t('Blocked bots')}</h2>
            <p className="hint">{t('One name per line, matched anywhere in User-Agent. Matched literally, so')}{' '}<code>bingbot/2.0</code> will not also match <code>bingbotX2Y0</code>. Blocked requests get 403 before WAF and rate limiting run.</p>
          </div>
        </div>
        <textarea
          className="code-editor"
          value={siteBotText}
          onChange={e => setSiteBotText(e.target.value)}
          rows={10}
          spellCheck={false}
          placeholder={'AhrefsBot\nSemrushBot\nMJ12bot'}
        />
        <p className="hint">
          {`${siteBotUnique.size} bot(s)`}
          {siteBotNames.length !== siteBotUnique.size ? ` (${siteBotNames.length - siteBotUnique.size} duplicate(s) will be dropped)` : ''}
          {botBlocks?.max_bots ? ` - max ${botBlocks.max_bots}` : ''}
        </p>
        <div className="actions">
          <button disabled={!!loading} onClick={saveSiteBots}><Shield size={14}/>{t('Save blocked bots')}</button>
          <button className="secondary-light" disabled={!!loading || siteBotNames.length === 0} onClick={() => setSiteBotText('')}>{t('Clear list')}</button>
        </div>
      </section>}

      {wafSiteConfig && <section className="section http-flood-panel">
        <div className="section-title">
          <h2>{t('HTTP Flood')}</h2>
          <span className={httpFloodForm.http_flood_enabled ? 'badge ok' : 'badge'}>{httpFloodForm.http_flood_enabled ? 'Enabled' : 'Disabled'}</span>
        </div>
        <label className="schedule-toggle http-flood-toggle">
          <input type="checkbox" checked={!!httpFloodForm.http_flood_enabled} onChange={e => setHttpFloodForm(prev => ({ ...prev, http_flood_enabled: e.target.checked }))} />{t('Enabled')}</label>
        <div className="http-flood-grid">
          <label><span>{t('Requests')}</span><input type="number" min="1" max="100000" value={httpFloodForm.access_limit_requests} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_requests: e.target.value }))} /></label>
          <label><span>{t('Window (sec)')}</span><input type="number" min="1" max="3600" value={httpFloodForm.access_limit_window} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_window: e.target.value }))} /></label>
          <label><span>{t('Burst')}</span><input type="number" min="0" max="100000" value={httpFloodForm.access_limit_burst} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_burst: e.target.value }))} /></label>
          <label><span>{t('Connections/IP')}</span><input type="number" min="1" max="10000" value={httpFloodForm.connection_limit} onChange={e => setHttpFloodForm(prev => ({ ...prev, connection_limit: e.target.value }))} /></label>
          <button disabled={!!loading} onClick={saveWebsiteHttpFlood}><Shield size={14}/>{t('Save HTTP Flood')}</button>
        </div>
      </section>}

      {wafSiteConfig && <section className="section waf-rules-grid">
        <div className="waf-rule-panel">
          <div className="section-title"><h2>{t('Default rules')}</h2></div>
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
          <div className="section-title"><h2>{t('Custom rules')}</h2></div>
          <textarea
            className="code-editor"
            value={wafCustomRules}
            onChange={e => setWafCustomRules(e.target.value)}
            rows={14}
            spellCheck={false}
            placeholder="SecRule ..."
            readOnly={wafSiteConfig.may_edit_custom_rules === false}
          />
          <p className="hint">
            {wafSiteConfig.may_edit_custom_rules === false
              ? 'Custom rules are arbitrary ModSecurity directives, so only an administrator can change them. Ask your provider if you need a rule added or excluded.'
              : `Saved into ${wafSiteConfig.rules_file}`}
          </p>
          <div className="actions"><button disabled={!!loading} onClick={saveWebsiteWafRules}>{t('Save website WAF rules')}</button></div>
        </div>
      </section>}
    </>;
  }

  function renderWafAccessLogs() {
    const rows = wafAccessLogs.items || [];
    const selectedSite = websites.find(site => String(site.id) === String(wafAccessLogFilters.websiteId));
    const entryLabel = wafAccessLogs.total >= 1000 ? `${(wafAccessLogs.total / 1000).toFixed(1)}k entries` : `${wafAccessLogs.total || 0} entries`;
    return <section className="section access-logs-section">
      <div className="section-title access-logs-title">
        <div><h2>{t('Access Logs')}</h2><p className="hint">{t('Protected Nginx traffic across all websites.')}</p></div>
        <div className="access-log-icon-actions">
          <button className="secondary-light icon-button" disabled={!!loading} onClick={() => loadWafAccessLogs(wafAccessLogFilters, true)} aria-label={t('Refresh access logs')} title={t('Refresh access logs')}><RefreshCw size={15}/></button>
          <button className="secondary-light icon-button" onClick={() => selectedSite && window.open(websiteUrl(selectedSite), '_blank', 'noopener,noreferrer')} disabled={!selectedSite} aria-label={t('Open website')} title={t('Open website')}><ExternalLink size={15}/></button>
        </div>
      </div>
      <div className="access-log-panel">
        <div className="access-log-toolbar">
          <div className="access-log-toolbar-label"><strong>{t('Access Logs')}</strong><span>{entryLabel}</span></div>
          <button className="secondary-light" disabled={rows.length === 0} onClick={exportWafAccessLogs}><Download size={14}/>{t('Export')}</button>
          <button className="danger light" disabled={!!loading || websites.length === 0} onClick={clearWafAccessLogs}><Trash2 size={14}/>{t('Clear')}</button>
          <select value={wafAccessLogFilters.websiteId} onChange={e => updateWafAccessLogFilters({ websiteId: e.target.value }, true)}>
            <option value="">{t('All websites')}</option>
            {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
          </select>
          <select value={wafAccessLogFilters.verdict} onChange={e => updateWafAccessLogFilters({ verdict: e.target.value }, true)}>
            <option value="all">{t('All verdicts')}</option>
            <option value="block">{t('Blocked')}</option>
            <option value="allow">{t('Allowed')}</option>
            <option value="error">{t('Errors')}</option>
          </select>
          <input value={wafAccessLogFilters.query} onChange={e => updateWafAccessLogFilters({ query: e.target.value })} onKeyDown={e => { if (e.key === 'Enter') applyWafAccessLogFilters(); }} placeholder={t('Filter logs')} />
          <select value={wafAccessLogFilters.limit} onChange={e => updateWafAccessLogFilters({ limit: Number(e.target.value) }, true)}>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
            <option value={200}>200 / page</option>
            <option value={500}>500 / page</option>
          </select>
          <select value={wafAccessLogFilters.refresh} onChange={e => updateWafAccessLogFilters({ refresh: Number(e.target.value) })}>
            <option value={0}>{t('Manual refresh')}</option>
            <option value={5}>{t('Refresh 5s')}</option>
            <option value={10}>{t('Refresh 10s')}</option>
            <option value={30}>{t('Refresh 30s')}</option>
          </select>
          <button disabled={!!loading} onClick={applyWafAccessLogFilters}><Search size={14}/>{t('Apply')}</button>
        </div>
        <div className="access-log-table-wrap">
          <table className="access-log-table">
            <thead>
              <tr>
                <th>{t('Verdict')}</th>
                <th>{t('Time')}</th>
                <th>{t('Site')}</th>
                <th>{t('Method')}</th>
                <th>{t('Path')}</th>
                <th>IP</th>
                <th>{t('Country')}</th>
                <th>{t('Reason')}</th>
                <th>{t('Status')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(item => <tr key={item.id}>
                <td data-label={t('Verdict')}><span className={accessLogBadgeClass(item.verdict)}>{accessLogVerdictLabel(item.verdict)}</span></td>
                <td data-label={t('Time')}><span className="access-log-time">{formatAccessLogTime(item.timestamp)}</span><small>{item.duration_ms || 0} ms</small></td>
                <td data-label={t('Site')}><span className="access-log-site">{item.domain}</span></td>
                <td data-label={t('Method')}>{item.method || '-'}</td>
                <td data-label={t('Path')}><code>{item.path || '-'}</code></td>
                <td data-label="IP"><span className="access-log-ip">{item.ip || '-'}</span></td>
                <td data-label={t('Country')}>{accessLogCountryLabel(item)}</td>
                <td data-label={t('Reason')}>{item.reason || '-'}</td>
                <td data-label={t('Status')}>{item.status || '-'}</td>
              </tr>)}
            </tbody>
          </table>
          {rows.length === 0 && <EmptyState icon={FileText} message={t('No access log entries match these filters.')} />}
        </div>
        {(wafAccessLogs.missing || []).length > 0 && <p className="hint">{t('Missing log files:')} {wafAccessLogs.missing.join(', ')}</p>}
      </div>
    </section>;
  }

  function renderUpdates() {
    if (!isAdmin) return <section className="section"><h2>{t('Updates')}</h2><p className="hint">{t('No permission.')}</p></section>;
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
          <div><h2>{t('Updates')}</h2><p className="hint">{t('OS packages use apt; panel updates use')}{' '}<code>bpanel-update</code>.</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={toggleUpdateLog}>{showUpdateLog ? <X size={14}/> : <FileText size={14}/>} {showUpdateLog ? 'Hide logs' : 'View logs'}</button>
        </div>
        <div className="info-box update-version-box">
          <div className="update-version-head"><strong>{t('Panel release')}</strong><span className={panelBadgeClass}>{panelBadge}</span></div>
          <div className="update-version-grid">
            <span>{t('Current')}{' '}<strong>v{currentPanelVersion}</strong></span>
            <span>{t('Latest')}{' '}<strong>{latestPanelVersion === 'unknown' ? 'unknown' : `v${latestPanelVersion}`}</strong></span>
            <span>{t('Checked')}{' '}<strong>{panelUpdate.last_checked_at || 'never'}</strong></span>
            <span>{t('State file')}{' '}<strong>{panelUpdate.state_file || '/var/lib/bpanel/update-status.json'}</strong></span>
          </div>
          {panelUpdate.check_error && <p className="hint">{t('Release check failed:')} {panelUpdate.check_error}</p>}
          {panelUpdate.last_update_status && <p className="hint">{t('Last update:')} {panelUpdate.last_update_status}{panelUpdate.last_update_ref ? ` (${panelUpdate.last_update_ref})` : ''}{panelUpdate.last_update_finished_at ? ` at ${panelUpdate.last_update_finished_at}` : ''}</p>}
        </div>
        <div className="actions">
          <button className="secondary-light" disabled={!!loading} onClick={() => loadUpdates(true)}><RefreshCw size={14}/>{t('Check releases')}</button>
          <button disabled={!!loading || osUpdating} onClick={runOsUpdate}><RefreshCw size={14} className={osUpdating ? 'spin' : ''}/> {osUpdating ? 'Updating OS...' : 'Update OS now'}</button>
          <button disabled={!!loading || panelUpdating || !updateAvailable} onClick={runPanelUpdate}><RotateCcw size={14} className={panelUpdating ? 'spin' : ''}/> {panelUpdating ? 'Updating panel...' : 'Update panel now'}</button>
        </div>
        {showUpdateLog && <div className="info-box firewall-status update-log-box">
          <div className="update-log-head"><strong>{t('Update logs')}</strong><button className="secondary-light" disabled={!!loading} onClick={() => loadUpdates(true)}><RefreshCw size={13}/>{t('Refresh')}</button></div>
          <pre>{statusText}</pre>
        </div>}
        {(panelUpdating || (panelUpdate.progress_percent && panelUpdate.last_update_status && panelUpdate.last_update_status !== 'completed' && panelUpdate.last_update_status !== 'failed')) && (
          <div className="info-box firewall-status update-progress-box">
            <div className="update-progress-row">
              <span className={panelUpdate.last_update_status === 'failed' ? 'badge bad' : 'badge ok'}>
                {panelUpdating ? 'Running' : (panelUpdate.last_update_status === 'failed' ? 'Failed' : (panelUpdate.last_update_status || 'Idle'))}
              </span>
              <span className="update-progress-phase">{panelUpdate.progress_phase || ''}</span>
              <span className="update-progress-pct">{Number(panelUpdate.progress_percent) || 0}%</span>
            </div>
            <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${Number(panelUpdate.progress_percent) || 0}%` }} /></div>
            {panelUpdate.progress_message && <p className="hint update-progress-msg">{panelUpdate.progress_message}</p>}
            {panelUpdateLog.length > 0 && (
              <pre className="update-progress-log">{panelUpdateLog.join('\n')}</pre>
            )}
          </div>
        )}
      </section>
      <section className="section">
        <h2>{t('Auto Update OS')}</h2>
        <div className="firewall-form updates-os-form">
          <label><span>{t('Enabled')}</span><select value={osAutoUpdate.enabled ? 'on' : 'off'} onChange={e => setOsAutoUpdate(prev => ({ ...prev, enabled: e.target.value === 'on' }))}><option value="on">{t('On')}</option><option value="off">{t('Off')}</option></select></label>
          <label><span>{t('Mode')}</span><select value={osAutoUpdate.mode} onChange={e => setOsAutoUpdate(prev => ({ ...prev, mode: e.target.value }))}><option value="security">{t('Security')}</option><option value="all">{t('All packages')}</option></select></label>
          <label><span>{t('Auto reboot')}</span><select value={osAutoUpdate.auto_reboot ? 'on' : 'off'} onChange={e => setOsAutoUpdate(prev => ({ ...prev, auto_reboot: e.target.value === 'on' }))}><option value="off">{t('Off')}</option><option value="on">{t('On')}</option></select></label>
          <button disabled={!!loading} onClick={saveOsAutoUpdate}>{t('Save OS auto update')}</button>
        </div>
      </section>
    </>;
  }

  function renderSecurity() {
    const enabled = Boolean(twoFactorStatus?.enabled || currentUser?.totp_enabled);
    const pk = passkeyStatus;
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Passkey')}</h2>
            <p className="hint">{t('Sign in with a fingerprint, Face ID or a security key instead of typing a code.')}</p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={loadPasskeyStatus}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>

        {pk && !pk.supported && <div className="info-box">
          <p className="hint" style={{color:'var(--red)'}}>
            {t('You are reaching the panel by IP address ({host}). Browsers only create passkeys for domain names, so open the panel by its domain and add one there.', { host: pk.hostname })}
          </p>
        </div>}

        {pk?.supported && <>
          <p className="hint">{t('A passkey is tied to the domain')}{' '}<strong>{pk.rp_id}</strong>.{' '}
            {t('Reach the panel by any other name and it will not be offered — use Google Authenticator below for that.')}
          </p>
          <div className="passkey-form">
            <NoAutofillInput
              name="passkey-name"
              value={passkeyName}
              onChange={e => setPasskeyName(e.target.value)}
              placeholder={t('Device name, e.g. MacBook')}
              aria-label={t('Passkey name')}
            />
            <input
              type="password"
              value={passkeyPassword}
              onChange={e => setPasskeyPassword(e.target.value)}
              placeholder={t('Current password')}
              autoComplete="current-password"
              aria-label={t('Current password')}
            />
            <button disabled={!!loading || !passkeyPassword} onClick={addPasskey}>
              <KeyRound size={14}/>{t('Add passkey')}</button>
          </div>
          <p className="hint">{t('Your current password confirms it is you, the same as when turning on Google Authenticator.')}</p>
        </>}

        {pk?.credentials?.length > 0 && <div className="table">
          {pk.credentials.map(c => <div className="row db-row" key={c.id}>
            <span><strong>{c.name}</strong></span>
            <span style={{color:'var(--text-muted)'}}>{c.rp_id}</span>
            <span className={c.usable_here ? 'badge ok' : 'badge'}>
              {c.usable_here ? 'Works here' : 'Another domain'}
            </span>
            <button className="danger" disabled={!!loading} onClick={() => removePasskey(c)}><Trash2 size={14}/></button>
          </div>)}
        </div>}

        {pk?.supported && (pk?.credentials?.length || 0) === 0 &&
          <EmptyState icon={KeyRound} message={t('No passkeys yet.')} />}

        {(pk?.credentials?.length || 0) > 0 && !enabled && <p className="hint" style={{color:'var(--red)'}}>
          {t('A passkey is your only second factor. Reach the panel by a different domain and there is no second factor at all — turn on Google Authenticator below as well.')}
        </p>}
      </section>

      <section className="section">
        <div className="section-title">
          <div><h2>{t('Google Authenticator 2FA')}</h2><p className="hint">{t('Current status:')}{' '}<strong>{enabled ? 'Enabled' : 'Disabled'}</strong></p></div>
          <button className="secondary-light" disabled={!!loading} onClick={loadTwoFactorStatus}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {!enabled && <div className="security-grid">
          <div className="info-box">
            <strong>{t('Setup')}</strong>
            {twoFactorSetup?.qr_data_url ? <img className="qr-code" src={twoFactorSetup.qr_data_url} alt="2FA QR code" /> : <p className="hint">{t('No setup code generated.')}</p>}
            {twoFactorSetup?.secret && <code className="secret-text">{twoFactorSetup.secret}</code>}
            <div className="actions">
              <button disabled={!!loading} onClick={setupTwoFactorAuth}><Shield size={14}/>{t('Generate QR')}</button>
            </div>
          </div>
          <div className="info-box">
            <strong>{t('Verify')}</strong>
            <input value={twoFactorCode} onChange={e => setTwoFactorCode(e.target.value)} placeholder="123456" inputMode="numeric" />
            <button disabled={!!loading || !twoFactorSetup || !twoFactorCode} onClick={enableTwoFactorAuth}><Lock size={14}/>{t('Enable 2FA')}</button>
          </div>
        </div>}
        {enabled && <div className="security-grid one">
          <div className="info-box">
            <strong>{t('Disable 2FA')}</strong>
            <input value={twoFactorCode} onChange={e => setTwoFactorCode(e.target.value)} placeholder="123456" inputMode="numeric" />
            <button className="danger" disabled={!!loading || !twoFactorCode} onClick={disableTwoFactorAuth}>{t('Disable 2FA')}</button>
          </div>
        </div>}
      </section>

    </>;
  }

  function renderMalware() {
    if (!isAdmin) return <section className="section"><h2>{t('Malware Scanner')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const mw = malwareScanStatus || {};
    const mwActive = Boolean(mw.active);
    const mwInstalled = Boolean(mw.installed);
    const mwEnabled = Boolean(mw.enabled);
    const activeScanJob = scanJob || scanResults || {};
    const scanRunning = ['queued', 'running'].includes(scanJob?.status);
    const scanJobTitle = job => job.scope === 'server'
      ? t('Whole server')
      : (job.domains && job.domains.length > 0)
        ? (job.domains.length === 1 ? job.domains[0] : t('{count} websites', { count: job.domains.length }))
        : (job.scope === 'all' ? t('All websites') : t('Scan'));
    const scanJobStamp = job => {
      const stamp = job.finished_at || job.updated_at || job.started_at || job.created_at || '';
      if (!stamp) return 'No time recorded';
      const date = new Date(stamp);
      return Number.isNaN(date.getTime()) ? stamp : new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Ho_Chi_Minh',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      }).format(date).replace(',', '');
    };
    const scanJobDetail = job => t('{scanned}/{total} files, {infected} threats, {errors} errors', {
      scanned: job.scanned || 0, total: job.total_files || job.scanned || 0, infected: job.infected || 0, errors: job.errors || 0,
    });
    const scanJobMeta = job => `${scanJobStamp(job)} / ${scanJobDetail(job)}`;
    const scanJobBadgeClass = job => {
      if (job.status === 'done') return 'badge ok';
      if (job.status === 'infected') return 'badge danger';
      if (['error', 'interrupted'].includes(job.status)) return 'badge bad';
      return 'badge warn';
    };
    const scanStatusLabels = {
      queued: 'Queued', running: 'Running', done: 'Finished',
      infected: 'Threats found', error: 'Error', interrupted: 'Interrupted',
    };
    // Translated here, not by each caller: two of the three forgot.
    const scanStatusLabel = status => (scanStatusLabels[status] ? t(scanStatusLabels[status]) : (status || '—'));
    const fmtStamp = s => {
      if (!s) return '';
      const d = new Date(s);
      return Number.isNaN(d.getTime()) ? s : new Intl.DateTimeFormat('vi-VN', {
        timeZone: 'Asia/Ho_Chi_Minh', hour12: false,
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
      }).format(d);
    };
    const scheduleDirty = ['websites', 'server'].some(n =>
      JSON.stringify(malwareSchedulesForm[n] || {}) !== JSON.stringify(malwareSchedules[n] || {}));
    const setSched = (name, patch) =>
      setMalwareSchedulesForm(p => ({ ...p, [name]: { ...p[name], ...patch } }));
    const renderScheduleRow = name => {
      const form = malwareSchedulesForm[name] || {};
      const saved = malwareSchedules[name] || {};
      // form.weekday/hour are UTC on the wire; show and edit them as VN time.
      const vn = utcScheduleToVn(form.weekday ?? 6, form.hour ?? 3);
      const setSchedVn = (patch) => {
        const merged = { weekday: patch.weekday ?? vn.weekday, hour: patch.hour ?? vn.hour };
        setSched(name, vnScheduleToUtc(merged.weekday, merged.hour));
      };
      return <div className={`malware-sched-row${form.enabled ? ' on' : ''}`} key={name}>
        <label className="malware-sched-toggle">
          <input type="checkbox" checked={!!form.enabled} onChange={e => setSched(name, { enabled: e.target.checked })} />
          <span>{MALWARE_SCHEDULE_LABELS[name]}</span>
        </label>
        <div className="malware-sched-when">
          <select value={vn.weekday} disabled={!form.enabled} aria-label={t('Day')}
            onChange={e => setSchedVn({ weekday: Number(e.target.value) })}>
            {WEEKDAY_LABELS.map((l, i) => <option key={i} value={i}>{l}</option>)}
          </select>
          <select value={vn.hour} disabled={!form.enabled} aria-label={t('Hour')}
            onChange={e => setSchedVn({ hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
          </select>
        </div>
        <div className="malware-sched-meta">
          {saved.enabled && saved.next_run_at && <span>{t('Next:')}{' '}<strong>{fmtStamp(saved.next_run_at)}</strong></span>}
          {saved.last_run_at && <span className={`badge ${saved.last_status === 'done' ? 'ok' : saved.last_status === 'infected' ? 'danger' : 'warn'}`}>
            {fmtStamp(saved.last_run_at)} · {scanStatusLabel(saved.last_status)}
          </span>}
        </div>
      </div>;
    };

    // One view of a scan, used for the run in progress on this page and for a
    // finished run opened from the history on a page of its own.
    // A /home scan is 180,000 files or more, so a whole percent takes a minute
    // or two to tick over and the figure looked stuck. While a scan runs it is
    // worked out from the counts, with a decimal below 10%.
    const scanPercent = job => {
      const total = Number(job.total_files) || 0;
      if (job.status !== 'running' || !total) return String(Number(job.progress_percent) || 0);
      const exact = Math.min(99, (Number(job.scanned) || 0) * 100 / total);
      return exact > 0 && exact < 10 ? exact.toFixed(1) : String(Math.floor(exact));
    };
    const renderScanStatus = job => <div className="scan-status-panel">
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{width: `${scanPercent(job)}%`}} />
      </div>
      <div className="scan-status-summary">
        <span><strong>{t('Progress')}</strong>{scanPercent(job)}%</span>
        <span><strong>{t('Files scanned')}</strong>{job.scanned || 0}/{job.total_files || job.scanned || 0}</span>
        <span><strong>{t('Threats')}</strong>{job.infected > 0
          ? <span className="badge danger">{job.infected}</span>
          : <span className="badge ok">0</span>}
        </span>
        <span><strong>{t('Errors')}</strong>{job.errors || 0}</span>
      </div>
      {/* The scanner's stage messages are fixed sentences in the dictionary;
          one that is not (an older job's) shows as it was written. */}
      {job.message && <p className="hint">{t(job.message)}</p>}
      {job.threats && job.threats.length > 0 && <div className="scan-threat-list">
        <p className="hint">{t('These are the scanner\'s own family names (php.base64..., for instance), not common virus names — there is nowhere else to look them up.')}</p>
        {job.threats.map((threat, i) => <div key={i} className="scan-threat-item">
          <strong>{threat.signature}</strong>
          <span>{threat.domain ? `${threat.domain}: ` : ''}{threat.path}</span>
        </div>)}
      </div>}
      {job.log && job.log.length > 0 && <pre className="malware-scan-log">{job.log.join('\n')}</pre>}
    </div>;

    // A run from the history, on a page of its own: the list stays short and
    // the one being read gets the width. Reloading the address with nothing
    // chosen points back at the history instead of showing an empty panel.
    if (page === 'malware-scan') {
      const job = activeScanJob;
      return <section className="section scan-detail">
        <div className="section-title">
          <div>
            <h2>{job.job_id ? scanJobTitle(job) : t('Scan details')}</h2>
            {job.job_id && <p className="hint">{scanJobMeta(job)}</p>}
          </div>
          <div className="actions">
            {job.job_id && <span className={scanJobBadgeClass(job)}>{scanStatusLabel(job.status)}</span>}
            <button type="button" className="secondary" onClick={() => navigateToPage('malware')}><ArrowLeft size={14}/>{t('Scan history')}</button>
          </div>
        </div>
        {job.job_id ? renderScanStatus(job) : <EmptyState icon={Search} message={t('Pick a scan from the history.')} />}
      </section>;
    }

    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Malware Scanner')}</h2>
            <p className="hint">
              {mwActive ? <span className="badge ok">{t('On')}</span>
                : mwEnabled && !mwInstalled ? <span className="badge warn">{t('Installing...')}</span>
                : mwInstalled && !mwEnabled ? <span className="badge">{t('Installed · off')}</span>
                : <span className="badge">{t('Not installed')}</span>}
              {mw.realtime_enabled && <span className={mw.monitor_running ? 'badge ok' : 'badge warn'} style={{marginLeft:6}}>
                {t(mw.monitor_running ? 'Level 2 running' : 'Level 2 not running')}
              </span>}
            </p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={loadMalwareScanStatus}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {mw.memory_warning && <div className="info-box malware-ram-warning">
          <strong><AlertCircle size={15}/>{t('Memory warning')}</strong>
          <p className="hint">{mw.memory_warning}</p>
        </div>}
        <div className="info-box">
          <p className="hint">{mw.detail || 'Checking...'}</p>
          {mw.memory_total_mb > 0 && <p className="hint">{t('Server memory:')}{' '}<strong>{mw.memory_total_mb} MB</strong> {t('({n} MB free)', { n: mw.memory_available_mb })}</p>}
          {mw.lmd_installed && <p className="hint">{t('Malware signatures:')}{' '}<strong>{mw.lmd_sig_version || '—'}</strong>{mw.lmd_updated_at ? ` (updated ${mw.lmd_updated_at})` : ''}</p>}
          {!mwInstalled && <p className="hint" style={{marginTop:8}}>{t('Turning this on installs the scanner. It only runs during a scan (~1.3 GB of RAM) and releases that afterwards — nothing runs in the background, so it costs no memory at rest.')}</p>}
          <div className="actions" style={{marginTop:12}}>
            {!mwEnabled
              ? <button disabled={!!loading} onClick={() => toggleMalwareScan(true)}><Shield size={14}/>{t('Turn on scanner')}</button>
              : <button className="danger" disabled={!!loading} onClick={() => toggleMalwareScan(false)}>{t('Turn off scanner')}</button>}
            {mwEnabled && !mw.lmd_installed && <button disabled={!!loading} onClick={installLmd}>{t('Install the scanner')}</button>}
            {mw.lmd_installed && <button className="secondary" disabled={!!loading} onClick={updateMalwareSignatures}><RefreshCw size={13}/>{t('Update signatures')}</button>}
          </div>
        </div>

        {mwInstalled && <div className="info-box malware-scan-panel">
          <div className="malware-scan-runner">
            <div className="malware-scan-head">
              <div>
                <strong>{t('Level 1 — Scheduled scans')}</strong>
                <p className="hint">{t('Scan the website directories (fast), the whole server, or incrementally (only recently changed files — run by hand when you want it, never on the schedule).')}</p>
              </div>
              <button className="secondary" disabled={!!loading} onClick={loadMalwareScanJobs}><RefreshCw size={14}/>{t('History')}</button>
            </div>
            <div className="malware-scan-controls">
              <select value={scanTargetWebsiteId} onChange={e => { setScanTargetWebsiteId(e.target.value); setScanResults(null); setScanJob(null); }}>
                <option value="">-- Scan now: pick a target --</option>
                <option value="all">{t('All websites')}</option>
                <option value="incremental">{t('Incremental scan')}</option>
                <option value="server">{t('Whole server')}</option>
                {websites.map(w => <option key={w.id} value={w.id}>{w.domain}</option>)}
              </select>
              {scanTargetWebsiteId === 'incremental' && <select value={incrementalDays} onChange={e => setIncrementalDays(Number(e.target.value))}>
                {[1, 2, 3, 7, 14].map(d => <option key={d} value={d}>{d} days</option>)}
              </select>}
              <button disabled={!!loading || scanRunning || !scanTargetWebsiteId} onClick={runMalwareScan}>
                {scanRunning || scanLoading ? <><RefreshCw size={14} className="spin"/>{t('Scanning...')}</> : <><Search size={14}/>{t('Scan now')}</>}
              </button>
            </div>
          </div>
          <div className="malware-schedule">
            <div className="malware-scan-head">
              <div><strong>{t('Automatic schedule')}</strong><p className="hint">{t('The panel scans on its own, with nobody pressing anything. Pick an hour when few visitors are around.')}</p></div>
              <button disabled={!!loading || !scheduleDirty} onClick={saveMalwareSchedule}><Clock size={14}/>{t('Save schedule')}</button>
            </div>
            <div className="malware-sched-list">
              {['websites', 'server'].map(renderScheduleRow)}
            </div>
          </div>
          <div className="malware-realtime">
            <div className="malware-scan-head">
              <div>
                <strong>{t('Level 2 — Real-time protection')}</strong>
                <p className="hint">{t('Watches the website directories continuously and checks new files in short batches (~15 seconds). Catches something arriving over SFTP or through a plugin at once, instead of waiting for the next Level 1 scheduled scan.')}</p>
              </div>
              <label className="switch-line">
                <input type="checkbox" checked={!!mw.realtime_enabled} disabled={!!loading}
                  onChange={e => toggleMalwareRealtime(e.target.checked)} />
                <span>{mw.realtime_enabled ? 'On' : 'Off'}</span>
              </label>
            </div>
          </div>
          <div className="malware-realtime">
            <div className="malware-scan-head">
              <div>
                <strong>{t('Scan uploaded files')}</strong>
                <p className="hint">
                  Scans each file uploaded through the file manager, in the background after the upload finishes, so nobody waits on it.
                  Off by default: without a resident clamd, every file reloads the whole signature database
                  (measured at 28 seconds and over 1 GB of RAM for a 20 MB file). The Level 1 scheduled scan covers these files either way.
                </p>
                {!mw.scan_on_upload_is_cheap && <p className="hint">{t('This server has no resident clamd — start one first and each scan drops to milliseconds.')}</p>}
              </div>
              <label className="switch-line">
                <input type="checkbox" checked={!!mw.scan_on_upload} disabled={!!loading}
                  onChange={e => toggleMalwareScanOnUpload(e.target.checked)} />
                <span>{mw.scan_on_upload ? 'On' : 'Off'}</span>
              </label>
            </div>
          </div>
          {scanJobs.length > 0 && <div className="scan-history-wrap">
            <div className="scan-history-head">
              <strong>{t('Scan history')}</strong>
              <span>{scanJobs.length} runs</span>
            </div>
            <div className="scan-history-list">
              {scanJobs.slice(0, 8).map(job => <button
                key={job.job_id}
                className={`scan-history-item ${job.status}${activeScanJob.job_id === job.job_id ? ' active' : ''}`}
                onClick={() => { showMalwareScanJob(job); navigateToPage('malware-scan'); }}
                disabled={!!loading}
                type="button"
              >
                <Clock size={14}/>
                <span className="scan-history-main">
                  <strong>{scanJobTitle(job)}</strong>
                  <small>{scanJobMeta(job)}</small>
                </span>
                <span className={scanJobBadgeClass(job)}>{scanStatusLabel(job.status)}</span>
              </button>)}
            </div>
          </div>}
          {/* The live run stays here while it is running; a finished one is
              read on its own page from the history above. */}
          {(scanRunning || scanLoading) && (scanJob || scanResults) && renderScanStatus(activeScanJob)}
        </div>}
      </section>
    </>;
  }

  function renderPanelSettings() {
    if (!isAdmin) return <section className="section"><h2>{t('Settings')}</h2><p className="hint">{t('No permission.')}</p></section>;
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Panel settings')}</h2><p className="hint">{t('Branding and hostname.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={loadPanelSettings}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        <div className="panel-settings-grid panel-settings-compact">
          <label><span>{t('Panel name')}</span><input value={panelSettingsForm.app_name} onChange={e => setPanelSettingsForm(prev => ({ ...prev, app_name: e.target.value }))} placeholder="BPanel" /></label>
          <label><span>{t('Panel hostname')}</span><input value={panelSettingsForm.panel_hostname} onChange={e => setPanelSettingsForm(prev => ({ ...prev, panel_hostname: e.target.value }))} placeholder="panel.domain.com" /></label>
          <label className="check-line panel-ssl-status"><input type="checkbox" checked={!!panelSettingsForm.ssl_enabled} onChange={e => setPanelSettingsForm(prev => ({ ...prev, ssl_enabled: e.target.checked }))} />{t('Panel SSL')}</label>
          <button disabled={!!loading || !panelSettingsForm.app_name || !panelSettingsForm.panel_hostname} onClick={savePanelSettings}><SettingsIcon size={14}/>{t('Save settings')}</button>
        </div>
        <div className="panel-net-strip">
          <div className="panel-net-row">
            <span className="panel-net-label">IPv4</span>
            <div className="panel-net-value">
              {panelSettings.server_ipv4?.length > 0
                ? panelSettings.server_ipv4.map(address => <span key={address} className="badge">{address}</span>)
                : <span className="hint">{t('Could not read the server\'s IPv4 address.')}</span>}
            </div>
          </div>
          <div className="panel-net-row">
            <span className="panel-net-label">IPv6</span>
            <div className="panel-net-value">
              {panelSettings.ipv6?.addresses?.length > 0
                ? panelSettings.ipv6.addresses.map(address => <span key={address} className="badge">{address}</span>)
                : <span className="badge">{t('None')}</span>}
              <span className={`badge ${panelSettings.ipv6?.enabled ? 'ok' : ''}`}>
                {panelSettings.ipv6?.enabled ? 'On' : 'Off'}
              </span>
            </div>
            {panelSettings.ipv6?.enabled
              ? <button className="secondary-light" disabled={!!loading} onClick={() => toggleIpv6(false)}>{t('Disable IPv6')}</button>
              : <button className="secondary-light" disabled={!!loading || !panelSettings.ipv6?.available} onClick={() => toggleIpv6(true)}>{t('Enable IPv6')}</button>}
          </div>
          <span className="hint">{panelSettings.ipv6?.detail}</span>
        </div>
      </section>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Admin account')}</h2></div>
        </div>
        <div className="panel-settings-grid admin-account-grid">
          <label><span>{t('Email')}</span><input type="email" value={adminAccountForm.email} onChange={e => setAdminAccountForm(prev => ({ ...prev, email: e.target.value }))} placeholder="admin@domain.com" /></label>
          <label><span>{t('Current password')}</span><input type="password" value={adminAccountForm.current_password} onChange={e => setAdminAccountForm(prev => ({ ...prev, current_password: e.target.value }))} placeholder={t('Current password')} autoComplete="current-password" /></label>
          <label><span>{t('New password')}</span><input type="password" value={adminAccountForm.password} onChange={e => setAdminAccountForm(prev => ({ ...prev, password: e.target.value }))} placeholder={t('New password')} autoComplete="new-password" /></label>
          <label><span>{t('Confirm password')}</span><input type="password" value={adminAccountForm.confirm_password} onChange={e => setAdminAccountForm(prev => ({ ...prev, confirm_password: e.target.value }))} placeholder={t('Repeat new password')} autoComplete="new-password" /></label>
          <label><span>{t('Authenticator code')}</span><input value={adminAccountForm.code} onChange={e => setAdminAccountForm(prev => ({ ...prev, code: e.target.value }))} placeholder="123456" inputMode="numeric" autoComplete="one-time-code" /></label>
          <button disabled={!!loading || !adminAccountForm.email.trim() || (!!adminAccountForm.password && adminAccountForm.password !== adminAccountForm.confirm_password)} onClick={saveAdminAccount}><Lock size={14}/>{t('Save account')}</button>
        </div>
      </section>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Brand assets')}</h2><p className="hint">{t('Upload PNG, JPG, WEBP, or ICO files up to 1 MB.')}</p></div>
        </div>
        <div className="brand-asset-grid">
          <div className="brand-asset-card">
            <div className="brand-preview">{renderBrandMark('settings-brand-mark')}</div>
            <label><span>{t('Logo')}</span><input type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={e => setPanelLogoFile(e.target.files?.[0] || null)} /></label>
            <button disabled={!!loading || !panelLogoFile} onClick={() => uploadPanelAsset('logo')}><Upload size={14}/>{t('Upload logo')}</button>
          </div>
          <div className="brand-asset-card">
            <div className="brand-preview favicon-preview">{panelSettings.favicon_url ? <img src={panelSettings.favicon_url} alt="" /> : <Image size={28}/>}</div>
            <label><span>{t('Favicon')}</span><input type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={e => setPanelFaviconFile(e.target.files?.[0] || null)} /></label>
            <button disabled={!!loading || !panelFaviconFile} onClick={() => uploadPanelAsset('favicon')}><Upload size={14}/>{t('Upload favicon')}</button>
          </div>
        </div>
      </section>
      {renderApiTokenSections()}
    </>;
  }

  // Its own function, not its own page: tokens are a panel-wide setting, and a
  // nav entry of their own made people hunt for them.
  function renderApiTokenSections() {
    if (!isAdmin) return null;
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('API Tokens')}</h2><p className="hint">{t('Create one token for WHMCS. Paste it into WHMCS Server → Access Hash.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={loadApiTokens}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {createdApiToken && <div className="user-create-card">
          <label><span>{t('New token (copy now)')}</span><input id="created-api-token" readOnly value={createdApiToken} onFocus={e => e.target.select()} /></label>
          <button className="secondary" disabled={!!loading} onClick={copyApiToken}><Copy size={14}/>{t('Copy token')}</button>
          <button className="secondary-light" onClick={() => setCreatedApiToken('')}>{t('Hide')}</button>
        </div>}
        <div className="user-create-card">
          <label><span>{t('Name')}</span><input value={newApiToken.name} onChange={e => setNewApiToken(prev => ({ ...prev, name: e.target.value }))} placeholder="WHMCS" /></label>
          <label><span>{t('WHMCS server IP')}</span><input value={newApiToken.allowed_ips} onChange={e => setNewApiToken(prev => ({ ...prev, allowed_ips: e.target.value }))} placeholder={t('optional: 1.2.3.4 or 1.2.3.4, 5.6.7.8')} /></label>
          <button disabled={!!loading || !newApiToken.name.trim()} onClick={createApiToken}><Plus size={14}/>{t('Create token')}</button>
        </div>
        <p className="hint">{t('Leave WHMCS server IP empty to allow all IPs. Multiple IPs: separate with comma.')}</p>
        <div className="package-list">
          {apiTokens.length === 0 && <EmptyState icon={KeyRound} message={t('No API tokens found.')} />}
          {apiTokens.map(token => <div className="package-row" key={token.id}>
            <div className="user-main"><strong>{token.name}</strong><small>{token.allowed_ips ? `Allowed IPs: ${token.allowed_ips}` : 'Allowed IPs: all'}</small></div>
            <span className="user-metric"><KeyRound size={13}/>{token.is_active ? 'Active' : 'Revoked'}</span>
            <span className="user-metric"><Clock size={13}/>{token.last_used_at ? new Date(token.last_used_at).toLocaleString() : 'Never used'}</span>
            <div className="row-actions">
              <button className="mini danger" disabled={!!loading || !token.is_active} onClick={() => revokeApiToken(token)}><Trash2 size={14}/>{t('Revoke')}</button>
            </div>
          </div>)}
        </div>
      </section>
    </>;
  }

  function renderUsers() {
    if (!isAdmin) return <section className="section"><h2>{t('Users')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const activeUserTab = userTab || 'list';
    const userTabButton = (key, Icon, label) => (
      <button
        type="button"
        className={activeUserTab === key ? 'active' : ''}
        role="tab"
        aria-selected={activeUserTab === key}
        aria-controls={`users-tab-${key}`}
        id={`users-tab-button-${key}`}
        onClick={() => setUserTab(key)}
      >
        <Icon size={14}/>{t(label)}
      </button>
    );

    return <section className="section users-page">
      <div className="section-title">
        <div><h2>{t('Panel users')}</h2><p className="hint">{t('Manage users, packages, and domain ownership.')}</p></div>
      </div>
      {/* One underlined row, like the backup tabs and OPanel's. */}
      <div className="segmented-control backup-tabs user-tabs" role="tablist" aria-label={t('Panel user sections')}>
        {userTabButton('list', Users, 'List user')}
        {userTabButton('packages', HardDrive, 'Package')}
        {userTabButton('add', Plus, 'Add User')}
      </div>

      {activeUserTab === 'list' && <div className="user-tab-panel" id="users-tab-list" role="tabpanel" aria-labelledby="users-tab-button-list">
        <div className="section-title user-panel-title">
          <div><h2>{t('Panel user list')}</h2><p className="hint">{t('Current panel users and service limits.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={loadUsers}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        {users.length === 0 && <EmptyState icon={Users} message={t('No users found.')} />}
        <div className="table">
          {users.map(user => <div className="row user-row" key={user.id}>
            <div className="user-main"><strong>{user.username}</strong><small>{user.email}</small></div>
            <div className="user-badges">
              <span className={user.is_active ? 'badge ok' : 'badge danger'}>{user.is_active ? t('Active') : t('Suspended')}</span>
              <span className="badge">{t(roleLabel(user.role))}</span>
              <span className="badge">{user.package_name || t('Custom')}</span>
              {user.totp_enabled && <span className="badge ok">2FA</span>}
            </div>
            <span className="user-metric"><HardDrive size={13}/>{storageUsageText(user)}</span>
            <div className="row-actions">
              <button className="mini secondary-light" disabled={!!loading} onClick={() => startEditingUser(user)}><Pencil size={14}/>{t('Edit')}</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => quickLoginUser(user)}><LogIn size={14}/>{t('Login as')}</button>
              {user.totp_enabled && user.id !== currentUser?.id && <button className="mini secondary-light" disabled={!!loading} onClick={() => resetUserTwoFactor(user)}>{t('Reset 2FA')}</button>}
              {user.id !== currentUser?.id && (user.is_active
                ? <button className="mini secondary-light" disabled={!!loading} onClick={() => suspendUser(user)}><Ban size={14}/>{t('Suspend')}</button>
                : <button className="mini secondary-light" disabled={!!loading} onClick={() => unsuspendUser(user)}><Play size={14}/>{t('Unsuspend')}</button>
              )}
              {user.id !== currentUser?.id && <button className="mini danger" disabled={!!loading} onClick={() => deletePanelUser(user)}><Trash2 size={14}/></button>}
            </div>
            {editingUser?.id === user.id && <div className="user-edit-panel">
              <div className="user-edit-heading">
                <div><strong>Edit {user.username}</strong><small>
                  {user.id === currentUser?.id ? 'Role is locked for the active admin session.' : 'Role changes sign the user out of existing sessions.'}
                  {editingUserForm.role === 'admin' ? ' Admin accounts bypass website and storage limits.' : ''}
                </small></div>
                <button className="user-edit-close secondary-light" onClick={cancelEditingUser} aria-label={t('Close user editor')} title={t('Close user editor')}><X size={16}/></button>
              </div>
              <div className="user-edit-grid">
                <label><span>{t('Email')}</span><input type="email" value={editingUserForm.email} onChange={e => setEditingUserForm(prev => ({ ...prev, email: e.target.value }))} /></label>
                <label><span>{t('Role')}</span><select value={editingUserForm.role} disabled={user.id === currentUser?.id} onChange={e => setEditingUserForm(prev => ({ ...prev, role: e.target.value }))}>
                  <option value="end_user">{t('End user')}</option><option value="admin">{t('Admin')}</option>
                </select></label>
                <label><span>{t('Package')}</span><select value={editingUserForm.package_id} onChange={e => applyPackageToEditingUser(e.target.value)}>
                  <option value="">{t('Custom limits')}</option>
                  {packages.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select></label>
                <label><span>{t('Website limit')}</span><input type="number" min="0" max="1000" disabled={!!editingUserForm.package_id} value={editingUserForm.website_limit} onChange={e => setEditingUserForm(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
                <label><span>{t('Storage limit (MB)')}</span><input type="number" min="0" max="1048576" disabled={!!editingUserForm.package_id} value={editingUserForm.storage_limit_mb} onChange={e => setEditingUserForm(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
                <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" disabled={!!editingUserForm.package_id} value={editingUserForm.sftp_accounts_limit} onChange={e => setEditingUserForm(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
              </div>
              <div className="user-edit-section">
                <div className="user-edit-heading"><div><strong>{t('Change password')}</strong><small>{t('Minimum 12 characters.')} {t(user.id === currentUser?.id ? 'Requires current password + 2FA.' : 'Admin can set directly.')}</small></div></div>
                <div className="user-edit-grid">
                  <label><span>{t('New password')}</span><input type="password" placeholder={t('Min 12 characters')} value={editingUserForm.new_password} onChange={e => setEditingUserForm(prev => ({ ...prev, new_password: e.target.value }))} /></label>
                  <label><span>{t('Confirm password')}</span><input type="password" placeholder={t('Repeat password')} value={editingUserForm.confirm_password} onChange={e => setEditingUserForm(prev => ({ ...prev, confirm_password: e.target.value }))} /></label>
                </div>
                <div className="user-edit-actions">
                  <button disabled={!!loading || !editingUserForm.new_password || editingUserForm.new_password.length < 12} onClick={() => submitPasswordChange(user)}>{t('Set password')}</button>
                </div>
              </div>
              <div className="user-edit-actions">
                <button className="secondary-light" onClick={cancelEditingUser}>{t('Cancel')}</button>
                <button disabled={!!loading || !editingUserForm.email.trim()} onClick={updatePanelUser}><Save size={14}/>{t('Save changes')}</button>
              </div>
            </div>}
          </div>)}
        </div>
        <div className="user-action-panel">
          <div><h3>{t('Assign domain to user')}</h3><p className="hint">{t('Move an existing domain under a selected panel user.')}</p></div>
          <div className="assign-row">
            <select value={assignWebsiteId} onChange={e => setAssignWebsiteId(e.target.value)}>
              <option value="">{t('Select domain')}</option>
              {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
            </select>
            <select value={assignUserId} onChange={e => setAssignUserId(e.target.value)}>
              <option value="">{t('Select user')}</option>
              {users.map(user => <option key={user.id} value={user.id}>{user.username} ({roleLabel(user.role)})</option>)}
            </select>
            <button disabled={!assignWebsiteId || !assignUserId || !!loading} onClick={assignDomainToUser}>{t('Assign')}</button>
          </div>
        </div>
      </div>}

      {activeUserTab === 'packages' && <div className="user-tab-panel" id="users-tab-packages" role="tabpanel" aria-labelledby="users-tab-button-packages">
        <div className="section-title user-panel-title">
          <div><h2>{t('Package')}</h2><p className="hint">{t('Create, edit, delete, and review reusable user limits.')}</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={loadPackages}><RefreshCw size={14}/>{t('Refresh')}</button>
        </div>
        <div className="user-create-card package-create-card">
          <label><span>{t('Package name')}</span><input value={newPackage.name} onChange={e => setNewPackage(prev => ({ ...prev, name: e.target.value }))} placeholder={t('Starter')} /></label>
          <label><span>{t('Site limit')}</span><input type="number" min="0" max="1000" value={newPackage.website_limit} onChange={e => setNewPackage(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
          <label><span>{t('Storage MB')}</span><input type="number" min="0" max="1048576" value={newPackage.storage_limit_mb} onChange={e => setNewPackage(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
          <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" value={newPackage.sftp_accounts_limit} onChange={e => setNewPackage(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
          <button disabled={!!loading || !newPackage.name.trim()} onClick={createPackage}><Plus size={14}/>{t('Create package')}</button>
        </div>
        <div className="package-list">
          {packages.length === 0 && <EmptyState icon={HardDrive} message={t('No packages found.')} />}
          {packages.map(item => <div className="package-row" key={item.id}>
            {String(editingPackageId) === String(item.id) ? <>
              <label><span>{t('Name')}</span><input value={editingPackageForm.name} onChange={e => setEditingPackageForm(prev => ({ ...prev, name: e.target.value }))} /></label>
              <label><span>{t('Site limit')}</span><input type="number" min="0" max="1000" value={editingPackageForm.website_limit} onChange={e => setEditingPackageForm(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
              <label><span>{t('Storage MB')}</span><input type="number" min="0" max="1048576" value={editingPackageForm.storage_limit_mb} onChange={e => setEditingPackageForm(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
              <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" value={editingPackageForm.sftp_accounts_limit} onChange={e => setEditingPackageForm(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
              <div className="row-actions">
                <button className="mini secondary-light" onClick={cancelEditingPackage}>{t('Cancel')}</button>
                <button className="mini" disabled={!!loading || !editingPackageForm.name.trim()} onClick={() => updatePackage(item.id)}><Save size={14}/>{t('Save')}</button>
              </div>
            </> : <>
              <div className="user-main"><strong>{item.name}</strong><small>{item.website_limit} sites - {item.storage_limit_mb} MB</small></div>
              <span className="user-metric"><Globe size={13}/>{item.website_limit} sites</span>
              <span className="user-metric"><HardDrive size={13}/>{item.storage_limit_mb} MB</span>
              <div className="row-actions">
                <button className="mini secondary-light" disabled={!!loading} onClick={() => startEditingPackage(item)}><Pencil size={14}/>{t('Edit')}</button>
                <button className="mini danger" disabled={!!loading || users.some(user => user.package_id === item.id)} onClick={() => deletePackage(item)}><Trash2 size={14}/></button>
              </div>
            </>}
          </div>)}
        </div>
      </div>}

      {activeUserTab === 'add' && <div className="user-tab-panel" id="users-tab-add" role="tabpanel" aria-labelledby="users-tab-button-add">
        <div className="section-title user-panel-title">
          <div><h2>{t('Add User')}</h2><p className="hint">{t('Panel username is also the Linux user. Login as a user before creating websites for that account.')}</p></div>
        </div>
        <div className="user-create-card">
          <label><span>{t('Username')}</span><input value={newUser.username} onChange={e => setNewUser(prev => ({ ...prev, username: e.target.value.toLowerCase() }))} placeholder="johndoe" /></label>
          <label><span>{t('Email')}</span><input value={newUser.email} onChange={e => setNewUser(prev => ({ ...prev, email: e.target.value }))} placeholder="user@domain.com" /></label>
          <label><span>{t('Password')}</span><input value={newUser.password} onChange={e => setNewUser(prev => ({ ...prev, password: e.target.value }))} placeholder={t('Min 12 characters')} type="password" /></label>
          <label><span>{t('Role')}</span><select value={newUser.role} onChange={e => setNewUser(prev => ({ ...prev, role: e.target.value }))}>
            <option value="end_user">{t('End user')}</option><option value="admin">{t('Admin')}</option>
          </select></label>
          <label><span>{t('Package')}</span><select value={newUser.package_id} onChange={e => applyPackageToNewUser(e.target.value)}>
            <option value="">{t('Custom limits')}</option>
            {packages.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <label><span>{t('Site limit')}</span><input type="number" disabled={!!newUser.package_id} value={newUser.website_limit} onChange={e => setNewUser(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
          <label><span>{t('Storage MB')}</span><input type="number" disabled={!!newUser.package_id} value={newUser.storage_limit_mb} onChange={e => setNewUser(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
          <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" disabled={!!newUser.package_id} value={newUser.sftp_accounts_limit} onChange={e => setNewUser(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
          <button disabled={!!loading || !newUser.username || !newUser.password} onClick={createUser}><Plus size={14}/>{t('Create user')}</button>
        </div>
      </div>}
    </section>;
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
          <span className="editor-chip">{t('{n} line(s)', { n: editorLineCount })}</span>
          <span className="editor-chip">Ln {editorCursor.line}, Col {editorCursor.column}</span>
          <button className="secondary" disabled={!selectedWebsiteId || !!loading} onClick={() => readFile(filePath)}><RefreshCw size={14}/>{t('Reload')}</button>
          <button disabled={!selectedWebsiteId || !!loading} onClick={writeFile}>{t('Save')}</button>
          <button disabled={!selectedWebsiteId || !filePath || !!loading} onClick={() => downloadFile(filePath)}><Download size={14}/></button>
          <LanguageToggle language={language} onChange={changeLanguage}/>
          <ThemeToggle theme={theme} onToggle={toggleTheme}/>
          <button className="secondary-light" onClick={() => window.close()}><X size={14}/>{t('Close')}</button>
        </div>
      </header>
      {loading && <div className="loading">{t(loading)}</div>}
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

  // --- AI assistants (MCP) --------------------------------------------------

  async function copyText(text, message) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const holder = document.createElement('textarea');
        holder.value = text;
        holder.style.position = 'fixed';
        holder.style.opacity = '0';
        document.body.appendChild(holder);
        holder.select();
        document.execCommand('copy');
        document.body.removeChild(holder);
      }
      setNotice(message || 'Copied.');
    } catch {
      setError(t('Copy failed. Select the text and press Ctrl+C.'));
    }
  }


  async function loadMcpTokens() {
    const data = await request('/mcp/tokens');
    if (data) setMcpTokens(Array.isArray(data) ? data : []);
  }

  async function createMcpToken() {
    const name = (mcpDraft.name || '').trim();
    if (!name) return;
    const data = await request('/mcp/tokens', {
      method: 'POST',
      body: JSON.stringify({
        name,
        expires_in_days: Number(mcpDraft.expires_in_days || 90),
        can_write: !!mcpDraft.can_write,
      }),
    }, t('Creating token...'));
    if (data) {
      // Shown once and never again: the server keeps only a hash. It stays on
      // screen until the person dismisses it rather than disappearing on the
      // next render, because there is no way to get it back.
      setMcpNewToken(data.token);
      setMcpDraft({ name: '', expires_in_days: 90, can_write: false });
      setNotice(t('Token created. Copy it now - it is not shown again.'));
      await loadMcpTokens();
    }
  }

  async function revokeMcpToken(token) {
    if (!window.confirm(`Revoke "${token.name}"? Any assistant using it stops working immediately.`)) return;
    const data = await request(`/mcp/tokens/${token.id}`, { method: 'DELETE' }, t('Revoking...'));
    if (data) {
      setNotice(t('Token revoked.'));
      await loadMcpTokens();
    }
  }

  function renderMcp() {
    const endpoint = `${window.location.origin}/api/mcp`;
    const mine = mcpTokens.filter(token => token.user_id === currentUser?.id);
    const others = mcpTokens.filter(token => token.user_id !== currentUser?.id);
    const selfSigned = !window.location.protocol.startsWith('https');

    // The real token while it is still on screen, the placeholder once it has
    // been dismissed. Somebody who has just made a token wants to paste a
    // finished command, not paste one and then go hunting for the value to
    // substitute - and since the panel can never show the token again, the
    // window in which this can help is exactly the window in which it is up.
    const bearer = mcpNewToken || 'YOUR_TOKEN';
    const claudeCode = `claude mcp add --transport http bpanel ${endpoint} \\\n  --header "Authorization: Bearer ${bearer}"`;
    const cursor = JSON.stringify({
      mcpServers: {
        bpanel: { url: endpoint, headers: { Authorization: `Bearer ${bearer}` } },
      },
    }, null, 2);
    const vscode = JSON.stringify({
      servers: {
        bpanel: { type: 'http', url: endpoint, headers: { Authorization: `Bearer ${bearer}` } },
      },
    }, null, 2);

    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('AI assistants (MCP)')}</h2>
            <p className="hint">
              {t('Give Claude Code, Cursor or VS Code a token and it can read and operate the panel with exactly your own permissions - nothing more.')}
            </p>
          </div>
          <button className="secondary-light" disabled={!!loading} onClick={loadMcpTokens}>
            <RefreshCw size={14}/>{t('Refresh')}</button>
        </div>

        {!mcpAddonInstalled && <div className="addon-notes">
          <strong><AlertCircle size={13}/>{t('The addon is off')}</strong>
          <ul><li>{t('Nothing answers on this address until an administrator installs')}{' '}<strong>{t('AI assistants (MCP)')}</strong> on the Addons page. Existing tokens are kept
            while it is off.</li></ul>
        </div>}

        {selfSigned && <div className="addon-notes">
          <strong><AlertCircle size={13}/>{t('This panel needs a real certificate')}</strong>
          <ul><li>{t('MCP clients refuse a self-signed certificate, so no assistant will connect until the panel has one. Install it under Panel settings → SSL.')}</li></ul>
        </div>}

        <div className="mcp-endpoint">
          <span>{t('Endpoint')}</span>
          <code>{endpoint}</code>
          <button className="mini secondary-light" onClick={() => copyText(endpoint, 'Endpoint copied.')}>
            <Copy size={13}/>{t('Copy')}</button>
        </div>
      </section>

      <section className="section">
        <div className="section-title"><div><h2>{t('New token')}</h2><p className="hint">{t('A token acts as you. It is shown once, when you create it.')}</p></div></div>
        <div className="form-row">
          <input
            placeholder={t('What is it for - laptop, work desktop')}
            value={mcpDraft.name}
            maxLength={100}
            onChange={event => setMcpDraft(prev => ({ ...prev, name: event.target.value }))}
          />
          <select
            value={mcpDraft.expires_in_days}
            aria-label={t('Expires in')}
            onChange={event => setMcpDraft(prev => ({ ...prev, expires_in_days: event.target.value }))}>
            <option value="7">{t('Expires in 7 days')}</option>
            <option value="30">{t('Expires in 30 days')}</option>
            <option value="90">{t('Expires in 90 days')}</option>
            <option value="365">{t('Expires in a year')}</option>
          </select>
          <label className="check-line">
            <input
              type="checkbox"
              checked={!!mcpDraft.can_write}
              onChange={event => setMcpDraft(prev => ({ ...prev, can_write: event.target.checked }))}
            />
            <span>{t('Allow actions')}</span>
          </label>
          <button disabled={!mcpDraft.name.trim() || !!loading} onClick={createMcpToken}>
            <KeyRound size={14}/>{t('Create')}</button>
        </div>
        <p className="hint">{t('Without')}{' '}<strong>{t('Allow actions')}</strong> the token can only read, and the assistant is not
          even shown the tools that change anything. Leave it off unless you want the assistant to
          act.
        </p>

        {mcpNewToken && <div className="mcp-secret">
          <div>
            <strong>{t('Copy this now. It is not shown again.')}</strong>
            <code>{mcpNewToken}</code>
          </div>
          <div className="actions">
            <button className="mini" onClick={() => copyText(mcpNewToken, 'Token copied. It is not shown again.')}><Copy size={13}/>{t('Copy')}</button>
            <button className="mini secondary-light" onClick={() => setMcpNewToken('')}>{t('Done')}</button>
          </div>
        </div>}
      </section>

      <section className="section">
        <div className="section-title"><div><h2>{t('Your tokens')}</h2></div></div>
        {mine.length === 0
          ? <EmptyState icon={KeyRound} message={t('No tokens yet.')} />
          : <div className="backup-list">{mine.map(token => renderMcpTokenRow(token))}</div>}
      </section>

      {isAdmin && others.length > 0 && <section className="section">
        <div className="section-title"><div><h2>{t('Everyone else\'s tokens')}</h2><p className="hint">{t('Every key to this server, and who holds it. You can revoke any of them.')}</p></div></div>
        <div className="backup-list">{others.map(token => renderMcpTokenRow(token, true))}</div>
      </section>}

      <section className="section">
        <div className="section-title"><div><h2>{t('Connecting a client')}</h2><p className="hint">
          {mcpNewToken
            ? <>Your new token is already filled in below - copy one and paste it straight in.
                {t('Once you dismiss the token above these go back to saying YOUR_TOKEN, because the panel cannot show it to you a second time.')}</>
            : <>{t('Create a token above and it appears in these ready to copy. Otherwise replace YOUR_TOKEN yourself.')}</>}
        </p></div></div>
        {[['Claude Code', claudeCode], ['Cursor - .cursor/mcp.json', cursor],
          ['VS Code - .vscode/mcp.json', vscode]].map(([label, snippet]) => (
          <div className="mcp-snippet" key={label}>
            <div className="mcp-snippet-head">
              <strong>{label}</strong>
              <button className="mini secondary-light" onClick={() => copyText(snippet, 'Configuration copied.')}>
                <Copy size={13}/>{t('Copy')}</button>
            </div>
            <pre>{snippet}</pre>
          </div>
        ))}
      </section>
    </>;
  }

  function renderMcpTokenRow(token, showOwner = false) {
    const revoked = !!token.revoked_at;
    const dead = revoked || token.expired;
    return <div className="backup-item" key={token.id}>
      <span>
        {token.name}
        {showOwner && <> - <strong>{token.username}</strong></>}
        <span className={`badge ${token.can_write ? '' : 'ok'}`}>
          {token.can_write ? 'can act' : 'read only'}
        </span>
        {revoked && <span className="badge">revoked</span>}
        {!revoked && token.expired && <span className="badge">expired</span>}
        <small>
          <code>{token.prefix}…</code>
          {dead ? '' : ` · expires ${new Date(token.expires_at).toLocaleDateString()}`}
          {token.last_used_at
            ? ` · last used ${new Date(token.last_used_at).toLocaleString()}`
            : ' · never used'}
        </small>
      </span>
      <div className="actions">
        {!revoked && <button className="mini danger" disabled={!!loading}
          onClick={() => revokeMcpToken(token)}><Trash2 size={14}/>{t('Revoke')}</button>}
      </div>
    </div>;
  }

  function renderPage() {
    if (page === 'websites') return renderWebsites();
    if (page === 'addons') return renderAddons();
    // Reachable by URL after the addon is removed, so it answers for itself
    // rather than rendering a page whose every request would be refused.
    if (page === 'applications') return appsFeatureEnabled ? renderApplications() : renderAddonMissing();
    if (page === 'ssl') return renderSsl();
    if (page === 'databases') return renderDatabases();
    if (page === 'sftp') return renderSftp();
    if (page === 'cron') return renderCron();
    if (page === 'files') return renderFiles();
    if (page === 'backups') return renderBackups();
    if (page === 'security') return renderSecurity();
    if (page === 'php') return renderPhpConfig();
    if (page === 'firewall') return renderFirewall();
    if (page === 'waf') return renderWaf();
    if (page === 'waf-site') return renderWafSite();
    if (page === 'malware' || page === 'malware-scan') return renderMalware();
    if (page === 'access-logs') return renderWafAccessLogs();
    if (page === 'updates') return renderUpdates();
    // Reachable by URL, so it answers for itself rather than firing a
    // page full of requests that will every one be refused.
    if (page === 'services') return isAdmin ? renderServices() : renderAdminOnly();
    if (page === 'mcp') return (mcpAddonInstalled || isAdmin) ? renderMcp() : renderAddonMissing();
    if (page === 'settings') return renderPanelSettings();
    if (page === 'users') return renderUsers();
    return renderDashboard();
  }

  // Login screen
  if (bootstrapping) {
    return <main className="login-page">
      <section className="login-card">
        <div className="login-brand">{renderBrandMark('login-brand-mark')}<div><p className="eyebrow">{panelSettings.app_name || 'BPanel'}</p><h1>{t('Loading…')}</h1></div></div>
      </section>
    </main>;
  }

  if (!isAuthenticated) {
    return <main className="login-page">
      <section className="login-card">
        <div className="login-card-head">
          <div className="login-brand">
            {renderBrandMark('login-brand-mark')}
            <div>
              <p className="eyebrow">{t('Server Management Panel')}</p>
              <h1>{panelSettings.app_name || 'BPanel'}</h1>
            </div>
          </div>
          <LanguageToggle language={language} onChange={changeLanguage}/>
          <ThemeToggle theme={theme} onToggle={toggleTheme}/>
        </div>
        <div className="login-form">
          <input value={username} onChange={e => setUsername(e.target.value)} placeholder={t('Username')} autoComplete="username" />
          <input value={password} onChange={e => setPassword(e.target.value)} placeholder={t('Password')} type="password" autoComplete="current-password" onKeyDown={e => { if (e.key === 'Enter') login(); }} />
          {passkeyPrompt && !needsTwoFactor && <div className="info-box">
            <p className="hint">{t('Touch your passkey to sign in.')}</p>
            <div className="site-app-form-actions">
              <button disabled={!!loading} onClick={() => usePasskey(passkeyPrompt.options)}><KeyRound size={14}/>{t('Try the passkey again')}</button>
              {/* A passkey belongs to one hostname. Reaching the panel by
                  another name offers nothing, so the app has to stay in reach. */}
              {passkeyPrompt.canUseOtp && <button className="secondary-light" disabled={!!loading} onClick={() => { setNeedsTwoFactor(true); setPasskeyPrompt(null); setNotice(t('Enter the code from your authenticator app.')); }}>{t('Use a code instead')}</button>}
            </div>
          </div>}
          {needsTwoFactor && <input value={otpCode} onChange={e => setOtpCode(e.target.value)} placeholder={t('Authentication code')} inputMode="numeric" autoComplete="one-time-code" onKeyDown={e => { if (e.key === 'Enter') login(); }} />}
          <label className="login-remember">
            <input type="checkbox" checked={rememberMe} onChange={e => setRememberMe(e.target.checked)} />{t('Keep me signed in for 30 days')}</label>
          {/* Not onClick={login}: that hands login() the click event as its
              passkey argument, so every click sent passkey=[object Object]
              and an account without two-factor was refused with "no second
              factor configured". Only Enter in a field ever worked. */}
          <button disabled={!!loading || !username || !password} onClick={() => login()}>{loading ? t('Logging in...') : t('Login')}</button>
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
      <aside className={`sidebar ${mobileMenuOpen ? 'open' : ''}`} role="navigation" aria-label={t('Main navigation')}>
        <div className="sidebar-head">
          <div className="sidebar-brand">
            {renderBrandMark()}
            <div>
              <strong>{panelSettings.app_name || 'BPanel'}</strong>
              <small>{t('Server Panel')}</small>
            </div>
          </div>
          <button className="sidebar-close" onClick={() => setMobileMenuOpen(false)} aria-label={t('Close menu')}><X size={18}/></button>
        </div>
        <nav className="sidebar-nav">
          {navSections.map(section => <div className="sidebar-section" key={section.key}>
            {section.title && <p className="sidebar-section-title">{t(section.title)}</p>}
            {section.items.map(([key, label, Icon]) => <button key={key} type="button" className={navPage === key ? 'active' : ''} onClick={() => navigateToPage(key)} aria-current={navPage === key ? 'page' : undefined}>
              <Icon size={16}/><span>{t(label)}</span>
            </button>)}
          </div>)}
        </nav>
        {appVersion && <div className="sidebar-version">v{appVersion}</div>}
      </aside>
      <div className="content">
        <section className="topbar">
          <button className="mobile-nav-toggle" onClick={() => setMobileMenuOpen(o => !o)} aria-expanded={mobileMenuOpen} aria-label={t('Toggle navigation')}>
            <Menu size={20}/><span><ActiveIcon size={17}/>{t(activeNavItem?.[1] || 'Menu')}</span>
          </button>
          <div className="page-title">
            <h1>{activeNavItem?.[1] ? t(activeNavItem[1]) : (panelSettings.app_name || 'BPanel')}</h1>
          </div>
          {/* The page title, then one account menu - profile, account security
              and sign out live in it, as they do in OPanel. */}
          <div className="top-actions">
            <LanguageToggle language={language} onChange={changeLanguage}/>
            <ThemeToggle theme={theme} onToggle={toggleTheme}/>
            <div className="user-menu" ref={userMenuRef}>
              <button type="button" className="user-menu-trigger" onClick={() => setUserMenuOpen(open => !open)} aria-haspopup="menu" aria-expanded={userMenuOpen} title={t('Logged in as')}>
                <span className="user-avatar" aria-hidden="true">{(currentUser?.username || username || '?').slice(0, 1).toUpperCase()}</span>
                <span className="user-menu-name">{currentUser?.username || username}</span>
                <ChevronDown size={14} className="user-menu-chevron"/>
              </button>
              {userMenuOpen && <div className="user-menu-panel" role="menu">
                <div className="user-menu-head">
                  <strong>{accountLabel}</strong>
                  <small>{currentUser?.email || t(roleLabel(currentUser?.role))}</small>
                </div>
                <button type="button" role="menuitem" onClick={() => { setUserMenuOpen(false); navigateToPage('security'); }}><LockKeyhole size={15}/>{t('Account security')}</button>
                <button type="button" role="menuitem" className="user-menu-logout" onClick={() => { setUserMenuOpen(false); logout(); }}><LogOut size={15}/>{t('Logout')}</button>
              </div>}
            </div>
          </div>
        </section>
        <div className="content-body">
          {renderPage()}
          {loading && <div className="loading"><span></span>{t(loading)}</div>}
        </div>
      </div>
    </section>
    {renderNotifications()}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
