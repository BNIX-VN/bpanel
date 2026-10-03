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
import { Archive, ArchiveRestore, ArrowLeft, Ban, Bot, Boxes, Check, ChevronDown, Clock, Code2, Copy, Cpu, Database, Dices, ExternalLink, Eye, FileText, FolderOpen, Globe, HardDrive, Home, Image, KeyRound, Lock, LogIn, LogOut, MemoryStick, Menu, Moon, MoveRight, Network, Pencil, Save, Search, Server, Settings as SettingsIcon, Shield, Sun, Trash2, TerminalIcon, Users, X, RefreshCw, Plus, Download, Upload, Play, Square, RotateCcw, AlertCircle, Activity, BrickWall, Bug, LockKeyhole, PackageOpen, ScrollText, ShieldAlert, CheckCircle, Zap, Bell, Mail, Send, Cloud, Inbox, Forward, ShieldCheck } from 'lucide-react';
import { Terminal } from './components/Terminal';
import { LANGUAGES, t, useLanguage } from './i18n.js';
import './shared/style.css';
import './shared/brand.css';
import './shared/ui.css';
import './shared/file-manager.css';
import './bpanel.css';

const API = import.meta.env.VITE_API_URL || '/api';
// Common cron schedules, offered as a dropdown next to the raw expression.
const CRON_PRESETS = [
  ['* * * * *', 'Every minute'],
  ['*/5 * * * *', 'Every 5 minutes'],
  ['*/15 * * * *', 'Every 15 minutes'],
  ['*/30 * * * *', 'Every 30 minutes'],
  ['0 * * * *', 'Every hour'],
  ['0 */6 * * *', 'Every 6 hours'],
  ['0 0 * * *', 'Daily at 00:00'],
  ['0 2 * * *', 'Daily at 02:00'],
  ['0 0 * * 0', 'Weekly, Sunday 00:00'],
  ['0 0 1 * *', 'Monthly, day 1 at 00:00'],
];
const normalizeCron = value => String(value || '').trim().split(/\s+/).join(' ');
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
  'panel-settings': '/panel-settings',
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
  notifications: '/notifications',
  dns: '/dns',
  mail: '/email',
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

function ThemeToggle({ theme, onToggle, className = '', size = 16 }) {
  const label = t('Toggle dark mode');
  return <button type="button" className={className} onClick={onToggle} aria-label={label} title={label}>
    {theme === 'dark' ? <Sun size={size}/> : <Moon size={size}/>}
  </button>;
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
  // As in OPanel: one button showing the language in use; a click switches
  // to the other one.
  const next = language === 'vi' ? 'en' : 'vi';
  const label = t('Switch to {language}', { language: LANGUAGES.find(([code]) => code === next)?.[1] || next });
  return <button type="button" className={className} onClick={() => onChange(next)} aria-label={label} title={label}>
    <span className="lang-code">{language === 'vi' ? 'VI' : 'EN'}</span>
  </button>;
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
  ['/api-token', 'panel-settings'],
  ['/api-tokens', 'panel-settings'],
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
// DNS Manager addon, laid out like OPanel's: the record types, the TTLs the
// form offers, and an example value for each type.
const DNS_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA'];
const DNS_TTLS = [60, 300, 900, 1800, 3600, 14400, 43200, 86400];
const DNS_PLACEHOLDERS = {
  A: '203.0.113.10', AAAA: '2001:db8::10', CNAME: 'target.example.com', MX: 'mail.example.com',
  TXT: 'v=spf1 mx -all', NS: 'ns1.example.net', SRV: '5 5060 sip.example.com', CAA: '0 issue letsencrypt.org',
};
const emptyDnsRecord = () => ({ type: 'A', name: '', value: '', priority: '', ttl: '' });
// The SPF part of the smarthosts customers use most.
const MAIL_SPF_INCLUDES = ['include:spf.smtp2go.com', 'include:mailgun.org', 'include:sendgrid.net', 'include:amazonses.com',
  'include:spf.brevo.com', 'include:spf.mandrillapp.com', 'include:_spf.google.com', 'include:spf.protection.outlook.com'];


const SITE_APP_KINDS = [
  ['node', 'Node.js', 'BPanel installs dependencies and keeps the process running under systemd.'],
  ['docker', 'Container', 'BPanel pulls the image and runs it, published on loopback only.'],
  ['compose', 'Docker Compose', 'Paste your project’s docker-compose.yml. BPanel checks it and runs a file it generates from what it accepted.'],
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
    // "Line 3: <a sentence the dictionary knows>" - the DNS template's check.
    const line = cleaned.match(/^Line (\d+): (.+)$/s);
    if (line) return t('Line {n}: {reason}', { n: line[1], reason: t(line[2]) });
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
  const [createSslManual, setCreateSslManual] = useState({ certificate: '', private_key: '', ca_bundle: '' }); // the Manual tab's paste-in
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
  const [newDatabase, setNewDatabase] = useState({ db_name: '', db_user: '', db_password: '' });
  const [createdDbInfo, setCreatedDbInfo] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [users, setUsers] = useState([]);
  const [packages, setPackages] = useState([]);
  const [userTab, setUserTab] = useState('list');
  const [resourceUsage, setResourceUsage] = useState(null);
  const [dashSummary, setDashSummary] = useState(null);
  // Notifications addon: my own settings, and (administrators) the server's.
  const [notifyMe, setNotifyMe] = useState(null);
  const [notifySettings, setNotifySettings] = useState(null);
  const [notifyLog, setNotifyLog] = useState([]);
  const [showNotifyLog, setShowNotifyLog] = useState(false);
  const [notifyLogStatus, setNotifyLogStatus] = useState('');
  const [notifyLogPage, setNotifyLogPage] = useState(1);
  const [telegramLink, setTelegramLink] = useState(null);
  const [smtpForm, setSmtpForm] = useState({ host: '', port: 587, security: 'starttls', username: '', password: '', from_email: '', from_name: 'BPanel' });
  const [botTokenInput, setBotTokenInput] = useState('');
  const [adminChatInput, setAdminChatInput] = useState('');
  const [telegramChats, setTelegramChats] = useState(null);
  const [myChatInput, setMyChatInput] = useState('');
  const [notifyLimits, setNotifyLimits] = useState({ disk_percent: 90, ssl_days: 7, language: 'vi' });
  const [serviceStates, setServiceStates] = useState({});
  const [serviceNames, setServiceNames] = useState(DEFAULT_SERVICE_NAMES);
  const [backupTab, setBackupTab] = useState('website');
  // An old /api-tokens link opens the tab the tokens now live on.
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
  // Restore, DirectAdmin's way: a source ('local', 'target:<id>' or
  // 'remote'), another server's details when that is the source, what the
  // source holds, which users are ticked, and the job restoring them.
  const [restoreSource, setRestoreSource] = useState('local');
  const [restoreTargetId, setRestoreTargetId] = useState('');
  const [restoreRemote, setRestoreRemote] = useState({ protocol: 'sftp', host: '', port: '', username: '', password: '', path: '/' });
  const [restoreListing, setRestoreListing] = useState(null);
  const [restoreChoice, setRestoreChoice] = useState({});
  const [restorePicks, setRestorePicks] = useState([]);
  const [restoreFilter, setRestoreFilter] = useState('');
  const [restoreJob, setRestoreJob] = useState(null);
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
  // Which schedule pickers are on "Custom…", by picker key.
  const [customSchedules, setCustomSchedules] = useState({});
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
  // The password dialog: an extra account's (account set), or the main
  // login's (account null), which the panel password and 2FA code confirm.
  const [sftpPasswordFor, setSftpPasswordFor] = useState(null);
  const [showCreateSftp, setShowCreateSftp] = useState(false);
  const [siteApps, setSiteApps] = useState({ items: [], limit: 0, used: 0, memory_ceiling_mb: 512, port_range: [21000, 21999] });
  // Optional features. Until this has loaded nothing addon-owned is offered, so
  // a slow first request cannot flash a section that turns out not to be there.
  const [addons, setAddons] = useState({ items: [], can_manage: false, loaded: false });
  // The addon card whose details and panel are open on the Addons page.
  const [addonOpen, setAddonOpen] = useState('');
  // Demo mode addon: the accounts the login page offers, and the form that picks them.
  const [demoAccess, setDemoAccess] = useState({ enabled: false, accounts: [] });
  const [demoSettings, setDemoSettings] = useState(null);
  // DNS Manager addon: the zones, one zone's records, the settings.
  const [dnsInfo, setDnsInfo] = useState(null);
  const [dnsTab, setDnsTab] = useState('zones');
  const [dnsZones, setDnsZones] = useState(null);
  const [dnsQuery, setDnsQuery] = useState('');
  const [dnsPage, setDnsPage] = useState(1);
  const [dnsZone, setDnsZone] = useState(null);
  const [dnsDelegation, setDnsDelegation] = useState(null);
  const [dnsRecordForm, setDnsRecordForm] = useState(emptyDnsRecord);
  const [dnsRecordEdit, setDnsRecordEdit] = useState(null);
  const [dnsRecordFilter, setDnsRecordFilter] = useState('');
  const [dnsSettings, setDnsSettings] = useState(null);
  const [dnsNewZone, setDnsNewZone] = useState({ name: '', owner_id: '' });
  // Email: domains, mailboxes and forwarders, and for administrators the
  // relays, the spam filter and the mail server.
  const [mailInfo, setMailInfo] = useState(null);
  const [mailTab, setMailTab] = useState('mailboxes');
  const [mailFilter, setMailFilter] = useState({ domain_id: '', q: '' });
  const [mailPage, setMailPage] = useState(1);
  const [mailboxList, setMailboxList] = useState(null);
  const [forwarderList, setForwarderList] = useState(null);
  const [showCreateMailbox, setShowCreateMailbox] = useState(false);
  const [mailboxForm, setMailboxForm] = useState({ domain_id: '', local_part: '', password: '', quota_mb: '' });
  const [showCreateForwarder, setShowCreateForwarder] = useState(false);
  const [forwarderForm, setForwarderForm] = useState({ domain_id: '', local_part: '', destinations: '' });
  const [mailboxEdit, setMailboxEdit] = useState(null);
  const [forwarderEdit, setForwarderEdit] = useState(null);
  const [mailDomainForm, setMailDomainForm] = useState({ domain: '', owner_id: '' });
  const [catchAllDraft, setCatchAllDraft] = useState({});
  const [mailDns, setMailDns] = useState(null);
  const [mailRelays, setMailRelays] = useState(null);
  const [relayForm, setRelayForm] = useState(null);
  const [relayTestTo, setRelayTestTo] = useState('');
  const [relayTestLines, setRelayTestLines] = useState(null);
  const [rspamdView, setRspamdView] = useState('history');
  const [rspamdStat, setRspamdStat] = useState(null);
  const [rspamdHistory, setRspamdHistory] = useState(null);
  const [rspamdFilter, setRspamdFilter] = useState({ q: '', action: '', page: 1 });
  const [rspamdLog, setRspamdLog] = useState(null);
  const [rspamdLogQuery, setRspamdLogQuery] = useState({ q: '', lines: 500 });
  const [eximLog, setEximLog] = useState(null);
  const [eximLogQuery, setEximLogQuery] = useState({ q: '', lines: 500 });
  const [mailSettings, setMailSettings] = useState(null);
  const [mailSettingsForm, setMailSettingsForm] = useState(null);
  const [demoDraft, setDemoDraft] = useState({ admin: { username: '', password: '' }, customer: { username: '', password: '' } });
  const [f2b, setF2b] = useState(null);
  const [f2bBanned, setF2bBanned] = useState({ items: [], total: 0, offset: 0, limit: 50 });
  // Firewall > View list: the blocked and allowed addresses on a sub-page of
  // their own, so the page stays one screen tall however many there are.
  const [showFirewallIpList, setShowFirewallIpList] = useState(false);
  const [firewallIpQuery, setFirewallIpQuery] = useState('');
  const [firewallIpAction, setFirewallIpAction] = useState('');
  const [firewallIpPage, setFirewallIpPage] = useState(1);
  const [siteAppDraft, setSiteAppDraft] = useState(EMPTY_SITE_APP_DRAFT);
  const [createSiteAppId, setCreateSiteAppId] = useState('');
  // File manager target: empty means the selected website, otherwise an app.
  const [fileAppId, setFileAppId] = useState(() => standaloneEditor?.appId || '');
  const [siteAppLog, setSiteAppLog] = useState(null);
  const [composePlan, setComposePlan] = useState(null);
  const [siteAppEdit, setSiteAppEdit] = useState(null);
  const [siteAppEditPlan, setSiteAppEditPlan] = useState(null);
  const [siteRuntimes, setSiteRuntimes] = useState({ docker: { installed: false }, node_majors: [], allowed_registries: [] });
  const [showCreateApp, setShowCreateApp] = useState(false);
  // The "Add Node version" dialog: null when closed, else the major typed.
  const [nodeMajorDraft, setNodeMajorDraft] = useState(null);
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
  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10, reseller_id: '', pool_user_limit: 0, pool_website_limit: 0, pool_storage_limit_mb: 0, pool_mail_accounts_limit: 0, pool_app_limit: 0 });
  // A reseller's share of the server and what it has handed out (GET /users/pool).
  const [resellerPool, setResellerPool] = useState(null);
  // Who a new website is for: '' is the account creating it.
  const [siteOwnerId, setSiteOwnerId] = useState('');
  const [editingUser, setEditingUser] = useState(null);
  const [editingUserForm, setEditingUserForm] = useState({ email: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10, new_password: '', confirm_password: '' });
  const [newPackage, setNewPackage] = useState({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10 });
  const [editingPackageId, setEditingPackageId] = useState('');
  const [editingPackageForm, setEditingPackageForm] = useState({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10 });
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
  const [wafGlobalRules, setWafGlobalRules] = useState('');
  const [wafCustomRules, setWafCustomRules] = useState('');
  const [selectedWafWebsiteId, setSelectedWafWebsiteId] = useState('');
  const [wafSiteConfig, setWafSiteConfig] = useState(null);
  const [httpFloodForm, setHttpFloodForm] = useState({ http_flood_enabled: false, ...HTTP_FLOOD_DEFAULTS });
  // Bot blocking. The list is free text so a whole blocklist can be pasted in
  // one go; the backend splits and cleans it. Targets are the websites the
  // paste is applied to - it is normally the same list on many sites.
  const [botBlocks, setBotBlocks] = useState(null);
  // The global list as typed, one bot per line; the backend splits and
  // cleans it.
  const [globalBotText, setGlobalBotText] = useState('');
  const [crs, setCrs] = useState(null);
  // The list for the one site being configured.
  const [siteBotText, setSiteBotText] = useState('');
  const [wafAccessLogFilters, setWafAccessLogFilters] = useState(WAF_ACCESS_LOG_DEFAULTS);
  const [wafAccessLogs, setWafAccessLogs] = useState({ items: [], total: 0, scanned: 0, missing: [], generated_at: '' });
  const [assignUserId, setAssignUserId] = useState('');
  const [assignWebsiteId, setAssignWebsiteId] = useState('');
  // What moves with the website being assigned: its app and its databases.
  const [assignPreview, setAssignPreview] = useState(null);
  const [assignDbId, setAssignDbId] = useState('');
  const [assignDbUserId, setAssignDbUserId] = useState('');
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
  // A run from the history, read as a sub-page of the scanner.
  const [malwareDetailJob, setMalwareDetailJob] = useState(null);
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
  // The Auto-tune recommendation card, opened by its button as in OPanel.
  const [phpTuneOpen, setPhpTuneOpen] = useState(false);
  const [panelSettingsForm, setPanelSettingsForm] = useState({ app_name: 'BPanel', panel_hostname: '', panel_port: 2222, ssl_enabled: false });
  const [apiTokens, setApiTokens] = useState([]);
  const [newApiToken, setNewApiToken] = useState({ name: 'WHMCS', allowed_ips: '' });
  const [createdApiToken, setCreatedApiToken] = useState('');
  const [appVersion, setAppVersion] = useState('');
  const [panelLogoFile, setPanelLogoFile] = useState(null);
  const [panelFaviconFile, setPanelFaviconFile] = useState(null);
  const [adminAccountForm, setAdminAccountForm] = useState({ email: '', current_password: '', password: '', confirm_password: '', code: '' });
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [panelSettingsTab, setPanelSettingsTab] = useState(() => (/^\/api-tokens?\/?$/i.test(window.location.pathname) ? 'api' : 'general'));
  const [updatesStatus, setUpdatesStatus] = useState(null);
  const [showUpdateLog, setShowUpdateLog] = useState(false);
  const [osUpdating, setOsUpdating] = useState(false);
  const [panelUpdating, setPanelUpdating] = useState(false);
  const [panelUpdateLog, setPanelUpdateLog] = useState([]);
  const panelUpdateInterval = useRef(null);
  const [osAutoUpdate, setOsAutoUpdate] = useState({ enabled: true, mode: 'security', auto_reboot: false });
  const noticeTimer = useRef(null);
  const isAdmin = currentUser?.role === 'admin';
  // A reseller manages its customers and packages, never the server.
  const isReseller = currentUser?.role === 'reseller';
  const canManageUsers = isAdmin || isReseller;

  useEffect(() => {
    setAssignPreview(null);
    if (!assignWebsiteId || !isAdmin) return undefined;
    let cancelled = false;
    request(`/websites/${assignWebsiteId}/transfer-preview`, { silent: true })
      .then(data => { if (!cancelled && data) setAssignPreview(data); });
    return () => { cancelled = true; };
  }, [assignWebsiteId, isAdmin]);

  // Assigning a database needs the list of users, which only the Users page loads.
  useEffect(() => {
    if (page === 'databases' && isAdmin && users.length === 0) loadUsers();
  }, [page, isAdmin]);
  const mcpAddonInstalled = !!addons.items.find(item => item.slug === 'mcp')?.installed;
  const notificationsAddonInstalled = !!addons.items.find(item => item.slug === 'notifications')?.installed;
  const malwareAddonInstalled = !!addons.items.find(item => item.slug === 'malware')?.installed;
  const dnsAddonInstalled = !!addons.items.find(item => item.slug === 'dns')?.installed;
  const mailAddonInstalled = !!addons.items.find(item => item.slug === 'mail')?.installed;
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
    // The sidebar's DNS Manager opens the list, not the zone last looked at.
    if (nextPage === 'dns') { setDnsZone(null); setDnsTab('zones'); }
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

  async function login(passkeyAssertion = '', credentials = null) {
    try {
      setError('');
      setLoading('Logging in...');
      // credentials: a demo account's button on the login page, which signs in
      // without the visitor typing what the button already shows.
      if (credentials) setUsername(credentials.username);
      const body = new URLSearchParams(credentials || { username, password });
      // An otp and a passkey are never sent together: the customer either used
      // the key or chose the app.
      if (otpCode && !credentials) body.set('otp', otpCode);
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

  function openProfileModal() {
    setAdminAccountForm({ email: currentUser?.email || '', current_password: '', password: '', confirm_password: '', code: '' });
    setShowProfileModal(true);
  }

  async function saveProfileEmail() {
    const email = String(adminAccountForm.email || '').trim();
    const data = await request('/panel-settings/admin-account', { method: 'PATCH', body: JSON.stringify({ email }) }, t('Saving admin account...'));
    if (!data) return;
    await loadCurrentUser({ clearOnUnauthorized: false });
    setNotice(data.message || t('Email updated.'));
  }

  async function changeMyPassword() {
    const payload = { password: adminAccountForm.password, current_password: adminAccountForm.current_password };
    if (currentUser?.totp_enabled) payload.code = String(adminAccountForm.code || '').trim();
    const data = await request(`/users/${currentUser.id}/password`, { method: 'POST', body: JSON.stringify(payload) }, t('Changing password...'));
    if (!data) return;
    setAdminAccountForm(prev => ({ ...prev, current_password: '', password: '', confirm_password: '', code: '' }));
    setShowProfileModal(false);
    setNotice(data.message || t('Password changed.'));
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
    const dbData = await request('/databases');
    if (dbData) setDatabases(dbData);
    if (refreshedUser?.role === 'admin') {
      await loadPhpVersions();
      await loadPackages();
    }
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

  // The whole list: the page filters it as you type, as OPanel's does.
  async function loadDatabases(showLoading = false) {
    const data = await request('/databases', {}, showLoading ? 'Loading databases...' : '');
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
    if (!confirm(t('Delete API token {name}? WHMCS using it stops working at once.', { name: token.name }))) return;
    const data = await request(`/provisioning/v1/tokens/${token.id}`, { method: 'DELETE' }, t('Deleting token...'));
    if (data) {
      setNotice(t('API token {name} deleted.', { name: token.name }));
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

  async function loadResellerPool() {
    const data = await request('/users/pool', { silent: true });
    if (data) setResellerPool(data);
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
  async function loadNotifyMe() {
    const data = await request('/notifications/me', { silent: true });
    if (data) setNotifyMe(data);
  }

  // The switch moves when it is clicked, not when the server answers; a
  // refusal puts back what the server holds.
  async function saveNotifyMe(changes) {
    setNotifyMe(prev => (prev ? { ...prev, ...changes } : prev));
    const data = await request('/notifications/me', { method: 'PUT', body: JSON.stringify(changes) });
    if (data) setNotifyMe(data); else loadNotifyMe();
  }

  function toggleNotifyEvent(key, on) {
    const muted = new Set(notifyMe?.muted || []);
    if (on) muted.delete(key); else muted.add(key);
    saveNotifyMe({ muted: [...muted] });
  }

  async function startTelegramLink() {
    const data = await request('/notifications/me/telegram/link', { method: 'POST' });
    if (data) setTelegramLink(data);
  }

  async function verifyTelegramLink() {
    const data = await request('/notifications/me/telegram/verify', { method: 'POST' }, t('Checking...'));
    if (!data) return;
    setNotifyMe(data);
    if (data.telegram_linked) {
      setTelegramLink(null);
      setNotice(t('Telegram connected.'));
    } else {
      setError(t('The bot has not received your /start message yet. Send it, then press Check again.'));
    }
  }

  async function unlinkTelegram() {
    const data = await request('/notifications/me/telegram', { method: 'DELETE' });
    if (data) { setNotifyMe(data); setNotice(t('Telegram disconnected.')); }
  }

  async function sendNotifyTest(channel) {
    const data = await request('/notifications/test', { method: 'POST', body: JSON.stringify({ channel }) }, t('Sending...'));
    if (data) setNotice(t('Test sent to {target}.', { target: data.sent_to }));
    if (isAdmin) loadNotifyLog();
  }

  function applyNotifySettings(data) {
    setNotifySettings(data);
    setSmtpForm({ ...data.smtp, password: '' });
    setBotTokenInput('');
    setAdminChatInput(data.telegram.chat_id || '');
    setTelegramChats(null);
    setNotifyLimits({ ...data.thresholds, language: data.language });
  }

  async function loadNotifySettings() {
    const data = await request('/notifications/settings', { silent: true });
    if (data) applyNotifySettings(data);
  }

  async function saveNotifySettings(body, done) {
    const data = await request('/notifications/settings', { method: 'PUT', body: JSON.stringify(body) }, t('Saving...'));
    if (!data) return;
    applyNotifySettings(data);
    setNotice(done);
    loadNotifyMe();
  }

  async function findTelegramChats() {
    const data = await request('/notifications/telegram/chats', {}, t('Checking...'));
    if (Array.isArray(data)) setTelegramChats(data);
  }

  async function loadNotifyLog() {
    const data = await request('/notifications/log', { silent: true });
    if (Array.isArray(data)) setNotifyLog(data);
  }

  async function loadDashboardSummary() {
    const data = await request('/dashboard/summary', { silent: true });
    if (data) setDashSummary(data);
  }

  async function loadResourceUsage() {
    const data = await request('/services/resource-usage');
    if (data) setResourceUsage(data);
  }

  const POOL_FIELDS = ['pool_user_limit', 'pool_website_limit', 'pool_storage_limit_mb', 'pool_mail_accounts_limit', 'pool_app_limit'];

  async function createUser() {
    const payload = {
      username: newUser.username, email: newUser.email, password: newUser.password,
      // A reseller's new accounts are always its own customers.
      role: isAdmin ? newUser.role : 'end_user',
      package_id: newUser.package_id ? Number(newUser.package_id) : null,
      website_limit: Number(newUser.website_limit),
      storage_limit_mb: Number(newUser.storage_limit_mb),
      sftp_accounts_limit: Number(newUser.sftp_accounts_limit || 0),
      mail_accounts_limit: Number(newUser.mail_accounts_limit || 0),
    };
    if (isAdmin && newUser.role === 'end_user' && newUser.reseller_id) payload.reseller_id = Number(newUser.reseller_id);
    if (isAdmin && newUser.role === 'reseller') POOL_FIELDS.forEach(field => { payload[field] = Number(newUser[field]) || 0; });
    const data = await request('/users', { method: 'POST', body: JSON.stringify(payload) }, t('Creating user...'));
    if (data) {
      setNotice(`Created user ${data.username}`);
      setNewUser({ username: '', email: '', password: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10, reseller_id: '', pool_user_limit: 0, pool_website_limit: 0, pool_storage_limit_mb: 0, pool_mail_accounts_limit: 0, pool_app_limit: 0 });
      await loadUsers();
      if (isReseller) await loadResellerPool();
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
      mail_accounts_limit: selected ? (selected.mail_accounts_limit ?? 10) : 10,
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
      mail_accounts_limit: selected ? (selected.mail_accounts_limit ?? 10) : 10,
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
      mail_accounts_limit: user.mail_accounts_limit ?? 10,
      reseller_id: user.reseller_id ? String(user.reseller_id) : '',
      pool_user_limit: user.pool_user_limit ?? 0,
      pool_website_limit: user.pool_website_limit ?? 0,
      pool_storage_limit_mb: user.pool_storage_limit_mb ?? 0,
      pool_mail_accounts_limit: user.pool_mail_accounts_limit ?? 0,
      pool_app_limit: user.pool_app_limit ?? 0,
      new_password: '',
      confirm_password: '',
    });
  }

  function cancelEditingUser() {
    setEditingUser(null);
    setEditingUserForm({ email: '', role: 'end_user', package_id: '', website_limit: 5, storage_limit_mb: 1024, new_password: '', confirm_password: '' });
    setNewPackage({ name: '', website_limit: 5, storage_limit_mb: 1024 });
    setEditingPackageId('');
    setEditingPackageForm({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10 });
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
    // A new password is optional; when one is typed it is checked before
    // anything is saved, so a typo does not leave half the change applied.
    const newPassword = editingUserForm.new_password || '';
    if (newPassword && newPassword.length < 12) { setError(t('Password must be at least 12 characters.')); return; }
    if (newPassword && newPassword !== editingUserForm.confirm_password) { setError(t('Passwords do not match.')); return; }
    const payload = {
      email: editingUserForm.email.trim(),
      package_id: editingUserForm.package_id ? Number(editingUserForm.package_id) : null,
      website_limit: websiteLimit,
      storage_limit_mb: storageLimitMb,
      sftp_accounts_limit: Number(editingUserForm.sftp_accounts_limit || 0),
      mail_accounts_limit: Number(editingUserForm.mail_accounts_limit || 0),
    };
    if (isAdmin) {
      if (editingUser.id !== currentUser?.id) payload.role = editingUserForm.role;
      if (editingUserForm.role === 'end_user') payload.reseller_id = Number(editingUserForm.reseller_id) || 0;
      if (editingUserForm.role === 'reseller') POOL_FIELDS.forEach(field => { payload[field] = Number(editingUserForm[field]) || 0; });
    }
    const data = await request(`/users/${editingUser.id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }, `Updating ${editingUser.username}...`);
    if (data) {
      if (data.id === currentUser?.id) setCurrentUser(prev => ({ ...prev, ...data }));
      if (newPassword && !(await submitPasswordChange(editingUser, newPassword))) {
        setNotice(t('User updated but password was not changed.'));
        cancelEditingUser();
        await loadUsers();
        return;
      }
      setNotice(`Updated user ${data.username}.`);
      cancelEditingUser();
      await loadUsers();
      if (isReseller) await loadResellerPool();
    }
  }

  // Changing your own password asks for the current one (and the 2FA code);
  // an administrator sets anyone else's directly. True when it was changed.
  async function submitPasswordChange(user, password) {
    const payload = { password };
    if (user.id === currentUser?.id) {
      const currentPassword = prompt(t('Enter your current password to confirm:'));
      if (!currentPassword) return false;
      payload.current_password = currentPassword;
      if (currentUser?.totp_enabled) {
        const code = prompt(t('Enter your 2FA code:'));
        if (!code) return false;
        payload.code = code.trim();
      }
    }
    const data = await request(`/users/${user.id}/password`, { method: 'POST', body: JSON.stringify(payload) }, t('Changing password for {name}...', { name: user.username }));
    return !!data;
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
      body: JSON.stringify({ name: newPackage.name.trim(), website_limit: websiteLimit, storage_limit_mb: storageLimitMb, sftp_accounts_limit: Number(newPackage.sftp_accounts_limit || 0), mail_accounts_limit: Number(newPackage.mail_accounts_limit || 0) }),
    }, t('Creating package...'));
    if (data) {
      setNotice(`Created package ${data.name}.`);
      setNewPackage({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10 });
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
      mail_accounts_limit: item.mail_accounts_limit ?? 10,
    });
  }

  function cancelEditingPackage() {
    setEditingPackageId('');
    setEditingPackageForm({ name: '', website_limit: 5, storage_limit_mb: 1024, sftp_accounts_limit: 0, mail_accounts_limit: 10 });
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
      body: JSON.stringify({ name: editingPackageForm.name.trim(), website_limit: websiteLimit, storage_limit_mb: storageLimitMb, sftp_accounts_limit: Number(editingPackageForm.sftp_accounts_limit || 0), mail_accounts_limit: Number(editingPackageForm.mail_accounts_limit || 0) }),
    }, t('Updating package...'));
    if (data) {
      setNotice(`Updated package ${data.name}.`);
      cancelEditingPackage();
      await loadPackages();
      await loadUsers();
      if (isReseller) await loadResellerPool();
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

  // Ends a "Login as" session and restores the admin's own one, which the
  // server kept aside: no second login.
  async function returnToImpersonator() {
    const admin = currentUser?.impersonator;
    if (!admin) return;
    const data = await request('/auth/impersonation/return', { method: 'POST' }, t('Going back to {name}...', { name: admin }));
    if (data?.access_token) {
      setNotice(t('Back to {name}.', { name: admin }));
      await loadCurrentUser();
      navigateToPage('users');
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

  async function loadMalwareSchedule() {
    const data = await request('/malware/schedule', { silent: true }, '');
    if (data) {
      setMalwareSchedules(data);
      setMalwareSchedulesForm(data);
    }
  }

  // One schedule at a time, as each has its own section and Save button; the
  // other keeps whatever is being edited in it.
  async function saveMalwareSchedule(scope) {
    const entry = malwareSchedulesForm[scope] || {};
    if (scope === 'server' && entry.enabled && malwareScanStatus?.memory_warning) {
      if (!confirm(`${malwareScanStatus.memory_warning}\n\nSchedule the whole-server scan anyway?`)) return;
    }
    const body = { [scope]: { enabled: !!entry.enabled, weekday: Number(entry.weekday ?? 6), hour: Number(entry.hour ?? 3) } };
    const data = await request('/malware/schedule', { method: 'PUT', body: JSON.stringify(body) }, t('Saving scan schedule...'));
    if (data) {
      setMalwareSchedules(data);
      setMalwareSchedulesForm(prev => ({ ...prev, [scope]: data[scope] }));
      setNotice(data[scope]?.enabled ? t('Scheduled scan saved.') : t('Scheduled scan disabled.'));
    }
  }

  async function toggleMalwareRealtime(enabled) {
    if (enabled && !confirm(t('Turn on real-time protection? The panel watches website directories and scans new files as they appear. If it is not installed yet, the panel installs it (1-3 minutes).'))) return;
    const data = await request('/malware/realtime', { method: 'POST', body: JSON.stringify({ enabled }) },
      enabled ? 'Turning on real-time protection...' : 'Turning off...');
    if (data) { setMalwareScanStatus(data); setNotice(t(enabled ? 'Real-time protection is on (level 2).' : 'Real-time protection is off.')); }
  }

  async function toggleMalwareScanOnUpload(enabled) {
    if (enabled && !malwareScanStatus?.clamd_running && !confirm(
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

  async function openMalwareScanDetail(job) {
    setMalwareDetailJob(job);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    const data = await request(`/malware/jobs/${job.job_id}`, { silent: true }, '');
    if (data) setMalwareDetailJob(data);
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

  async function assignDatabaseToUser() {
    if (!assignDbId || !assignDbUserId) return;
    const data = await request(`/databases/${assignDbId}/owner`, { method: 'PATCH', body: JSON.stringify({ owner_id: Number(assignDbUserId) }) }, t('Assigning database...'));
    if (data) {
      const user = users.find(item => String(item.id) === String(assignDbUserId));
      setNotice(t('Assigned database {name} to {user}', { name: data.db_name, user: user?.username || assignDbUserId }));
      setAssignDbId('');
      await loadDatabases();
    }
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
    if (siteOwnerId) body.owner_id = Number(siteOwnerId);
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
      // Pasted into the form: installed on the new site straight away.
      if (createSslManual.certificate.trim() && createSslManual.private_key.trim()) {
        const form = new FormData();
        form.append('certificate_text', createSslManual.certificate);
        form.append('private_key_text', createSslManual.private_key);
        if (createSslManual.ca_bundle.trim()) form.append('ca_bundle_text', createSslManual.ca_bundle);
        const data = await request(`/websites/${id}/ssl/manual`, { method: 'POST', body: form }, t('Installing manual SSL...'));
        if (data) setCreateSslManual({ certificate: '', private_key: '', ca_bundle: '' });
        return;
      }
      // Left empty: send the operator to the SSL page for this site to
      // finish it there.
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

  async function loadDemoAccess() {
    // Public: an ordinary panel answers "not enabled" and the login page shows nothing.
    try {
      const res = await fetch(`${API}/demo-mode/public`, { credentials: 'include' });
      if (res.ok) setDemoAccess(await res.json());
    } catch {}
  }

  async function loadDemoSettings() {
    const data = await request('/demo-mode', { silent: true });
    if (!data) return;
    setDemoSettings(data);
    setDemoDraft({
      admin: data.accounts?.admin || { username: '', password: '' },
      customer: data.accounts?.customer || { username: '', password: '' },
    });
  }

  // --- DNS Manager, laid out like OPanel's: the zones, one zone, the settings ---
  const dnsPath = zone => `/dns/zones/${encodeURIComponent(zone.name)}`;

  async function loadDnsInfo() {
    const data = await request('/dns/overview', { silent: true });
    if (data) setDnsInfo(data);
    return data;
  }

  async function loadDnsZones(page = dnsPage) {
    const params = new URLSearchParams({ page: String(page), per_page: '50' });
    if (dnsQuery.trim()) params.set('q', dnsQuery.trim());
    const data = await request(`/dns/zones?${params}`, { silent: true });
    if (data) setDnsZones(data);
  }

  async function loadDnsSettings() {
    const data = await request('/dns/settings', { silent: true });
    if (data) setDnsSettings({ ...data, ns1: data.nameservers?.[0] || '', ns2: data.nameservers?.[1] || '' });
  }

  async function openDnsZone(zone) {
    if (page !== 'dns') navigateToPage('dns');
    setDnsTab('zones');
    setDnsZone({ zone, records: null });
    setDnsDelegation(null);
    setDnsRecordEdit(null);
    setDnsRecordFilter('');
    setDnsRecordForm(emptyDnsRecord());
    const data = await request(`${dnsPath(zone)}/records`);
    if (!data) { setDnsZone(null); return; }
    setDnsZone({ zone, records: data.records || [] });
    const check = await request(`${dnsPath(zone)}/delegation`, { silent: true });
    setDnsDelegation(check || { status: 'unknown', expected: [], found: [] });
  }

  function dnsRecordBody(form) {
    const withPriority = ['MX', 'SRV'].includes(form.type);
    return {
      name: String(form.name || '').trim() || '@',
      type: form.type,
      ttl: Number(form.ttl) || Number(dnsInfo?.default_ttl) || 3600,
      content: String(form.value ?? '').trim(),
      priority: withPriority ? (String(form.priority ?? '').trim() === '' ? 10 : Number(form.priority)) : null,
    };
  }

  // A record as the server listed it: how the server finds it again.
  function dnsRecordKey(record) {
    return { name: record.name, type: record.type, ttl: Number(record.ttl) || 3600, content: record.content, priority: record.priority ?? null };
  }

  function applyDnsRecords(data) {
    setDnsZone(prev => (prev ? { ...prev, records: data.records || [] } : prev));
  }

  async function addDnsRecord() {
    const data = await request(`${dnsPath(dnsZone.zone)}/records`, { method: 'POST', body: JSON.stringify(dnsRecordBody(dnsRecordForm)) }, t('Saving the record...'));
    if (!data) return;
    applyDnsRecords(data);
    setDnsRecordForm(prev => ({ ...prev, name: '', value: '', priority: '' }));
    setNotice(t('Record added.'));
  }

  async function saveDnsRecordEdit() {
    const { old, form } = dnsRecordEdit;
    const body = { original: dnsRecordKey(old), record: dnsRecordBody(form) };
    const data = await request(`${dnsPath(dnsZone.zone)}/records`, { method: 'PUT', body: JSON.stringify(body) }, t('Saving the record...'));
    if (!data) return;
    applyDnsRecords(data);
    setDnsRecordEdit(null);
    setNotice(t('Record saved.'));
  }

  async function deleteDnsRecord(record) {
    const question = record.mail
      ? t('The Email addon keeps this record for {domain} and writes it again when the email settings of {domain} change. Delete the {type} record of {name} anyway?', { domain: record.mail, type: record.type, name: record.name })
      : t('Delete the {type} record of {name}: {value}?', { type: record.type, name: record.name, value: record.value });
    if (!confirm(question)) return;
    const data = await request(`${dnsPath(dnsZone.zone)}/records/delete`, { method: 'POST', body: JSON.stringify(dnsRecordKey(record)) }, t('Deleting the record...'));
    if (!data) return;
    applyDnsRecords(data);
    if (dnsRecordEdit?.old?.content === record.content) setDnsRecordEdit(null);
    setNotice(t('Record deleted.'));
  }

  async function restoreDnsDefaults() {
    if (!confirm(t('Put back the records the panel manages for {zone}: nameservers, websites and email. Records you added are kept.', { zone: dnsZone.zone.name }))) return;
    const data = await request(`${dnsPath(dnsZone.zone)}/defaults`, { method: 'POST' }, t("Restoring the panel's records..."));
    if (!data) return;
    applyDnsRecords(data);
    setNotice(t("The panel's records are back in {zone}.", { zone: dnsZone.zone.name }));
  }

  async function deleteDnsZone(zone) {
    const typed = prompt(t('Every record of {zone} is deleted, and the domain stops resolving once its nameservers point here. Type the domain name to confirm.', { zone: zone.name }));
    if (typed === null) return;
    if (typed.trim().toLowerCase().replace(/\.$/, '') !== zone.name) { setError(t('The name did not match; nothing was deleted.')); return; }
    const data = await request(dnsPath(zone), { method: 'DELETE' }, t('Deleting the zone...'));
    if (!data) return;
    setNotice(t('Zone {zone} deleted.', { zone: zone.name }));
    setDnsZone(null);
    loadDnsZones();
  }

  async function addDnsZone() {
    const body = { name: dnsNewZone.name.trim(), owner_id: dnsNewZone.owner_id ? Number(dnsNewZone.owner_id) : null };
    const data = await request('/dns/zones', { method: 'POST', body: JSON.stringify(body) }, t('Saving...'));
    if (!data) return;
    setDnsNewZone({ name: '', owner_id: '' });
    loadDnsZones();
    openDnsZone({ name: data.zone });
  }

  async function syncDnsZones() {
    const data = await request('/dns/sync', { method: 'POST' }, t('Syncing...'));
    if (!data) return;
    setNotice(t('Every domain on the server has its DNS zone. New zones: {zones}, new records: {records}, owners corrected: {owners}.',
      { zones: data.zones.length, records: data.records.length, owners: data.owners.length }));
    loadDnsZones();
  }

  async function saveDnsSettings() {
    const f = dnsSettings;
    const body = {
      nameservers: [f.ns1, f.ns2].map(name => String(name || '').trim()).filter(Boolean),
      zone_ip: String(f.zone_ip || '').trim(),
      ttl: Number(f.ttl) || 3600,
      auto_zone: !!f.auto_zone,
      template: f.template || '',
    };
    const data = await request('/dns/settings', { method: 'PUT', body: JSON.stringify(body) }, t('Saving DNS settings...'));
    if (!data) return;
    setNotice(t('DNS settings saved.'));
    loadDnsSettings();
    loadDnsInfo();
    loadDnsZones();
  }

  // --- Email (OPanel's structure): domains, mailboxes, forwarders ---
  async function loadMailInfo() {
    const data = await request('/mail/overview', { silent: true });
    if (data) setMailInfo(data);
    return data;
  }

  function mailQuery(page) {
    const params = new URLSearchParams({ page: String(page), per_page: '50' });
    if (mailFilter.domain_id) params.set('domain_id', mailFilter.domain_id);
    if (mailFilter.q.trim()) params.set('q', mailFilter.q.trim());
    return params.toString();
  }

  async function loadMailboxes(page = mailPage) {
    const data = await request(`/mail/mailboxes?${mailQuery(page)}`, { silent: true });
    if (data) setMailboxList(data);
  }

  async function loadForwarders(page = mailPage) {
    const data = await request(`/mail/forwarders?${mailQuery(page)}`, { silent: true });
    if (data) setForwarderList(data);
  }

  function refreshMail() {
    loadMailInfo();
    if (mailTab === 'mailboxes') loadMailboxes();
    if (mailTab === 'forwarders') loadForwarders();
  }

  function mailPassword() {
    // The server wants at least one letter and one digit.
    let value = '';
    do { value = generateRandomPassword(16); } while (!/[A-Za-z]/.test(value) || !/\d/.test(value));
    return value;
  }

  function splitAddresses(text) {
    return String(text || '').split(/[\s,;]+/).map(item => item.trim()).filter(Boolean);
  }

  async function addMailDomain() {
    const domain = mailDomainForm.domain.trim().toLowerCase();
    if (!domain) return;
    const body = { domain };
    if (isAdmin && mailDomainForm.owner_id) body.owner_id = Number(mailDomainForm.owner_id);
    const data = await request('/mail/domains', { method: 'POST', body: JSON.stringify(body) }, t('Turning on email...'));
    if (data) {
      setMailDomainForm({ domain: '', owner_id: '' });
      setNotice(t('Email is on for {domain}. Publish its DNS records next.', { domain: data.domain }));
      await loadMailInfo();
      openMailDns(data);
    }
  }

  async function deleteMailDomain(domain) {
    const typed = prompt(t('This deletes every mailbox of {domain} with all its mail, and its forwarders. It cannot be undone.\n\nType the domain name to confirm:', { domain: domain.domain }));
    if (typed === null) return;
    if (typed.trim().toLowerCase() !== domain.domain) { setError(t('The name did not match; nothing was deleted.')); return; }
    const data = await request(`/mail/domains/${domain.id}?confirm=${encodeURIComponent(domain.domain)}`, { method: 'DELETE' }, t('Deleting...'));
    if (data) {
      setNotice(t('Email for {domain} deleted.', { domain: domain.domain }));
      if (mailFilter.domain_id === String(domain.id)) setMailFilter(prev => ({ ...prev, domain_id: '' }));
      refreshMail();
    }
  }

  async function saveCatchAll(domain) {
    const value = String(catchAllDraft[domain.id] ?? domain.catch_all ?? '').trim();
    const data = await request(`/mail/domains/${domain.id}`, { method: 'PUT', body: JSON.stringify({ catch_all: value }) }, t('Saving...'));
    if (data) {
      setNotice(value
        ? t('Mail to unknown addresses at {domain} now goes to {target}.', { domain: domain.domain, target: value })
        : t('Mail to unknown addresses at {domain} is now refused.', { domain: domain.domain }));
      setCatchAllDraft(prev => { const next = { ...prev }; delete next[domain.id]; return next; });
      loadMailInfo();
    }
  }

  async function rotateMailDkim(domain) {
    if (!confirm(t('Make a new DKIM key for {domain}?\n\nMail is signed with the new key at once, so update the DKIM record in DNS right away: until you do, receivers cannot verify the signature.', { domain: domain.domain }))) return;
    const data = await request(`/mail/domains/${domain.id}/dkim/rotate`, { method: 'POST' }, t('Creating a new key...'));
    if (data) { setNotice(t('New DKIM key created. Update the DKIM record.')); openMailDns(domain); }
  }

  async function toggleWebmailHost(domain, enabled) {
    if (enabled && !confirm(t("Serve webmail at webmail.{domain}?\n\nIts A record must already point at this server: a Let's Encrypt certificate is issued for it now.", { domain: domain.domain }))) return;
    if (!enabled && !confirm(t("Stop serving webmail at webmail.{domain}? Webmail stays available on the server's own address.", { domain: domain.domain }))) return;
    const data = await request(`/mail/domains/${domain.id}/webmail-host`, { method: 'POST', body: JSON.stringify({ enabled }) },
      enabled ? t('Issuing a certificate for webmail.{domain}...', { domain: domain.domain }) : t('Removing...'));
    if (data) {
      setNotice(enabled ? t('Webmail is now at https://webmail.{domain}/', { domain: domain.domain }) : t('webmail.{domain} removed.', { domain: domain.domain }));
      loadMailInfo();
    }
  }

  async function createMailbox() {
    const body = { domain_id: Number(mailboxForm.domain_id), local_part: mailboxForm.local_part.trim().toLowerCase(), password: mailboxForm.password };
    if (String(mailboxForm.quota_mb).trim() !== '') body.quota_mb = Number(mailboxForm.quota_mb);
    const data = await request('/mail/mailboxes', { method: 'POST', body: JSON.stringify(body) }, t('Creating mailbox...'));
    if (data) {
      setNotice(t('{address} created.', { address: data.address }));
      setMailboxForm(prev => ({ ...prev, local_part: '', password: '' }));
      setShowCreateMailbox(false);
      loadMailboxes();
      loadMailInfo();
    }
  }

  async function saveMailboxEdit() {
    const edit = mailboxEdit;
    const body = {};
    if (edit.password) body.password = edit.password;
    if (String(edit.quota_mb) !== String(edit.box.quota_mb)) body.quota_mb = Number(edit.quota_mb);
    if (!Object.keys(body).length) { setMailboxEdit(null); return; }
    const data = await request(`/mail/mailboxes/${edit.box.id}`, { method: 'PUT', body: JSON.stringify(body) }, t('Saving...'));
    if (data) { setNotice(t('{address} saved.', { address: data.address })); setMailboxEdit(null); loadMailboxes(); }
  }

  async function setMailboxEnabled(box, enabled) {
    if (!enabled && !confirm(t('Suspend {address}?\n\nIt keeps receiving mail, but nobody can sign in to it or send from it until it is resumed.', { address: box.address }))) return;
    const data = await request(`/mail/mailboxes/${box.id}`, { method: 'PUT', body: JSON.stringify({ enabled }) }, t('Saving...'));
    if (data) { setNotice(enabled ? t('{address} resumed.', { address: box.address }) : t('{address} suspended.', { address: box.address })); loadMailboxes(); }
  }

  async function deleteMailbox(box) {
    if (!confirm(t('Delete {address} and all of its mail?\n\nThis cannot be undone.', { address: box.address }))) return;
    const data = await request(`/mail/mailboxes/${box.id}`, { method: 'DELETE' }, t('Deleting...'));
    if (data) { setNotice(t('{address} deleted.', { address: box.address })); loadMailboxes(); loadMailInfo(); }
  }

  async function openWebmail(box) {
    // Opened inside the click so no pop-up blocker stops it; the signed link
    // arrives a moment later.
    const win = window.open('about:blank', '_blank');
    const data = await request(`/mail/mailboxes/${box.id}/webmail`, { method: 'POST' }, t('Opening webmail...'));
    if (data?.url) {
      if (win) { win.opener = null; win.location.href = data.url; } else window.location.href = data.url;
    } else if (win) {
      win.close();
    }
  }

  async function createForwarder() {
    const body = { domain_id: Number(forwarderForm.domain_id), local_part: forwarderForm.local_part.trim().toLowerCase(), destinations: splitAddresses(forwarderForm.destinations) };
    const data = await request('/mail/forwarders', { method: 'POST', body: JSON.stringify(body) }, t('Creating forwarder...'));
    if (data) {
      setNotice(t('{address} now forwards to {destinations}.', { address: data.address, destinations: data.destinations.join(', ') }));
      setForwarderForm(prev => ({ ...prev, local_part: '', destinations: '' }));
      setShowCreateForwarder(false);
      loadForwarders();
      loadMailInfo();
    }
  }

  async function saveForwarderEdit() {
    const data = await request(`/mail/forwarders/${forwarderEdit.item.id}`, { method: 'PUT', body: JSON.stringify({ destinations: splitAddresses(forwarderEdit.destinations) }) }, t('Saving...'));
    if (data) { setNotice(t('{address} saved.', { address: data.address })); setForwarderEdit(null); loadForwarders(); }
  }

  async function deleteForwarder(item) {
    if (!confirm(t('Delete the forwarder {address}?', { address: item.address }))) return;
    const data = await request(`/mail/forwarders/${item.id}`, { method: 'DELETE' }, t('Deleting...'));
    if (data) { setNotice(t('{address} deleted.', { address: item.address })); loadForwarders(); loadMailInfo(); }
  }

  function applyMailDnsView(domain, data) {
    setMailDns({ domain, records: data?.records || [], relay: data?.relay || null, hostedZone: data?.hosted_zone || '' });
  }

  async function openMailDns(domain) {
    setMailDns({ domain, records: null, relay: null });
    const data = await request(`/mail/domains/${domain.id}/dns`, { silent: true });
    applyMailDnsView(domain, data);
  }

  function dnsRecordsBody(rows) {
    return rows
      .filter(r => String(r.value || '').trim())
      .map(r => ({
        type: r.type,
        name: String(r.name || '@').trim() || '@',
        value: String(r.value).trim(),
        ...(r.type === 'MX' && String(r.priority ?? '').trim() !== '' ? { priority: Number(r.priority) } : {}),
      }));
  }

  async function saveDomainRelay(value) {
    const data = await request(`/mail/domains/${mailDns.domain.id}/relay`, { method: 'PUT', body: JSON.stringify({ relay: value }) }, t('Saving...'));
    if (data) { setNotice(t('Outgoing mail for {domain} saved.', { domain: mailDns.domain.domain })); applyMailDnsView(mailDns.domain, data); }
  }

  // --- Email: relays (administrators) ---
  async function loadMailRelays() {
    const data = await request('/mail/relays', { silent: true });
    if (data) setMailRelays(data);
  }

  function editRelay(relay) {
    setRelayForm(relay
      ? { ...relay, password: '', dns_records: (relay.dns_records || []).map(r => ({ ...r, priority: r.priority ?? '' })), make_default: false }
      : { name: '', host: '', port: 587, tls: 'starttls', username: '', password: '', spf_include: '', dns_records: [],
          make_default: !(mailRelays?.relays || []).length });
  }

  async function saveRelay() {
    const f = relayForm;
    const body = {
      name: f.name.trim(), host: f.host.trim(), port: Number(f.port) || 587, tls: f.tls,
      username: f.username.trim(), password: f.password, spf_include: f.spf_include.trim(),
      dns_records: dnsRecordsBody(f.dns_records), make_default: !!f.make_default,
    };
    const data = await request(f.id ? `/mail/relays/${f.id}` : '/mail/relays', { method: f.id ? 'PUT' : 'POST', body: JSON.stringify(body) }, t('Saving relay...'));
    if (data) { setMailRelays(data); setRelayForm(null); setNotice(t('Relay saved. Domains that use it need its DNS records.')); }
  }

  async function deleteRelay(relay) {
    if (!confirm(t('Delete the relay {name}?\n\nDomains that use it go back to the default relay.', { name: relay.name }))) return;
    const data = await request(`/mail/relays/${relay.id}`, { method: 'DELETE' }, t('Deleting...'));
    if (data) { setMailRelays(data); setNotice(t('{name} deleted.', { name: relay.name })); }
  }

  async function setDefaultRelay(relayId) {
    const data = await request('/mail/default-relay', { method: 'PUT', body: JSON.stringify({ relay_id: relayId }) }, t('Saving...'));
    if (data) { setMailRelays(data); setNotice(relayId ? t('Default relay saved.') : t('Mail now leaves directly, except for domains with a relay of their own.')); }
  }

  async function testRelay() {
    setRelayTestLines(null);
    const data = await request('/mail/relays/test', { method: 'POST', body: JSON.stringify({ to: relayTestTo.trim() }) }, t('Sending a test message...'));
    if (data) setRelayTestLines(data.lines || []);
  }

  // --- Email: Rspamd and logs (administrators) ---
  async function loadRspamdStat() {
    const data = await request('/mail/rspamd/stat', { silent: true });
    setRspamdStat(data || null);
  }

  async function loadRspamdHistory(page = rspamdFilter.page, action = rspamdFilter.action) {
    const params = new URLSearchParams({ page: String(page), per_page: '50' });
    if (rspamdFilter.q.trim()) params.set('q', rspamdFilter.q.trim());
    if (action) params.set('action', action);
    const data = await request(`/mail/rspamd/history?${params}`, { silent: true });
    setRspamdHistory(data || { items: [], total: 0, page: 1, per_page: 50 });
    setRspamdFilter(prev => ({ ...prev, page, action }));
  }

  async function loadRspamdLog(query = rspamdLogQuery) {
    const params = new URLSearchParams({ lines: String(query.lines) });
    if (query.q.trim()) params.set('q', query.q.trim());
    const data = await request(`/mail/rspamd/log?${params}`, { silent: true });
    setRspamdLog(data?.lines || []);
  }

  async function loadEximLog(query = eximLogQuery) {
    const params = new URLSearchParams({ lines: String(query.lines) });
    if (query.q.trim()) params.set('q', query.q.trim());
    const data = await request(`/mail/log?${params}`, { silent: true });
    setEximLog(data?.lines || []);
  }

  async function allowMailSender(value) {
    if (!confirm(t('Never block mail from {sender}?', { sender: value }))) return;
    const data = await request('/mail/rspamd/allow', { method: 'POST', body: JSON.stringify({ value }) }, t('Saving...'));
    if (data) {
      setNotice(t('{sender} is on the allowlist. Ask the sender to send the message again.', { sender: value }));
      applyMailSettings({ ...(mailSettings || {}), settings: data.settings });
      loadRspamdHistory(rspamdFilter.page);
    }
  }

  function applyMailSettings(data) {
    setMailSettings(data);
    setMailSettingsForm({ ...data.settings, allow: (data.settings?.allow || []).join('\n') });
  }

  async function loadMailSettings() {
    const data = await request('/mail/settings', { silent: true });
    if (data) applyMailSettings(data);
  }

  async function saveMailSettings() {
    const f = mailSettingsForm;
    const body = {
      auth_rate_per_hour: Number(f.auth_rate_per_hour) || 0,
      local_rate_per_hour: Number(f.local_rate_per_hour) || 0,
      max_message_mb: Number(f.max_message_mb) || 50,
      spam_enabled: !!f.spam_enabled,
      spam_header_score: Number(f.spam_header_score) || 6,
      spam_reject_score: Number(f.spam_reject_score) || 15,
      greylisting: !!f.greylisting,
      default_quota_mb: Number(f.default_quota_mb) || 1024,
      allow: splitAddresses(f.allow),
    };
    const data = await request('/mail/settings', { method: 'PUT', body: JSON.stringify(body) }, t('Applying mail settings...'));
    if (data) { setNotice(t('Mail settings applied.')); loadMailSettings(); }
  }

  async function saveDemoAccounts() {
    const slot = entry => (entry.username ? entry : null);
    const data = await request('/demo-mode', {
      method: 'PUT',
      body: JSON.stringify({ admin: slot(demoDraft.admin), customer: slot(demoDraft.customer) }),
    }, t('Saving...'));
    if (data) setDemoSettings(data);
  }

  async function setAddonInstalled(slug, install) {
    const addon = addons.items.find(item => item.slug === slug);
    const label = addon?.name || slug;
    if (!install) {
      // Removing an addon takes what it does away, so the admin types its
      // name rather than clicking through a generic confirm. The name shown
      // (in either language) or the slug is accepted.
      const typed = window.prompt(t('Remove {name} and stop what it is doing?\n\nType the addon name to confirm:', { name: t(label) }));
      if (typed === null) return;
      const answer = typed.trim().toLowerCase();
      const accepted = [label, t(label), slug].map(name => String(name || '').trim().toLowerCase());
      if (!accepted.includes(answer)) { setError(t('Name did not match; nothing was removed.')); return; }
    }
    const data = await request(`/addons/${slug}/${install ? 'install' : 'uninstall'}`, { method: 'POST' },
      install ? t('Installing {name}...', { name: t(label) }) : t('Removing {name}...', { name: t(label) }));
    if (data) {
      // Each addon says in its own words what it stopped and what it kept;
      // "Stopped 1 app(s)" was Application's sentence, shown for every addon.
      setNotice(install
        ? `${t('{name} installed.', { name: t(label) })} ${data.next_step ? t(data.next_step) : ''}`.trim()
        : `${t('{name} removed.', { name: t(label) })} ${data.kept ? t(data.kept) : ''}`.trim());
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
      port: app.port ?? '',
      memory_limit_mb: app.memory_limit_mb ?? '',
      cpu_limit: app.cpu_limit || '',
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
    // Port, memory and CPU are sent only when they changed: a port that is
    // sent is allocated again, and an unchanged one has nothing to move.
    const port = Number(siteAppEdit.port);
    if (port && port !== app.port) patch.port = port;
    const memory = Number(siteAppEdit.memory_limit_mb);
    if (memory && memory !== app.memory_limit_mb) patch.memory_limit_mb = memory;
    const cpu = String(siteAppEdit.cpu_limit || '').trim();
    if (app.kind === 'docker' && cpu && cpu !== app.cpu_limit) patch.cpu_limit = cpu;
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
      setShowCreateApp(false);
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
      mode: 'install',
      website_id: site.id,
      domain: site.domain,
      php_version: site.php_version || phpVersion,
      title: site.domain,
      admin_user: 'admin',
      admin_email: `admin@${site.domain}`,
      admin_password: generateRandomPassword(20),
    });
  }

  // The same panel, asking before core, plugins and themes are updated.
  function openWordPressUpdate(site) {
    setNginxCustomEditing(null);
    setLogViewer(null);
    setTerminalViewer(null);
    setWordpressInstaller({ mode: 'update', website_id: site.id, domain: site.domain });
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
    setWordpressInstaller(null);
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

  // Every extra login on the account, each with the website it reaches.
  async function loadSftpAccounts() {
    const data = await request('/sftp-accounts', {}, t('Loading SFTP accounts...'));
    if (Array.isArray(data)) setSftpAccounts(data);
    const limits = await request('/sftp-accounts/limits', {}, null);
    if (limits) setSftpLimits(limits);
  }

  // One dialog for both passwords. The main login's is confirmed with the
  // panel password (and the 2FA code): the API asks for them.
  async function saveSftpPassword() {
    if (!sftpPasswordFor) return;
    const { account, password, current_password: currentPassword, code } = sftpPasswordFor;
    const data = account
      ? await request(`/sftp-accounts/${account.id}/password`, {
        method: 'POST',
        body: JSON.stringify({ password }),
      }, t('Updating SFTP password...'))
      : await request(`/users/${currentUser.id}/sftp-password`, {
        method: 'POST',
        body: JSON.stringify({ password, current_password: currentPassword, ...(code.trim() ? { code: code.trim() } : {}) }),
      }, t('Setting SFTP password...'));
    if (!data) return;
    setSftpPasswordFor(null);
    setNotice(t('Password of {name} changed.', { name: account ? account.username : (currentUser?.sftp_username || currentUser?.username) }));
    // The session carries sftp_password_set_at, so refresh it to clear the
    // "same as your panel password" warning.
    if (!account) await loadCurrentUser();
    await loadSftpAccounts();
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
      setShowCreateSftp(false);
      await loadSftpAccounts();
    }
  }

  async function deleteSftpAccount(account) {
    if (!confirm(t('Delete SFTP account {name}? Files in its folder are kept.', { name: account.username }))) return;
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
    // The server forgets it too: hidden only here, a failed job came back on
    // every reload. Best effort -- a job already gone is what we wanted.
    const csrf = readCookie('bpanel_csrf');
    fetch(`${API}/maintenance/files/jobs/${jobId}`, {
      method: 'DELETE',
      credentials: 'include',
      headers: csrf ? { 'X-CSRF-Token': csrf } : {},
    }).catch(() => {});
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
    const appId = linkedAppId(site.id);
    setFileAppId(appId);
    setSelectedWebsiteId(String(site.id));
    navigateToPage('files');
    setFileListPath(appId ? '' : 'public_html');
    setFileUploadDir(appId ? '' : 'public_html');
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

  async function loadBackupJobs(showLoading = false) {
    const data = await request('/maintenance/backup-jobs', {}, showLoading ? t('Loading backup logs...') : '');
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
    if (item.all_users) return t('All users');
    const ids = (item.user_ids && item.user_ids.length > 0) ? item.user_ids : (item.user_id ? [item.user_id] : []);
    return ids.length ? ids.map(userNameById).join(', ') : t('No users');
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

  // A source is 'local', 'target:<id>' (a Backup Destination) or 'remote'.
  function restoreSourceBody(source) {
    if (source === 'local') return { kind: 'local' };
    if (source.startsWith('target:')) return { kind: 'target', target_id: Number(source.slice(7)) };
    return {
      kind: 'remote', ...restoreRemote, port: restoreRemote.port ? Number(restoreRemote.port) : null,
      // The key the server showed when it was listed: the download checks it
      // is still the same server before the password is sent again.
      host_key: restoreListing?.source === 'remote' ? (restoreListing.host_key?.fingerprint || '') : '',
    };
  }

  async function listRestoreSource(source) {
    setRestoreListing(null);
    setRestorePicks([]);
    setRestoreChoice({});
    const data = await request('/maintenance/restore/list', {
      method: 'POST', body: JSON.stringify({ source: restoreSourceBody(source) }),
    }, t('Looking for backups...'));
    if (data) setRestoreListing({ ...data, source });
  }

  // Step 1 has three cards; the destination itself is picked in step 2.
  function chooseRestoreSource(kind) {
    setRestoreSource(kind);
    setRestoreListing(null);
    setRestorePicks([]);
    setRestoreChoice({});
    if (kind === 'local') listRestoreSource('local');
    if (kind === 'target') {
      const first = restoreTargetId || String(sftpTargets.find(target => target.is_active !== false)?.id || '');
      setRestoreTargetId(first);
      if (first) listRestoreSource(`target:${first}`);
    }
  }

  function currentRestoreSource() {
    if (restoreSource === 'target') return restoreTargetId ? `target:${restoreTargetId}` : '';
    return restoreSource;
  }

  // Upload backup, into the source picked in step 1: this server's restore
  // folder, the chosen destination, or the connected server. Refresh then
  // shows it in step 3.
  async function uploadRestoreBackups(files) {
    const chosen = Array.from(files || []);
    const source = currentRestoreSource();
    if (chosen.length === 0 || !source) return;
    const form = new FormData();
    chosen.forEach(file => form.append('files', file));
    form.append('source', JSON.stringify(restoreSourceBody(source)));
    const data = await request('/maintenance/restore/upload', { method: 'POST', body: form },
      t('Uploading {n} backup(s)...', { n: chosen.length }));
    if (data) {
      setNotice(t('Uploaded {n} backup(s).', { n: (data.uploaded || []).length }));
      await listRestoreSource(source);
    }
  }

  function editRestoreRemote(changes) {
    setRestoreRemote(prev => ({ ...prev, ...changes }));
    // What was listed belongs to the details it was listed with.
    if (restoreListing?.source === 'remote') { setRestoreListing(null); setRestorePicks([]); }
  }

  // One row per account, its backups newest first; a file whose name does
  // not say the account is a row of its own.
  function restoreGroupsOf(listing) {
    const groups = new Map();
    for (const item of listing?.items || []) {
      const id = item.username || `file:${item.key}`;
      if (!groups.has(id)) groups.set(id, { id, username: item.username, backups: [] });
      groups.get(id).backups.push(item);
    }
    return [...groups.values()].sort((a, b) => (!a.username - !b.username) || (a.username || a.id).localeCompare(b.username || b.id));
  }

  function chosenRestoreBackup(group) {
    return group.backups.find(item => item.key === restoreChoice[group.id]) || group.backups[0];
  }

  function toggleRestorePick(id) {
    setRestorePicks(prev => prev.includes(id) ? prev.filter(entry => entry !== id) : [...prev, id]);
  }

  async function runRestore() {
    const picked = restoreGroupsOf(restoreListing).filter(group => restorePicks.includes(group.id));
    if (picked.length === 0) return;
    const names = picked.map(group => group.username || chosenRestoreBackup(group).name).join(', ');
    if (!confirm(`${t('Restore {n} user(s)? An account that already exists on this server is overwritten with what is in its backup.', { n: picked.length })}\n\n${names}`)) return;
    const data = await request('/maintenance/restore/run', {
      method: 'POST',
      body: JSON.stringify({
        source: restoreSourceBody(restoreListing.source),
        items: picked.map(group => {
          const item = chosenRestoreBackup(group);
          return { key: item.key, size: item.size, username: group.username };
        }),
      }),
    }, t('Starting the restore...'));
    if (data?.job_id) {
      setRestoreJob(data);
      setRestorePicks([]);
      setNotice(t('Restore started. It keeps running on the server; this page shows each user as it goes.'));
      loadBackupJobs();
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
      // Another import has replaced this one on the server: polling on cannot
      // bring it back.
      if (data.stale) { setError(data.error); return; }
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
  async function repairFirewall() { await runFirewallAction('/firewall/repair', { method: 'POST' }, t('Repairing the firewall...')); }
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
      setWafGlobalRules(data.custom_rules || '');
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
      setGlobalBotText((data.global_blocked_bots || []).join('\n'));
    }
  }

  async function saveGlobalBots(text) {
    const data = await request('/waf/bots/global', {
      method: 'PUT',
      body: JSON.stringify({ blocked_bots: text }),
    }, t('Saving global bad bots...'));
    if (data) {
      setGlobalBotText((data.global_blocked_bots || []).join('\n'));
      setNotice(data.failed?.length
        ? `${data.message} Failed: ${data.failed.map(f => `${f.domain} (${f.error})`).join('; ')}`
        : (data.message || 'Global bad bots saved.'));
      await loadBotBlocks();
    }
  }

  async function saveWafGlobalRules() {
    const data = await request('/waf/rules/custom', { method: 'PUT', body: JSON.stringify({ content: wafGlobalRules }) }, t('Saving...'));
    if (data) { setNotice(t('Global WAF rules saved. They apply to every website with the WAF on.')); await loadWafRules(); }
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
    // 'malware-scan' is the address a scan used to open at; a scan is now a
    // sub-page of the scanner, and the old address shows the scanner.
    if (!isAuthenticated || !['malware', 'malware-scan'].includes(page) || !isAdmin || !malwareAddonInstalled) return;
    loadMalwareScanStatus();
    loadMalwareScanJobs();
    loadLatestMalwareScanJob();
    loadMalwareSchedule();
    if (websites.length === 0) loadWebsiteList('', false);
  }, [isAuthenticated, page, isAdmin, malwareAddonInstalled]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'notifications' || !notificationsAddonInstalled || !isAdmin) return;
    loadNotifyMe();
    loadNotifySettings();
    loadNotifyLog();
  }, [isAuthenticated, page, notificationsAddonInstalled, isAdmin]);

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

  // Both lists are read whole when their page opens; the search box on each
  // filters what is already here, as OPanel's does.
  useEffect(() => {
    if (!isAuthenticated || page !== 'websites') return;
    loadWebsiteList('', false);
  }, [isAuthenticated, page]);

  useEffect(() => {
    if (!isAuthenticated || page !== 'databases') return;
    loadDatabases(false);
  }, [isAuthenticated, page]);

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
  useEffect(() => { if (page === 'backups' && backupTab === 'restore' && isAdmin && restoreSource === 'local') listRestoreSource('local'); }, [backupTab, page]);
  useEffect(() => {
    if (!restoreJob?.job_id || !['queued', 'running'].includes(restoreJob.status)) return undefined;
    const timer = setInterval(async () => {
      const data = await request(`/maintenance/backup-jobs/${restoreJob.job_id}`, { silent: true });
      if (!data?.job_id) return;
      setRestoreJob(data);
      if (!['queued', 'running'].includes(data.status)) {
        loadBackupJobs();
        loadUsers();
        if (restoreListing && restoreListing.source !== 'remote') listRestoreSource(restoreListing.source);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [restoreJob?.job_id, restoreJob?.status]);

  useEffect(() => { if (selectedWebsiteId && page === 'cron') listCron(); }, [selectedWebsiteId, page]);
  // Which optional features exist decides what the nav shows, so this is asked
  // once per session rather than per page.
  useEffect(() => { if (currentUser) loadAddons(); }, [currentUser]);
  useEffect(() => { if (!isAuthenticated) loadDemoAccess(); }, [isAuthenticated]);
  const demoAddonInstalled = addons.items.some(item => item.slug === 'demo' && item.installed);
  useEffect(() => { if (isAdmin && demoAddonInstalled) loadDemoSettings(); }, [isAdmin, demoAddonInstalled]);
  useEffect(() => {
    if (!isAuthenticated || page !== 'dns' || !dnsAddonInstalled) return;
    loadDnsInfo();
    if (isAdmin) { loadDnsSettings(); loadUsers(); }
  }, [isAuthenticated, page, dnsAddonInstalled, isAdmin]);
  useEffect(() => {
    if (!isAuthenticated || page !== 'dns' || !dnsAddonInstalled) return;
    loadDnsZones(dnsPage);
  }, [isAuthenticated, page, dnsAddonInstalled, dnsPage]);
  useEffect(() => {
    if (!isAuthenticated || page !== 'mail' || !mailAddonInstalled) return;
    setMailDns(null);
    loadMailInfo();
    if (isAdmin) loadUsers();
  }, [isAuthenticated, page, mailAddonInstalled, isAdmin]);
  useEffect(() => {
    if (!isAuthenticated || page !== 'mail' || !mailAddonInstalled) return;
    if (mailTab === 'mailboxes') loadMailboxes(mailPage);
    else if (mailTab === 'forwarders') loadForwarders(mailPage);
  }, [isAuthenticated, page, mailAddonInstalled, mailTab, mailPage, mailFilter.domain_id]);
  useEffect(() => {
    if (!isAuthenticated || page !== 'mail' || !mailAddonInstalled || !isAdmin) return;
    if (mailTab === 'relay') loadMailRelays();
    else if (mailTab === 'rspamd') { loadRspamdStat(); loadRspamdHistory(1); loadMailSettings(); }
    else if (mailTab === 'server') { loadMailSettings(); loadEximLog(); }
  }, [isAuthenticated, page, mailAddonInstalled, isAdmin, mailTab]);
  useEffect(() => {
    if (isAuthenticated && page === 'mail' && isAdmin && mailTab === 'rspamd' && rspamdView === 'log') loadRspamdLog();
  }, [isAuthenticated, page, isAdmin, mailTab, rspamdView]);

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
    if (isAuthenticated && page === 'users') { loadUsers(); loadPackages(); if (currentUser?.role === 'reseller') loadResellerPool(); }
    // The owner picker on Create website.
    if (isAuthenticated && page === 'websites' && currentUser?.role === 'reseller') loadUsers();
    if (isAuthenticated && page === 'php') { loadPhpConfig(); loadPhpTune(phpConfig.php_version); loadPhpExtensions(); }
    if (isAuthenticated && page === 'firewall') { setShowFirewallIpList(false); loadFirewall(); loadFirewallBlocklists(); loadFail2ban(); loadBannedPage(0); }
    if (isAuthenticated && ['waf', 'waf-site'].includes(page)) {
      loadBotBlocks();
      // /waf/rules and /waf/crs describe the whole server and stay admin-only.
      if (isAdmin) { loadWafRules(); loadCrs(); }
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
    if (isAuthenticated && page === 'panel-settings') { loadPanelSettings(); if (isAdmin) loadApiTokens(); }
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
    if (role === 'reseller') return 'Reseller';
    return role === 'admin' ? 'Admin' : 'End user';
  }

  // The sidebar in three labelled groups, as OPanel has it - what a site
  // needs, what guards it, and the server itself - so nothing hides behind a
  // collapsed "Settings". Labels are English and go through t() when drawn.
  // The sidebar holds what is used every day (operator, 2026-09-27); the rest
  // is one click further, on the Settings page. An addon shows only once it
  // is on - Application, AI assistants, Notifications.
  // One plain list, top to bottom, as in OPanel: the everyday pages, the
  // addons that are on, then Settings.
  const navSections = [
    { key: 'main', items: [
      ['dashboard', 'Dashboard', Home],
      ['websites', 'Websites', Globe],
      ...(appsFeatureEnabled ? [['applications', 'Applications', Boxes]] : []),
      ['ssl', 'SSL', Lock],
      ['databases', 'Databases', Database],
      ['cron', 'Cron', Clock],
      ['files', 'File manager', FolderOpen],
      ['sftp', 'SFTP accounts', KeyRound],
      ['backups', 'Backups', Archive],
      ...(isAdmin ? [['users', 'Panel users', Users]] : []),
      ...(isReseller ? [['users', 'Customers', Users]] : []),
      ...(mailAddonInstalled ? [['mail', 'Email', Mail]] : []),
      ...(dnsAddonInstalled ? [['dns', 'DNS Manager', Network]] : []),
      ...(mcpAddonInstalled ? [['mcp', 'AI assistants (MCP)', Bot]] : []),
      ...(notificationsAddonInstalled && isAdmin ? [['notifications', 'Notifications', Bell]] : []),
      ...(malwareAddonInstalled && isAdmin ? [['malware', 'Malware Scanner', Bug]] : []),
      ['settings', 'Settings', SettingsIcon],
    ] },
  ].filter(section => section.items.length > 0);

  // Everything else, on the Settings page: [page, label, icon, summary].
  const settingsGroups = [
    { title: 'Security', items: [
      isAdmin && ['firewall', 'Firewall', BrickWall, 'Open ports, blocked addresses and blocklists'],
      ['waf', 'WAF', ShieldAlert, 'Web application firewall for each website'],
      isAdmin && ['access-logs', 'Access logs', ScrollText, 'Visitors and what the WAF blocked'],
      ['security', 'Account security', LockKeyhole, 'Password, two-factor authentication and passkeys'],
    ] },
    { title: 'System', items: [
      isAdmin && ['panel-settings', 'Panel settings', SettingsIcon, 'Branding, panel address and certificate'],
      isAdmin && ['services', 'Services', Activity, "Start, stop and check the server's daemons"],
      isAdmin && ['php', 'PHP config', Code2, 'PHP versions, limits and extensions'],
      isAdmin && ['updates', 'Updates', RefreshCw, 'Panel and system updates'],
      isAdmin && ['addons', 'Addons', PackageOpen, 'Install and turn on optional features'],
    ] },
  ].map(group => ({ ...group, items: group.items.filter(Boolean) })).filter(group => group.items.length > 0);
  const settingsItems = settingsGroups.flatMap(group => group.items);

  const navItems = navSections.flatMap(section => section.items);
  const basePage = NAV_PARENT_PAGE[page] || page;
  // A page reached from Settings lights up Settings in the sidebar...
  const navPage = settingsItems.some(([key]) => key === basePage) ? 'settings' : basePage;
  const activeNavItem = navItems.find(([key]) => key === navPage) || navItems[0];
  // ...and is still called by its own name at the top: "Firewall", not "Settings".
  const pageItem = [...navItems, ...settingsItems].find(([key]) => key === basePage) || activeNavItem;
  // Its title is a crumb back to Settings, as in OPanel.
  const settingsPageItem = settingsItems.find(([key]) => key === basePage);

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

  // A website that fronts an application serves nothing from its own folder:
  // nginx proxies every request to the app, so files uploaded there were never
  // read (160.236.192.120, 2026-10-02). Its file manager is the app's.
  function linkedAppId(siteId) {
    const site = websites.find(item => String(item.id) === String(siteId));
    return site?.app_id && applicationAddonInstalled ? String(site.app_id) : '';
  }

  function FileTargetSelect() {
    return <select
      value={fileAppId ? `app:${fileAppId}` : selectedWebsiteId}
      onChange={e => {
        const value = e.target.value;
        const appId = value.startsWith('app:') ? value.slice(4) : linkedAppId(value);
        if (!value.startsWith('app:')) setSelectedWebsiteId(value);
        setFileAppId(appId);
        setFileListPath(appId ? '' : 'public_html');
        setFileUploadDir(appId ? '' : 'public_html');
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

  function EmptyState({ icon: Icon = AlertCircle, message = 'No data yet', action }) {
    /* Translated here rather than at each call site. Several callers pass a
     * ternary - message={searching ? 'No matches.' : 'None yet.'} - and a
     * wrapper looking for message="..." cannot see inside one. Doing it here
     * covers every caller, including the ones written tomorrow. */
    return <div className="empty-state">
      <Icon size={40} />
      <p>{t(message)}</p>
      {action && <button type="button" className="mini secondary-light" onClick={action.onClick}>{action.icon ? <action.icon size={14}/> : null} {action.label}</button>}
    </div>;
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
    return <article className="resource-card">
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
        detail: !backups ? t('Checking…') : !backups.schedules ? t('No schedule') : backups.failed ? t('Last run failed') : t('{n} schedule(s)', { n: backups.schedules }),
        tone: !backups ? 'neutral' : !backups.schedules ? 'warn' : backups.failed ? 'bad' : 'ok' });
      const firewallOn = sum.firewall?.enabled;
      cards.push({ key: 'firewall', icon: BrickWall, label: t('Firewall'),
        value: firewallOn === true ? t('On') : firewallOn === false ? t('Off') : '—', detail: 'iptables + ipset',
        tone: firewallOn === true ? 'ok' : firewallOn === false ? 'bad' : 'neutral' });
      const engine = sum.waf?.engine;
      cards.push({ key: 'waf', icon: ShieldAlert, label: 'WAF',
        value: engine === 'on' ? t('On') : engine === 'off' ? t('Off') : '—', detail: t('ModSecurity engine'),
        tone: engine === 'on' ? 'ok' : engine === 'off' ? 'warn' : 'neutral' });
      const scanner = sum.malware;
      const lastScan = scanner?.last_scan;
      cards.push({ key: 'malware', icon: Bug, label: t('Malware scanner'),
        value: !scanner ? '—' : scanner.addon === false ? t('Off') : !scanner.installed ? t('Not installed') : lastScan?.infected ? t('{n} threat(s)', { n: lastScan.infected }) : lastScan ? t('Clean') : t('No scan yet'),
        detail: scanner?.addon === false ? t('Not installed') : scanner?.running ? t('Scanning...') : lastScan ? shortDate(lastScan.finished_at) : t('Last scan'),
        tone: !scanner || scanner.addon === false ? 'neutral' : !scanner.installed ? 'warn' : lastScan?.infected ? 'bad' : lastScan ? 'ok' : 'neutral' });
      const services = sum.services;
      cards.push({ key: 'services', icon: Activity, label: t('Services'),
        value: services ? `${services.running}/${services.total}` : '—',
        detail: services?.stopped?.length ? t('Stopped: {names}', { names: services.stopped.join(', ') }) : services ? t('All running') : t('Checking…'),
        tone: !services ? 'neutral' : services.stopped?.length ? 'bad' : 'ok' });
    } else {
      cards.push(sslCard);
      const wafOn = sites.waf_on ?? 0;
      cards.push({ key: 'waf', icon: ShieldAlert, label: 'WAF', value: `${wafOn}/${sites.total}`,
        detail: !sites.total ? t('No websites yet') : wafOn === sites.total ? t('On for every website') : t('{n} website(s) without WAF', { n: sites.total - wafOn }),
        tone: !sites.total ? 'neutral' : wafOn === sites.total ? 'ok' : 'warn' });
      const twoFactor = !!currentUser?.totp_enabled;
      cards.push({ key: 'security', icon: LockKeyhole, label: t('Account security'),
        value: twoFactor ? t('On') : t('Off'), detail: t('Two-factor sign-in'), tone: twoFactor ? 'ok' : 'warn' });
    }

    // Things that want a look, most urgent first.
    const attention = [];
    if (isAdmin && sum.services?.stopped?.length) attention.push({ tone: 'bad', text: t('Stopped: {names}', { names: sum.services.stopped.join(', ') }), action: t('Open'), target: 'services' });
    if (isAdmin && sum.firewall?.enabled === false) attention.push({ tone: 'bad', text: t('The firewall is off.'), action: t('Open'), target: 'firewall' });
    if (isAdmin && sum.malware?.last_scan?.infected) attention.push({ tone: 'bad', text: t('The last malware scan found {n} threat(s).', { n: sum.malware.last_scan.infected }), action: t('Open'), target: 'malware' });
    if (isAdmin && sum.backups?.failed) attention.push({ tone: 'bad', text: t('{n} scheduled backup(s) failed on their last run.', { n: sum.backups.failed }), action: t('Open'), target: 'backups' });
    if (ssl.unsecured_count) attention.push({ tone: 'warn', text: t('{n} website(s) without SSL: {domains}', {
      n: ssl.unsecured_count, domains: ssl.unsecured.join(', ') + (ssl.unsecured_count > ssl.unsecured.length ? '…' : ''),
    }), action: t('Set up SSL'), target: 'ssl' });
    if (sites.suspended) attention.push({ tone: 'warn', text: t('{n} website(s) suspended.', { n: sites.suspended }), action: t('Open'), target: 'websites' });
    if (isAdmin && sum.backups && !sum.backups.schedules) attention.push({ tone: 'warn', text: t('No scheduled backup is set up.'), action: t('Set up'), target: 'backups' });
    if (isAdmin && sum.waf?.engine === 'off') attention.push({ tone: 'warn', text: t('The WAF engine is not installed.'), action: t('Open'), target: 'waf' });
    // An addon that is off is not a fault: only the scanner's addon being on
    // while LMD and ClamAV are missing wants a look.
    if (isAdmin && sum.malware?.addon && !sum.malware.installed) attention.push({ tone: 'warn', text: t('The malware scanner is not installed.'), action: t('Open'), target: 'malware' });
    if (!isAdmin && currentUser && !currentUser.totp_enabled) attention.push({ tone: 'info', text: t('Two-factor sign-in is off for your account.'), action: t('Turn on'), target: 'security' });
    if (isAdmin && sum.updates?.update_available) attention.push({ tone: 'info', text: t('Panel update {version} is available.', { version: sum.updates.latest_version }), action: t('Open'), target: 'updates' });

    // The create forms open with the page, so "New website" is one click.
    const quickActions = [
      { key: 'site', icon: Plus, label: t('New website'), primary: true, run: () => { setCreateFormOpen(true); navigateToPage('websites'); } },
      { key: 'db', icon: Database, label: t('New database'), run: () => { setDbCreateOpen(true); navigateToPage('databases'); } },
      { key: 'ssl', icon: Lock, label: t('Set up SSL'), run: () => navigateToPage('ssl') },
      { key: 'backup', icon: Archive, label: t('Back up a website'), run: () => navigateToPage('backups') },
      { key: 'sftp', icon: KeyRound, label: t('New SFTP account'), run: () => {
        navigateToPage('sftp');
        window.setTimeout(() => document.querySelector('.sftp-form input')?.focus(), 150);
      } },
      ...(mailAddonInstalled ? [{ key: 'mail', icon: Mail, label: t('New mailbox'), run: () => { setMailTab('mailboxes'); navigateToPage('mail'); } }] : []),
      ...(canManageUsers ? [{ key: 'users', icon: Users, label: isReseller ? t('Customers') : t('Panel users'), run: () => navigateToPage('users') }] : []),
    ];

    return <div className="dashboard">
      {isAdmin && <section className="section dash-card dash-resources">
        <div className="dash-card-head"><span className="dash-card-icon"><Activity size={16}/></span><h2>{t('Server resources')}</h2></div>
        <div className="resource-grid">
          <ResourceCard icon={Cpu} label="CPU" value={formatPercent(cpu.percent)} percent={cpu.percent} detail={cpu.load?.length ? t('Load {load}', { load: cpu.load.join(' / ') }) : t('{count} cores', { count: cpu.cores || '--' })} />
          <ResourceCard icon={MemoryStick} label="RAM" value={formatPercent(memory.percent)} percent={memory.percent} detail={`${formatBytes(memory.used)} / ${formatBytes(memory.total)}`} />
          <ResourceCard icon={HardDrive} label={t('Disk')} value={formatPercent(disk.percent)} percent={disk.percent} detail={`${formatBytes(disk.used)} / ${formatBytes(disk.total)}`} />
          <ResourceCard icon={Network} label={t('Network')} value={`${formatBytes(networkTotal)}/s`} detail={t('Down {down}/s / Up {up}/s', { down: formatBytes(network.rx_per_sec), up: formatBytes(network.tx_per_sec) })} />
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
            ? <div className="attention-ok"><CheckCircle size={16}/> {dashSummary ? t('Everything looks fine.') : t('Checking…')}</div>
            : <div className="attention-list">
                {attention.map(item => <div className={`attention-item tone-${item.tone}`} key={item.text}>
                  {item.tone === 'info' ? <RefreshCw size={15}/> : <AlertCircle size={15}/>}
                  <span>{item.text}</span>
                  <button type="button" className="mini secondary" onClick={() => navigateToPage(item.target)}>{item.action}</button>
                </div>)}
              </div>}
        </section>
        <section className="section dash-card">
          <div className="dash-card-head"><span className="dash-card-icon"><Zap size={16}/></span><h2>{t('Quick actions')}</h2></div>
          <div className="quick-actions">
            {quickActions.map(action => <button type="button" key={action.key} className={action.primary ? '' : 'secondary'} onClick={action.run}><action.icon size={15}/> {action.label}</button>)}
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
      <h2>{t('Administrators only')}</h2>
      <div className="info-box"><AlertCircle size={14}/> {t('This page reports on the server itself, so only administrators can see it.')}</div>
    </section>;
  }

  // The API sends naive UTC; without the Z the browser would read it as local.
  function notifyTime(value) {
    if (!value) return '';
    const date = new Date(value.endsWith('Z') ? value : `${value}Z`);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  // The send log, a page of its own. The server keeps the last 100 messages,
  // so the status filter and the pages are worked out here.
  function renderNotifyLog() {
    const size = 50;
    const rows = notifyLog.filter(row => !notifyLogStatus || (notifyLogStatus === 'sent' ? row.status === 'sent' : row.status !== 'sent'));
    const pages = Math.max(1, Math.ceil(rows.length / size));
    const current = Math.min(notifyLogPage, pages);
    const shown = rows.slice((current - 1) * size, current * size);
    return <section className="section notify-log-page">
      <div className="section-title">
        <div className="waf-detail-title">
          <button className="secondary" onClick={() => setShowNotifyLog(false)}><ArrowLeft size={14}/> {t('Notifications')}</button>
          <div><h2>{t('Send log')}</h2><p className="hint">{t('The last 100 messages sent, and the ones that failed.')}</p></div>
        </div>
        <select value={notifyLogStatus} aria-label={t('Show')} onChange={e => { setNotifyLogStatus(e.target.value); setNotifyLogPage(1); }}>
          <option value="">{t('All')}</option><option value="sent">{t('Sent')}</option>
          <option value="failed">{t('Failed')}</option>
        </select>
      </div>
      {shown.length > 0 ? <ul className="notify-log-list">
        {shown.map(row => <li key={row.id}>
          <span className={`badge ${row.status === 'sent' ? 'ok' : 'bad'}`}>{row.status === 'sent' ? t('Sent') : t('Failed')}</span>
          <small>{notifyTime(row.created_at)}</small>
          <span className="notify-log-subject" title={row.title}>{row.title}</span>
          <small className="notify-log-to" title={row.username || ''}>{row.channel === 'email' ? '✉' : '✈'} {row.username || '—'}</small>
          {row.status !== 'sent' && row.detail && <small className="notify-log-error" title={row.detail}>{row.detail}</small>}
        </li>)}
      </ul> : <p className="hint">{t('Nothing has been sent yet.')}</p>}
      {pages > 1 && <div className="firewall-ip-pager">
        <button className="mini secondary" disabled={current <= 1} onClick={() => setNotifyLogPage(Math.max(1, current - 1))}>{t('Previous')}</button>
        <span className="hint">{t('Page {page} of {pages}', { page: current, pages })}</span>
        <button className="mini secondary" disabled={current >= pages} onClick={() => setNotifyLogPage(current + 1)}>{t('Next')}</button>
      </div>}
    </section>;
  }

  function renderNotificationsPage() {
    if (showNotifyLog) return renderNotifyLog();
    const me = notifyMe;
    const s = notifySettings;
    const events = me?.events || [];
    const muted = new Set(me?.muted || []);
    const eventRow = ev => <label key={ev.key}>
      <input type="checkbox" checked={!muted.has(ev.key)} disabled={!!loading} onChange={e => toggleNotifyEvent(ev.key, e.target.checked)} />
      <span className="notify-event-text">{t(ev.label)}<small>{t(ev.hint)}</small></span>
    </label>;
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Notifications')}</h2>
            <p className="hint">{t('Email and Telegram alerts for administrators. Hosting customers are not notified.')}</p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={() => { loadNotifyMe(); loadNotifySettings(); }}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {!me && !s && <p className="hint">{t('Loading…')}</p>}
      </section>

      {s && <section className="section">
        <div className="section-title">
          <div><h2>{t('Channels')}</h2><p className="hint">{t("Server-wide. Your own account's alerts go out through these too.")}</p></div>
          <button className="secondary" onClick={() => { setNotifyLogPage(1); setShowNotifyLog(true); loadNotifyLog(); }}><ScrollText size={14}/> {t('Send log')}</button>
        </div>
        <div className="notify-grid">
          <div className="notify-card">
            <div className="notify-card-head">
              <h3>{t('Email (SMTP)')}</h3>
            </div>
            <div className="notify-form">
              <label className="wide"><span>{t('SMTP host')}</span><input value={smtpForm.host} placeholder="smtp.gmail.com" onChange={e => setSmtpForm(f => ({ ...f, host: e.target.value }))} /></label>
              <label><span>{t('Port')}</span><input type="number" value={smtpForm.port} onChange={e => setSmtpForm(f => ({ ...f, port: e.target.value }))} /></label>
              <label><span>{t('Security')}</span><select value={smtpForm.security} onChange={e => setSmtpForm(f => ({ ...f, security: e.target.value, port: { starttls: 587, ssl: 465, none: 25 }[e.target.value] }))}>
                <option value="starttls">STARTTLS (587)</option><option value="ssl">SSL/TLS (465)</option><option value="none">{t('None')}</option>
              </select></label>
              <label><span>{t('Username')}</span><input value={smtpForm.username} autoComplete="off" onChange={e => setSmtpForm(f => ({ ...f, username: e.target.value }))} /></label>
              <label><span>{t('Password')}</span><input type="password" value={smtpForm.password} autoComplete="new-password"
                placeholder={s.smtp.password_set ? t('Saved — leave blank to keep') : ''} onChange={e => setSmtpForm(f => ({ ...f, password: e.target.value }))} /></label>
              <label><span>{t('From address')}</span><input value={smtpForm.from_email} placeholder="panel@example.com" onChange={e => setSmtpForm(f => ({ ...f, from_email: e.target.value }))} /></label>
              <label><span>{t('From name')}</span><input value={smtpForm.from_name} onChange={e => setSmtpForm(f => ({ ...f, from_name: e.target.value }))} /></label>
            </div>
            <div className="notify-test">
              <button className="secondary" disabled={!!loading || !s.smtp_ready} onClick={() => sendNotifyTest('email')}><Mail size={14}/> {t('Send me a test email')}</button>
            </div>
            <p className="hint">{t('Uses the saved settings. Many VPS providers block port 25; use 587 or 465.')}</p>
          </div>

          <div className="notify-card">
            <div className="notify-card-head">
              <h3>{t('Telegram')}</h3>
            </div>
            <div className="notify-form">
              <label className="wide"><span>{t('Bot token (from @BotFather)')}</span><input type="password" value={botTokenInput} autoComplete="off"
                placeholder={s.telegram.token_set ? t('Saved — leave blank to keep') : '123456789:AA…'} onChange={e => setBotTokenInput(e.target.value)} /></label>
              {s.telegram.bot_username && <p className="hint wide">{t('Bot:')} <a href={`https://t.me/${s.telegram.bot_username}`} target="_blank" rel="noopener noreferrer">@{s.telegram.bot_username}</a></p>}
              <label className="wide"><span>{t('Admin chat ID')}</span><input value={adminChatInput} placeholder="-1001234567890" onChange={e => setAdminChatInput(e.target.value)} /></label>
            </div>
            <p className="hint">{t('Create a bot with @BotFather (/newbot) and paste its token. Then send the bot any message - or add it to a group - press Find chat ID and pick the chat.')}</p>
            <div className="notify-test">
              <button className="secondary" disabled={!!loading || !s.telegram.token_set} onClick={findTelegramChats}><Search size={14}/> {t('Find chat ID')}</button>
              <button className="secondary" disabled={!!loading || !s.telegram.token_set || !s.telegram.chat_id} onClick={() => sendNotifyTest('telegram_admin')}><Send size={14}/> {t('Send test')}</button>
            </div>
            {telegramChats && (telegramChats.length > 0
              ? <div className="notify-chats">{telegramChats.map(chat => <button type="button" key={chat.id} className={adminChatInput === chat.id ? 'mini' : 'mini secondary'} onClick={() => setAdminChatInput(chat.id)}>{chat.name || chat.type}<code>{chat.id}</code></button>)}</div>
              : <p className="hint">{t('No messages yet. Send the bot a message first, then press Find chat ID again.')}</p>)}
            <p className="hint">{t('Server events go to this chat once. An administrator with no chat of their own hears about their account here too.')}</p>
          </div>
        </div>

        <div className="notify-grid">
          <div className="notify-card">
            <h3>{t('When to warn')}</h3>
            <div className="notify-form">
              <label><span>{t('Disk usage (%)')}</span><input type="number" min="50" max="99" value={notifyLimits.disk_percent} onChange={e => setNotifyLimits(v => ({ ...v, disk_percent: e.target.value }))} /></label>
              <label><span>{t('Certificate expiry (days)')}</span><input type="number" min="1" max="60" value={notifyLimits.ssl_days} onChange={e => setNotifyLimits(v => ({ ...v, ssl_days: e.target.value }))} /></label>
              <label><span>{t('Message language')}</span><select value={notifyLimits.language} onChange={e => setNotifyLimits(v => ({ ...v, language: e.target.value }))}>
                <option value="vi">Tiếng Việt</option><option value="en">English</option></select></label>
            </div>
          </div>
        </div>
        <div className="notify-actions">
          <button disabled={!!loading} onClick={() => saveNotifySettings({
            language: notifyLimits.language,
            smtp: { ...smtpForm, port: Number(smtpForm.port) || 587, password: smtpForm.password || null },
            telegram: { bot_token: botTokenInput.trim() || null, chat_id: adminChatInput.trim() },
            thresholds: { disk_percent: Number(notifyLimits.disk_percent), ssl_days: Number(notifyLimits.ssl_days) },
          }, t('Saved.'))}><Save size={14}/> {t('Save')}</button>
          {s.smtp.password_set && <button className="secondary-light" disabled={!!loading} onClick={() => saveNotifySettings({ smtp: { clear_password: true } }, t('Saved.'))}>{t('Forget SMTP password')}</button>}
          {s.telegram.token_set && <button className="secondary-light" disabled={!!loading} onClick={() => saveNotifySettings({ telegram: { clear_bot_token: true } }, t('Telegram bot removed.'))}>{t('Remove the bot')}</button>}
        </div>
      </section>}

      {me && <section className="section">
        <div className="section-title">
          <div><h2>{t('My notifications')}</h2><p className="hint">{t('Where the panel reaches you, and about what.')}</p></div>
        </div>
        <div className="notify-grid">
          <div className="notify-card">
            <div className="notify-card-head">
              <h3>{t('Email')}</h3>
              <label className="notify-switch"><input type="checkbox" disabled={!me.channels.email || !!loading} checked={!!me.email_enabled && !!me.channels.email}
                onChange={e => saveNotifyMe({ email_enabled: e.target.checked })} /> {t('On')}</label>
            </div>
            {me.channels.email
              ? <p className="hint">{t('Sent to {email}, the address on your account.', { email: me.email || '—' })}</p>
              : <p className="hint">{t('Email is not set up on this panel.')}</p>}
          </div>
          <div className="notify-card">
            <div className="notify-card-head">
              <h3>{t('Telegram')}</h3>
              {me.telegram_linked && <label className="notify-switch"><input type="checkbox" checked={!!me.telegram_enabled} disabled={!!loading}
                onChange={e => saveNotifyMe({ telegram_enabled: e.target.checked })} /> {t('On')}</label>}
            </div>
            {!me.channels.telegram ? <p className="hint">{t('Telegram is not set up on this panel.')}</p>
              : me.telegram_linked ? <div className="notify-test"><span className="badge ok">{t('Linked')}</span> <code>{me.telegram_chat_id}</code>
                  <button className="mini secondary" disabled={!!loading} onClick={() => sendNotifyTest('telegram')}>{t('Send test')}</button>
                  <button className="mini secondary-light" disabled={!!loading} onClick={unlinkTelegram}>{t('Unlink')}</button></div>
              : <>
                  {me.telegram_admin_chat && <p className="hint">{t('You hear in the admin chat ({chat}). Connect a chat of your own to hear there instead.', { chat: me.telegram_admin_chat })}</p>}
                  {telegramLink ? <>
                      <p className="hint">{t('In Telegram, press Start in the chat with @{bot}, then come back and check.', { bot: telegramLink.bot_username })}</p>
                      <p className="hint">{t('Or send the bot this message:')} <code>/start {telegramLink.code}</code> {t('The code works for {n} minutes.', { n: telegramLink.expires_minutes })}</p>
                      <div className="notify-test">
                        {telegramLink.link && <button className="secondary" onClick={() => window.open(telegramLink.link, '_blank', 'noopener')}>{t('Open Telegram')}</button>}
                        <button disabled={!!loading} onClick={verifyTelegramLink}>{t('I pressed Start — check')}</button>
                      </div>
                    </>
                    : <button className="secondary" disabled={!!loading} onClick={startTelegramLink}>{t('Link Telegram')}</button>}
                  <div className="notify-test">
                    <input value={myChatInput} placeholder={t('Your chat ID')} aria-label={t('Your chat ID')} onChange={e => setMyChatInput(e.target.value)} />
                    <button className="secondary" disabled={!!loading || !myChatInput.trim()} onClick={() => saveNotifyMe({ telegram_chat_id: myChatInput.trim() })}>{t('Save')}</button>
                  </div>
                </>}
          </div>
        </div>
        <div className="notify-card">
          <h3>{t('What to send me')}</h3>
          <div className="notify-events">
            <span className="field-label">{t('About the server')}</span>
            {events.filter(ev => ev.audience === 'admin').map(eventRow)}
            <span className="field-label">{t('About your account')}</span>
            {events.filter(ev => ev.audience === 'user').map(eventRow)}
          </div>
        </div>
      </section>}
    </>;
  }

  function renderSettingsHub() {
    return <section className="section settings-hub">
      <div className="section-title">
        <div><h2>{t('Settings')}</h2><p className="hint">{t('Security, server and panel configuration.')}</p></div>
      </div>
      {settingsGroups.map(group => <div className="settings-hub-group" key={group.title}>
        <h3>{t(group.title)}</h3>
        <div className="settings-hub-grid">
          {group.items.map(([key, label, Icon, summary]) => <button key={key} type="button" className="settings-tile" onClick={() => navigateToPage(key)}>
            <span className="settings-tile-icon"><Icon size={18}/></span>
            <span className="settings-tile-text"><strong>{t(label)}</strong><small>{t(summary)}</small></span>
          </button>)}
        </div>
      </div>)}
    </section>;
  }

  // Which addon a page belongs to decides the words: this said
  // "Applications" on the Malware, MCP and Notifications pages too.
  function renderAddonMissing(slug = 'application') {
    const addon = addons.items.find(item => item.slug === slug);
    const name = addon?.name || 'Application';
    const installed = !!addon?.installed;
    // Until the list is in, which addon is missing is not known yet.
    if (!addons.loaded) return <section className="section"><p className="hint">{t('Loading…')}</p></section>;
    return <section className="section">
      <h2>{t(name)}</h2>
      <div className="info-box"><AlertCircle size={14}/> {slug === 'application' && installed
        ? t('Your package does not include Applications. Contact an administrator to upgrade.')
        : isAdmin ? t('The {name} addon is not installed. Install it on the Addons page.', { name: t(name) })
          : t('{name} is not available on this server.', { name: t(name) })}</div>
      {isAdmin && !installed && <div className="actions"><button onClick={() => navigateToPage('addons')}><PackageOpen size={14}/> {t('Open Addons')}</button></div>}
    </section>;
  }

  function dnsTtlLabel(seconds) {
    const n = Number(seconds) || 0;
    if (n >= 86400 && n % 86400 === 0) return t('{n} d', { n: n / 86400 });
    if (n >= 3600 && n % 3600 === 0) return t('{n} h', { n: n / 3600 });
    if (n >= 60 && n % 60 === 0) return t('{n} min', { n: n / 60 });
    return t('{n} s', { n });
  }

  function dnsTypeHint(type) {
    const ip4 = dnsInfo?.addresses?.ipv4?.[0];
    const ip6 = dnsInfo?.addresses?.ipv6?.[0];
    return {
      A: ip4 ? t('The IPv4 address the name points to. This server: {ip}.', { ip: ip4 }) : t('The IPv4 address the name points to.'),
      AAAA: ip6 ? t('The IPv6 address the name points to. This server: {ip}.', { ip: ip6 }) : t('The IPv6 address the name points to.'),
      CNAME: t('Makes the name an alias of another host. A name with a CNAME can have no other record.'),
      MX: t('A mail server for the domain; the lowest priority is tried first.'),
      TXT: t('Text such as SPF, DKIM or a site verification. A long value is split into strings for you.'),
      NS: t('Hands a subdomain to other nameservers.'),
      SRV: t('Where a service runs: weight port target, with the priority in its own field. The name is like _sip._tcp.'),
      CAA: t('Which certificate authorities may issue for the domain, for example 0 issue letsencrypt.org.'),
    }[type] || '';
  }

  function renderDnsRecordFields(form, set, { lockType = false } = {}) {
    const hasPriority = ['MX', 'SRV'].includes(form.type);
    const current = Number(form.ttl) || 0;
    const ttls = !current || DNS_TTLS.includes(current) ? DNS_TTLS : [...DNS_TTLS, current].sort((a, b) => a - b);
    return <div className={`dns-record-fields${hasPriority ? ' with-priority' : ''}`}>
      <label className="field"><span className="field-label">{t('Type')}</span>
        <select value={form.type} disabled={lockType} onChange={e => set({ type: e.target.value })}>
          {DNS_TYPES.map(type => <option key={type} value={type}>{type}</option>)}
        </select></label>
      <label className="field"><span className="field-label">{t('Name')}</span>
        <input value={form.name} placeholder="@" spellCheck={false} autoCapitalize="off" onChange={e => set({ name: e.target.value })} /></label>
      {hasPriority && <label className="field"><span className="field-label">{t('Priority')}</span>
        <input type="number" min="0" max="65535" value={form.priority} placeholder="10" onChange={e => set({ priority: e.target.value })} /></label>}
      <label className="field dns-value-field"><span className="field-label">{t('Value')}</span>
        {form.type === 'TXT'
          ? <textarea rows={2} value={form.value} placeholder={DNS_PLACEHOLDERS.TXT} spellCheck={false} onChange={e => set({ value: e.target.value.replace(/[\r\n]+/g, ' ') })} />
          : <input value={form.value} placeholder={DNS_PLACEHOLDERS[form.type]} spellCheck={false} autoCapitalize="off" onChange={e => set({ value: e.target.value })} />}</label>
      <label className="field"><span className="field-label">TTL</span>
        <select value={form.ttl} onChange={e => set({ ttl: e.target.value })}>
          <option value="">{t('Default ({ttl})', { ttl: dnsTtlLabel(dnsInfo?.default_ttl || 3600) })}</option>
          {ttls.map(ttl => <option key={ttl} value={String(ttl)}>{dnsTtlLabel(ttl)}</option>)}
        </select></label>
    </div>;
  }

  // One line: the nameservers a domain's registrar is given.
  function renderDnsNameservers() {
    const names = dnsInfo?.nameservers || [];
    return <div className="dns-ns-line">
      <span className="dns-ns-label"><Network size={14}/> {t('Nameservers')}</span>
      {names.length > 0
        ? <>
          {names.map(name => <code key={name}>{name}</code>)}
          <button type="button" className="mini secondary icon-only" aria-label={t('Copy')} title={t('Copy')}
            onClick={() => copyText(names.join('\n'), t('Copied to clipboard.'))}><Copy size={13}/></button>
        </>
        : <span className="hint">{isAdmin ? t('Not set yet: open Settings.') : t('The administrator has not set the nameservers yet.')}</span>}
    </div>;
  }

  function renderDnsPager() {
    const list = dnsZones;
    const pages = Math.max(1, Math.ceil((list?.total || 0) / (list?.per_page || 50)));
    if (pages <= 1) return null;
    return <div className="firewall-ip-pager">
      <button className="mini secondary" disabled={dnsPage <= 1} onClick={() => setDnsPage(p => Math.max(1, p - 1))}>{t('Previous')}</button>
      <span className="hint">{t('Page {page} of {pages}', { page: dnsPage, pages })}</span>
      <button className="mini secondary" disabled={dnsPage >= pages} onClick={() => setDnsPage(p => p + 1)}>{t('Next')}</button>
    </div>;
  }

  function renderDnsZones() {
    const list = dnsZones;
    const items = list?.items || [];
    return <div className="mail-tab">
      {renderDnsNameservers()}
      <form className="mail-search dns-search" onSubmit={e => { e.preventDefault(); setDnsPage(1); loadDnsZones(1); }}>
        <input value={dnsQuery} placeholder={t('Search domains')} aria-label={t('Search domains')} onChange={e => setDnsQuery(e.target.value)} />
        <button type="submit" className="secondary icon-only" aria-label={t('Search')} title={t('Search')}><Search size={14}/></button>
      </form>
      {list === null && <p className="hint">{t('Loading…')}</p>}
      {list && items.length === 0 && <EmptyState icon={Network} message={dnsQuery.trim() ? t('No domain matches the search.') : t('No domains yet.')} />}
      {items.length > 0 && <div className="table">
        {items.map(zone => <div className="row dns-zone-row" key={zone.name}>
          <span className="mail-row-name">
            <strong>{zone.name}</strong>
            <small>{[isAdmin && zone.owner ? `${t('Account')}: ${zone.owner}` : '', zone.created_at ? `${t('Added')} ${new Date(zone.created_at).toLocaleDateString()}` : '', zone.on_panel === false ? t('No longer on the panel') : ''].filter(Boolean).join(' · ')}</small>
          </span>
          <span className="row-actions">
            <button className="mini secondary" disabled={!!loading} onClick={() => openDnsZone(zone)}><Pencil size={13}/> {t('Records')}</button>
          </span>
        </div>)}
      </div>}
      {renderDnsPager()}
    </div>;
  }

  function renderDnsSettings() {
    const f = dnsSettings;
    const set = patch => setDnsSettings(prev => ({ ...prev, ...patch }));
    const server = f?.server || {};
    const serving = server.running && server.api;
    const address = [dnsInfo?.addresses?.ipv4?.[0], dnsInfo?.addresses?.ipv6?.[0]].filter(Boolean).join(' / ');
    const ttl = Number(f?.ttl) || 3600;
    const ttls = DNS_TTLS.includes(ttl) ? DNS_TTLS : [...DNS_TTLS, ttl].sort((a, b) => a - b);
    return <section className="section dns-page">
      <div className="section-title">
        <div className="waf-detail-title">
          <button className="secondary" onClick={() => setDnsTab('zones')}><ArrowLeft size={14}/> {t('DNS Manager')}</button>
          <div><h2>{t('DNS settings')}</h2>
            <p className="hint">{t('The nameservers and default TTL of every zone on this server, and what a new zone holds.')}</p></div>
        </div>
      </div>
      {!f ? <p className="hint">{t('Loading…')}</p> : <div className="create-inline">
        <div className="dns-server">
          <span className={`badge ${serving ? 'ok' : 'bad'}`}>{serving ? t('PowerDNS is running') : t('PowerDNS is not running')}</span>
          <span className={`badge ${server.port_open ? 'ok' : 'warn'}`}>{server.port_open ? t('Port 53 open') : t('Port 53 closed')}</span>
          {server.listen?.length > 0 && <span className="hint">{t('Listening on')} {server.listen.join(', ')}</span>}
        </div>
        <div className="mail-settings-grid">
          <label className="field"><span className="field-label">{t('Nameserver 1')}</span>
            <input value={f.ns1} placeholder="ns1.example.com" spellCheck={false} onChange={e => set({ ns1: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Nameserver 2')}</span>
            <input value={f.ns2} placeholder="ns2.example.com" spellCheck={false} onChange={e => set({ ns2: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('IP address for new zones')}</span>
            <input value={f.zone_ip || ''} list="dns-server-ipv4" spellCheck={false} onChange={e => set({ zone_ip: e.target.value })} />
            <datalist id="dns-server-ipv4">{(f.server_ipv4 || []).map(ip => <option key={ip} value={ip} />)}</datalist></label>
          <label className="field"><span className="field-label">{t('Default TTL')}</span>
            <select value={String(ttl)} onChange={e => set({ ttl: e.target.value })}>
              {ttls.map(value => <option key={value} value={String(value)}>{dnsTtlLabel(value)}</option>)}
            </select></label>
        </div>
        <label className="check-line"><input type="checkbox" checked={!!f.auto_zone} onChange={e => set({ auto_zone: e.target.checked })} /> {t('Give every domain on the server a DNS zone')}</label>
        <label className="field dns-template"><span className="field-label">{t('Records for new zones')}</span>
          <textarea rows={6} value={f.template || ''} spellCheck={false} onChange={e => set({ template: e.target.value })} /></label>
        <p className="hint dns-template-hint">{t('One record per line: name, type, then the value; an MX value starts with its priority. {ip} is the address for new zones, {domain} the zone, and {spf} the SPF record:')} <code>{f.spf}</code>. {t('Zones that already exist are not changed.')}</p>
        <p className="hint">{t('A changed nameserver is written into the NS and SOA records of every zone. Register both names as glue (child nameserver) records at the registrar of their domain, pointing at this server.')} {address && t('This server: {address}.', { address })}</p>
        <div className="actions">
          <button type="button" disabled={!String(f.ns1 || '').trim() || !String(f.ns2 || '').trim() || !!loading} onClick={saveDnsSettings}><Save size={14}/> {t('Save settings')}</button>
          <button type="button" className="secondary" disabled={!!loading || !f.auto_zone} onClick={syncDnsZones}><RefreshCw size={14}/> {t('Sync zones now')}</button>
        </div>
      </div>}
      {/* BPanel only: a zone for a name no website or mail domain holds. */}
      <div className="create-inline dns-new-zone">
        <div className="create-inline-head"><strong>{t('A zone for a domain that is not on the panel')}</strong></div>
        <div className="mail-create-grid">
          <label className="field"><span className="field-label">{t('Domain')}</span>
            <input value={dnsNewZone.name} placeholder="example.com" spellCheck={false} onChange={e => setDnsNewZone(prev => ({ ...prev, name: e.target.value.trim().toLowerCase() }))} /></label>
          <label className="field"><span className="field-label">{t('Account')}</span>
            <select value={dnsNewZone.owner_id} onChange={e => setDnsNewZone(prev => ({ ...prev, owner_id: e.target.value }))}>
              <option value="">{t('No owner')}</option>
              {users.map(user => <option key={user.id} value={user.id}>{user.username}</option>)}
            </select></label>
          <button disabled={!dnsNewZone.name.trim() || !!loading} onClick={addDnsZone}><Plus size={14}/> {t('Add zone')}</button>
        </div>
      </div>
    </section>;
  }

  function renderDnsZone() {
    const { zone, records } = dnsZone;
    const delegation = dnsDelegation;
    const statusLabel = { ok: t('Served from here'), missing: t('Not delegated'), different: t('Other nameservers'), unknown: t('Not checked') };
    const statusClass = { ok: 'ok', missing: 'bad', different: 'warn', unknown: '' };
    const term = dnsRecordFilter.trim().toLowerCase();
    const shown = (records || []).filter(r => !term || `${r.name} ${r.type} ${r.value}`.toLowerCase().includes(term));
    const form = dnsRecordForm;
    const edit = dnsRecordEdit;
    const isEditing = record => edit && edit.old.name === record.name && edit.old.type === record.type && edit.old.content === record.content;
    const delegationText = !delegation ? t('Checking the nameservers…')
      : delegation.status === 'ok' ? t('{zone} is answered by this server.', { zone: zone.name })
      : delegation.status === 'different' ? t('{zone} uses other nameservers now ({found}). Set {expected} at its registrar.', { zone: zone.name, found: delegation.found.join(', '), expected: delegation.expected.join(', ') })
      : delegation.status === 'missing' ? t('Set {expected} as the nameservers of {zone} at its registrar. Until then these records are not used.', { expected: delegation.expected.join(', '), zone: zone.name })
      : t('The nameservers of {zone} could not be looked up.', { zone: zone.name });
    return <section className="section dns-zone-page">
      <div className="section-title">
        <div className="waf-detail-title">
          <button className="secondary" onClick={() => { setDnsZone(null); loadDnsZones(); }}><ArrowLeft size={14}/> {t('DNS Manager')}</button>
          <div><h2>{zone.name}</h2>
            <p className="hint">{[isAdmin && zone.owner ? `${t('Account')}: ${zone.owner}` : '', records ? t('{n} records', { n: records.length }) : ''].filter(Boolean).join(' · ')}</p></div>
        </div>
        <div className="actions">
          <button className="secondary" disabled={!!loading} onClick={() => openDnsZone(zone)}><RefreshCw size={14}/> {t('Refresh')}</button>
          <button className="secondary-light" disabled={!!loading || records === null} onClick={restoreDnsDefaults}><RotateCcw size={14}/> {t('Restore panel records')}</button>
          {isAdmin && zone.on_panel === false && <button className="danger" disabled={!!loading} onClick={() => deleteDnsZone(zone)}><Trash2 size={14}/> {t('Delete zone')}</button>}
        </div>
      </div>
      <div className="dns-delegation">
        <span className={`badge ${statusClass[delegation?.status] || ''}`}>{delegation ? statusLabel[delegation.status] || delegation.status : '…'}</span>
        <span className="hint">{delegationText}</span>
      </div>
      <div className="create-inline dns-record-form">
        <div className="create-inline-head"><strong>{t('Add a record')}</strong></div>
        {renderDnsRecordFields(form, patch => setDnsRecordForm(prev => ({ ...prev, ...patch })))}
        <p className="hint">{dnsTypeHint(form.type)} {t('Names are relative to {zone}: @ is the domain itself.', { zone: zone.name })}</p>
        <div className="actions"><button type="button" disabled={!String(form.value).trim() || !!loading || records === null} onClick={addDnsRecord}><Plus size={14}/> {t('Add record')}</button></div>
      </div>
      <div className="mail-toolbar">
        <strong>{t('Records')}</strong>
        <div className="mail-search"><input value={dnsRecordFilter} placeholder={t('Filter records')} aria-label={t('Filter records')} onChange={e => setDnsRecordFilter(e.target.value)} /></div>
      </div>
      {records === null && <p className="hint">{t('Loading…')}</p>}
      {records && <div className="table dns-records">
        <div className="row dns-record-row dns-record-head" aria-hidden="true">
          <span>{t('Name')}</span><span>{t('Type')}</span><span>TTL</span><span>{t('Value')}</span><span/>
        </div>
        {shown.map(record => isEditing(record)
          ? <div className="row dns-record-edit" key={`${record.name}|${record.type}|${record.content}`}>
              {renderDnsRecordFields(edit.form, patch => setDnsRecordEdit(prev => ({ ...prev, form: { ...prev.form, ...patch } })), { lockType: true })}
              <div className="actions">
                <button type="button" className="secondary-light" onClick={() => setDnsRecordEdit(null)}>{t('Cancel')}</button>
                <button type="button" disabled={!String(edit.form.value).trim() || !!loading} onClick={saveDnsRecordEdit}><Save size={14}/> {t('Save')}</button>
              </div>
            </div>
          : <div className="row dns-record-row" key={`${record.name}|${record.type}|${record.content}`}>
              <span className="dns-record-name" title={record.fqdn}>{record.name}</span>
              <span><code className="dns-type">{record.type}</code></span>
              <span className="dns-record-ttl">{dnsTtlLabel(record.ttl)}</span>
              <span className="dns-record-value">{record.priority != null && <small title={t('Priority')}>{record.priority}</small>}<code>{record.value}</code>
                {record.mail && <span className="badge dns-mail-badge" title={t('Kept in step with the email of {domain}', { domain: record.mail })}><Mail size={11}/> {t('Email')}</span>}</span>
              <span className="row-actions">
                {record.locked
                  ? <span className="dns-locked" title={t("Follows DNS Manager's nameserver settings")}><Lock size={13}/></span>
                  : <>
                    <button type="button" className="mini secondary icon-only" disabled={!!loading} aria-label={t('Edit')} title={t('Edit')}
                      onClick={() => setDnsRecordEdit({ old: record, form: { type: record.type, name: record.name, value: record.value, priority: record.priority ?? '', ttl: String(record.ttl || '') } })}><Pencil size={13}/></button>
                    <button type="button" className="mini danger-light icon-only" disabled={!!loading} aria-label={t('Delete')} title={t('Delete')} onClick={() => deleteDnsRecord(record)}><Trash2 size={13}/></button>
                  </>}
              </span>
            </div>)}
        {shown.length === 0 && <p className="hint">{t('No record matches the filter.')}</p>}
      </div>}
    </section>;
  }

  function renderDns() {
    if (dnsZone) return renderDnsZone();
    if (isAdmin && dnsTab === 'settings') return renderDnsSettings();
    return <section className="section dns-page">
      <div className="section-title">
        <div><h2>{t('DNS Manager')}</h2>
          <p className="hint">{isAdmin ? t('Every domain on the panel, answered by this server.') : t('The DNS records of your domains, answered by this server.')}</p></div>
        <div className="actions">
          {isAdmin && <button type="button" className="secondary" onClick={() => setDnsTab('settings')}><SettingsIcon size={14}/> {t('Settings')}</button>}
          <button type="button" className="secondary" disabled={!!loading} onClick={() => { loadDnsInfo(); loadDnsZones(); }}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
      </div>
      {renderDnsZones()}
    </section>;
  }

  function renderCopyBlock(title, text, { multiline = false, copiedMessage } = {}) {
    return <div className="copy-block">
      <div className="copy-block-head">
        <span>{title}</span>
        <button type="button" className="mini secondary" onClick={() => copyText(text, copiedMessage || t('Copied to clipboard.'))}><Copy size={13}/> {t('Copy')}</button>
      </div>
      {multiline ? <pre className="copy-block-code">{text}</pre> : <code className="copy-block-code">{text}</code>}
    </div>;
  }

  function mailDomainOptions(placeholder) {
    return <>
      {placeholder && <option value="">{placeholder}</option>}
      {(mailInfo?.domains || []).map(d => <option key={d.id} value={String(d.id)}>{d.domain}{isAdmin && d.owner ? ` (${d.owner})` : ''}</option>)}
    </>;
  }

  function renderMailFilter(onSearch) {
    return <div className="mail-filter">
      <select value={mailFilter.domain_id} aria-label={t('Domain')} onChange={e => { setMailFilter(prev => ({ ...prev, domain_id: e.target.value })); setMailPage(1); }}>
        {mailDomainOptions(t('All domains'))}
      </select>
      <form className="mail-search" onSubmit={e => { e.preventDefault(); setMailPage(1); onSearch(); }}>
        <input value={mailFilter.q} placeholder={t('Search')} aria-label={t('Search')} onChange={e => setMailFilter(prev => ({ ...prev, q: e.target.value }))} />
        <button type="submit" className="secondary icon-only" aria-label={t('Search')} title={t('Search')}><Search size={14}/></button>
      </form>
    </div>;
  }

  function renderMailPager(list) {
    const pages = Math.max(1, Math.ceil((list?.total || 0) / (list?.per_page || 50)));
    if (pages <= 1) return null;
    return <div className="firewall-ip-pager">
      <button className="mini secondary" disabled={mailPage <= 1} onClick={() => setMailPage(p => Math.max(1, p - 1))}>{t('Previous')}</button>
      <span className="hint">{t('Page {page} of {pages}', { page: mailPage, pages })}</span>
      <button className="mini secondary" disabled={mailPage >= pages} onClick={() => setMailPage(p => p + 1)}>{t('Next')}</button>
    </div>;
  }

  function renderMailboxes() {
    const info = mailInfo;
    const list = mailboxList;
    const items = list?.items || [];
    const limit = info.mailbox_limit;
    const atLimit = !isAdmin && !!info.at_limit;
    const local = mailboxForm.local_part.trim().toLowerCase();
    const canCreate = !!mailboxForm.domain_id && /^[a-z0-9]([a-z0-9._-]{0,62}[a-z0-9])?$/.test(local) && !local.includes('..')
      && mailboxForm.password.length >= 8 && /[A-Za-z]/.test(mailboxForm.password) && /\d/.test(mailboxForm.password);
    const openCreate = () => {
      setShowCreateMailbox(true);
      setMailboxForm(prev => ({
        ...prev,
        domain_id: prev.domain_id || mailFilter.domain_id || String(info.domains[0]?.id || ''),
        password: prev.password || mailPassword(),
        quota_mb: prev.quota_mb === '' ? String(info.default_quota_mb || 1024) : prev.quota_mb,
      }));
    };
    return <div className="mail-tab">
      <div className="mail-toolbar">
        {renderMailFilter(() => loadMailboxes(1))}
        {!showCreateMailbox && <button type="button" disabled={atLimit} title={atLimit ? t('Mailbox limit reached') : ''} onClick={openCreate}><Plus size={15}/> {t('New mailbox')}</button>}
      </div>
      {atLimit && <p className="hint">{limit
        ? t('You have used all {n} of your mailboxes. Delete one, or ask your provider for more.', { n: limit })
        : t('Your hosting package does not include mailboxes. Ask your provider.')}</p>}
      {showCreateMailbox && <div className="create-inline">
        <div className="create-inline-head">
          <strong>{t('New mailbox')}</strong>
          <button type="button" className="secondary icon-only mini" onClick={() => setShowCreateMailbox(false)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>
        </div>
        <div className="mail-create-grid">
          <div className="field mail-address-field"><span className="field-label">{t('Address')}</span>
            <div className="mail-address-input">
              <input value={mailboxForm.local_part} placeholder="info" autoComplete="off" spellCheck={false} aria-label={t('Mailbox name')}
                onChange={e => setMailboxForm(prev => ({ ...prev, local_part: e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, '') }))} />
              <span>@</span>
              <select value={mailboxForm.domain_id} aria-label={t('Domain')} onChange={e => setMailboxForm(prev => ({ ...prev, domain_id: e.target.value }))}>{mailDomainOptions(t('Choose a domain'))}</select>
            </div>
          </div>
          <div className="field"><span className="field-label">{t('Password')}</span>
            <div className="password-with-generate">
              <input value={mailboxForm.password} autoComplete="new-password" spellCheck={false} placeholder={t('8+ characters, letters and digits')} onChange={e => setMailboxForm(prev => ({ ...prev, password: e.target.value }))} data-lpignore="true" data-1p-ignore="true" />
              <button type="button" className="secondary icon-only" title={t('Generate random password')} aria-label={t('Generate random password')} onClick={() => setMailboxForm(prev => ({ ...prev, password: mailPassword() }))}><Dices size={15}/></button>
              <button type="button" className="secondary icon-only" title={t('Copy')} aria-label={t('Copy')} onClick={() => copyText(mailboxForm.password, t('Copied to clipboard.'))}><Copy size={15}/></button>
            </div>
          </div>
          <div className="field mail-quota-field"><span className="field-label">{t('Size (MB)')}{isAdmin && <em> {t('0 = unlimited')}</em>}</span>
            <input type="number" min={isAdmin ? 0 : 1} max={isAdmin ? 1048576 : info.max_user_quota_mb} value={mailboxForm.quota_mb} onChange={e => setMailboxForm(prev => ({ ...prev, quota_mb: e.target.value }))} />
          </div>
          <button disabled={!canCreate || !!loading} onClick={createMailbox}><Plus size={14}/> {t('Create')}</button>
        </div>
        <p className="hint">{t('Copy the password now — it is not shown again. It signs in to webmail and to any mail app, with the full address as the username.')}</p>
      </div>}
      {list === null && <p className="hint">{t('Loading…')}</p>}
      {list && items.length === 0 && <EmptyState icon={Inbox} message={mailFilter.q || mailFilter.domain_id ? t('No mailbox matches.') : t('No mailboxes yet.')} />}
      {items.length > 0 && <div className="table">
        {items.map(box => {
          const percent = box.quota_mb && box.used_mb != null ? Math.min(100, Math.round(box.used_mb / box.quota_mb * 100)) : null;
          return <div className="row mail-row" key={box.id}>
            <span className="mail-row-name">
              <strong>{box.address}</strong>
              <small>
                {!box.enabled && <span className="badge warn">{t('Suspended')}</span>}
                {isAdmin && box.owner ? <span>{t('Account')}: {box.owner}</span> : null}
              </small>
            </span>
            <span className="mail-row-usage">
              <small>{box.used_mb != null ? t('{n} MB', { n: box.used_mb }) : '—'} / {box.quota_mb ? t('{n} MB', { n: box.quota_mb }) : t('unlimited')}</small>
              {percent != null && <span className={`mail-meter ${percent >= 90 ? 'bad' : percent >= 75 ? 'warn' : ''}`}><span style={{ width: `${percent}%` }} /></span>}
            </span>
            <span className="row-actions">
              <button className="mini" disabled={!!loading || !box.enabled} onClick={() => openWebmail(box)} title={t('Open this mailbox in webmail, no password needed')}><Mail size={13}/> {t('Webmail')}</button>
              <button className="mini secondary" disabled={!!loading} onClick={() => setMailboxEdit({ box, password: '', quota_mb: String(box.quota_mb) })}><Pencil size={13}/> {t('Edit')}</button>
              <button className="mini secondary" disabled={!!loading} onClick={() => setMailboxEnabled(box, !box.enabled)}>{box.enabled ? <><Ban size={13}/> {t('Suspend')}</> : <><Play size={13}/> {t('Resume')}</>}</button>
              <button className="mini danger" disabled={!!loading} onClick={() => deleteMailbox(box)} aria-label={t('Delete {name}', { name: box.address })} title={t('Delete')}><Trash2 size={13}/></button>
            </span>
          </div>;
        })}
      </div>}
      {renderMailPager(list)}
    </div>;
  }

  function renderForwarders() {
    const info = mailInfo;
    const list = forwarderList;
    const items = list?.items || [];
    const local = forwarderForm.local_part.trim().toLowerCase();
    const canCreate = !!forwarderForm.domain_id && /^[a-z0-9]([a-z0-9._-]{0,62}[a-z0-9])?$/.test(local) && splitAddresses(forwarderForm.destinations).length > 0;
    return <div className="mail-tab">
      <div className="mail-toolbar">
        {renderMailFilter(() => loadForwarders(1))}
        {!showCreateForwarder && <button type="button" onClick={() => { setShowCreateForwarder(true); setForwarderForm(prev => ({ ...prev, domain_id: prev.domain_id || mailFilter.domain_id || String(info.domains[0]?.id || '') })); }}><Plus size={15}/> {t('New forwarder')}</button>}
      </div>
      {showCreateForwarder && <div className="create-inline">
        <div className="create-inline-head">
          <strong>{t('New forwarder')}</strong>
          <button type="button" className="secondary icon-only mini" onClick={() => setShowCreateForwarder(false)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>
        </div>
        <div className="mail-create-grid">
          <div className="field mail-address-field"><span className="field-label">{t('Address')}</span>
            <div className="mail-address-input">
              <input value={forwarderForm.local_part} placeholder="sales" autoComplete="off" spellCheck={false} aria-label={t('Forwarder name')}
                onChange={e => setForwarderForm(prev => ({ ...prev, local_part: e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, '') }))} />
              <span>@</span>
              <select value={forwarderForm.domain_id} aria-label={t('Domain')} onChange={e => setForwarderForm(prev => ({ ...prev, domain_id: e.target.value }))}>{mailDomainOptions(t('Choose a domain'))}</select>
            </div>
          </div>
          <div className="field mail-destinations-field"><span className="field-label">{t('Forward to')}</span>
            <textarea rows={2} value={forwarderForm.destinations} spellCheck={false} placeholder={t('one or more addresses, separated by commas')} onChange={e => setForwarderForm(prev => ({ ...prev, destinations: e.target.value }))} />
          </div>
          <button disabled={!canCreate || !!loading} onClick={createForwarder}><Plus size={14}/> {t('Create')}</button>
        </div>
        <p className="hint">{t('If a mailbox has the same address, it keeps a copy of each message as well.')}</p>
      </div>}
      {list === null && <p className="hint">{t('Loading…')}</p>}
      {list && items.length === 0 && <EmptyState icon={Forward} message={mailFilter.q || mailFilter.domain_id ? t('No forwarder matches.') : t('No forwarders yet.')} />}
      {items.length > 0 && <div className="table">
        {items.map(item => <div className="row mail-row" key={item.id}>
          <span className="mail-row-name"><strong>{item.address}</strong>{item.keeps_copy && <small><span className="badge">{t('Keeps a copy')}</span></small>}</span>
          <span className="mail-row-destinations"><MoveRight size={13}/> <span>{item.destinations.join(', ')}</span></span>
          <span className="row-actions">
            <button className="mini secondary" disabled={!!loading} onClick={() => setForwarderEdit({ item, destinations: item.destinations.join(', ') })}><Pencil size={13}/> {t('Edit')}</button>
            <button className="mini danger" disabled={!!loading} onClick={() => deleteForwarder(item)} aria-label={t('Delete {name}', { name: item.address })} title={t('Delete')}><Trash2 size={13}/></button>
          </span>
        </div>)}
      </div>}
      {renderMailPager(list)}
    </div>;
  }

  function renderMailDomains() {
    const info = mailInfo;
    const domains = info.domains || [];
    const candidates = info.candidates || [];
    return <div className="mail-tab">
      <div className="create-inline">
        <div className="create-inline-head"><strong>{t('Turn on email for a domain')}</strong></div>
        <div className="mail-create-grid">
          {isAdmin
            ? <div className="field"><span className="field-label">{t('Domain')}</span>
                <input list="mail-domain-candidates" value={mailDomainForm.domain} placeholder="example.com" spellCheck={false}
                  onChange={e => setMailDomainForm(prev => ({ ...prev, domain: e.target.value.trim().toLowerCase() }))} />
                <datalist id="mail-domain-candidates">{candidates.map(name => <option key={name} value={name} />)}</datalist>
              </div>
            : <div className="field"><span className="field-label">{t('Domain')}</span>
                <select value={mailDomainForm.domain} onChange={e => setMailDomainForm(prev => ({ ...prev, domain: e.target.value }))}>
                  <option value="">{t('Choose one of your websites')}</option>
                  {candidates.map(name => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>}
          {isAdmin && <div className="field"><span className="field-label">{t('Account')}</span>
            <select value={mailDomainForm.owner_id} onChange={e => setMailDomainForm(prev => ({ ...prev, owner_id: e.target.value }))}>
              <option value="">{t("The website's owner")}</option>
              {users.map(user => <option key={user.id} value={user.id}>{user.username}</option>)}
            </select>
          </div>}
          <button disabled={!mailDomainForm.domain.trim() || !!loading} onClick={addMailDomain}><Plus size={14}/> {t('Turn on email')}</button>
        </div>
        {!isAdmin && candidates.length === 0 && <p className="hint">{t('Every domain of your websites already has email. Add a website or a domain alias to use another one.')}</p>}
        <p className="hint">{t('Mail for a domain arrives here once its MX record points at this server; the DNS records to add are shown next.')}</p>
      </div>
      {domains.length === 0 && <EmptyState icon={Mail} message={t('No mail domains yet.')} />}
      {domains.length > 0 && <div className="table">
        {domains.map(d => {
          const draft = String(catchAllDraft[d.id] ?? d.catch_all ?? '');
          return <div className="row mail-domain-row" key={d.id}>
            <span className="mail-row-name">
              <strong>{d.domain}</strong>
              <small>{t('{mailboxes} mailboxes · {forwarders} forwarders', { mailboxes: d.mailboxes, forwarders: d.forwarders })}{isAdmin && d.owner ? ` · ${t('Account')}: ${d.owner}` : ''}</small>
            </span>
            <span className="mail-catchall">
              <span className="field-label">{t('Catch-all')}</span>
              <span className="mail-catchall-input">
                <input value={draft} placeholder={t('Off: unknown addresses are refused')} spellCheck={false} aria-label={t('Catch-all for {domain}', { domain: d.domain })}
                  onChange={e => setCatchAllDraft(prev => ({ ...prev, [d.id]: e.target.value }))} />
                {draft.trim() !== (d.catch_all || '') && <button className="mini" disabled={!!loading} onClick={() => saveCatchAll(d)} aria-label={t('Save')} title={t('Save')}><Save size={13}/></button>}
              </span>
            </span>
            <label className="check-line mail-webmail-host" title={t('Serve webmail at webmail.{domain} with its own certificate', { domain: d.domain })}>
              <input type="checkbox" checked={!!d.webmail_host} disabled={!!loading} onChange={e => toggleWebmailHost(d, e.target.checked)} />
              <span>webmail.{d.domain}</span>
            </label>
            <span className="row-actions">
              <button className="mini secondary" disabled={!!loading} onClick={() => openMailDns(d)}><Globe size={13}/> {t('DNS records')}</button>
              <button className="mini danger" disabled={!!loading} onClick={() => deleteMailDomain(d)} aria-label={t('Delete {name}', { name: d.domain })} title={t('Delete')}><Trash2 size={13}/></button>
            </span>
          </div>;
        })}
      </div>}
    </div>;
  }

  // A relay's DNS template: what every domain sending through it publishes.
  function renderDnsRecordEditor(rows, onChange) {
    const setRow = (index, patch) => onChange(rows.map((row, i) => i === index ? { ...row, ...patch } : row));
    return <div className="dns-editor">
      {rows.map((row, index) => <div className={`dns-editor-row${row.type === 'MX' ? ' with-priority' : ''}`} key={index}>
        <select value={row.type} aria-label={t('Type')} onChange={e => setRow(index, { type: e.target.value })}>
          {['TXT', 'CNAME', 'MX', 'A', 'AAAA'].map(type => <option key={type} value={type}>{type}</option>)}
        </select>
        <input value={row.name} placeholder="@" aria-label={t('Name')} spellCheck={false} onChange={e => setRow(index, { name: e.target.value })} />
        {row.type === 'MX' && <input type="number" min="0" max="65535" value={row.priority ?? ''} placeholder="10" aria-label={t('Priority')} onChange={e => setRow(index, { priority: e.target.value })} />}
        <input className="dns-editor-value" value={row.value} placeholder={t('Value ({domain} = the domain)')} aria-label={t('Value')} spellCheck={false} onChange={e => setRow(index, { value: e.target.value })} />
        <button type="button" className="mini danger-light icon-only" aria-label={t('Remove')} title={t('Remove')} onClick={() => onChange(rows.filter((_, i) => i !== index))}><Trash2 size={13}/></button>
      </div>)}
      <div className="actions dns-editor-actions">
        <button type="button" className="mini secondary" disabled={rows.length >= 10} onClick={() => onChange([...rows, { type: 'TXT', name: '@', value: '', priority: '' }])}><Plus size={13}/> {t('Add a record')}</button>
      </div>
      <p className="hint">{t('Names are relative to each domain that uses the relay: @ is the domain itself, brevo1._domainkey a name under it. {domain} in a value becomes the domain name.')}</p>
    </div>;
  }

  function renderMailDns() {
    const { domain, records, relay, hostedZone } = mailDns;
    const statusLabel = { ok: t('Found'), missing: t('Missing'), different: t('Different'), unknown: t('Not checked') };
    const statusClass = { ok: 'ok', missing: 'bad', different: 'warn', unknown: '' };
    const titles = {
      mx: t('Receiving mail (MX)'),
      mail: t('Mail server address (A)'),
      spf: t('Allowed senders (SPF)'),
      dkim: t('Signature key (DKIM)'),
      dmarc: t('Policy (DMARC)'),
      webmail: t('Webmail address (optional)'),
    };
    const titleFor = record => titles[record.key] || t('Asked for by the relay {relay}', { relay: record.relay });
    return <section className="section mail-dns-page">
      <div className="section-title">
        <div className="waf-detail-title">
          <button className="secondary" onClick={() => setMailDns(null)}><ArrowLeft size={14}/> {t('Email')}</button>
          <div><h2>{t('DNS records for {domain}', { domain: domain.domain })}</h2>
            <p className="hint">{t('Add these at the DNS provider of {domain}. A change can take a few hours to be seen everywhere.', { domain: domain.domain })}</p></div>
        </div>
        <div className="actions">
          <button className="secondary" disabled={!!loading || records === null} onClick={() => openMailDns(domain)}><RefreshCw size={14}/> {t('Check again')}</button>
          <button className="secondary-light" disabled={!!loading} onClick={() => rotateMailDkim(domain)}><KeyRound size={14}/> {t('New DKIM key')}</button>
        </div>
      </div>
      {relay && <div className="mail-relay-card">
        <div className="mail-relay-card-head"><Send size={15}/><strong>{t('Outgoing mail')}</strong></div>
        {isAdmin && <select value={relay.choice} disabled={!!loading} aria-label={t('Outgoing mail')} onChange={e => saveDomainRelay(e.target.value)}>
          <option value="">{t('Server default')}</option>
          <option value="direct">{t('Direct, without a relay')}</option>
          {relay.options.map(option => <option key={option.id} value={option.id}>{t('Relay: {name}', { name: option.name })}</option>)}
        </select>}
        <p className="hint">{relay.effective_name
          ? t('Mail from {domain} leaves through the relay {relay}; the records it asks for are listed below.', { domain: domain.domain, relay: relay.effective_name })
          : t('Mail from {domain} is delivered directly from this server.', { domain: domain.domain })}</p>
      </div>}
      {hostedZone && <div className="info-box dns-managed-box">
        <Network size={14}/>
        <span>{t('DNS Manager on this server holds the zone {zone} and keeps these records in it, taking back the ones email no longer needs. "In the zone" is what the zone holds; the other badge is what public DNS answers, which matches once the domain\'s nameservers point here.', { zone: hostedZone })}</span>
        <button type="button" className="mini secondary" onClick={() => openDnsZone({ name: hostedZone })}>{t('Open zone')}</button>
      </div>}
      {records === null && <p className="hint">{t('Checking DNS…')}</p>}
      {records && <div className="mail-dns-list">
        {records.map(record => <div className="mail-dns-record" key={record.key}>
          <div className="mail-dns-head">
            <strong>{titleFor(record)}</strong>
            <span className="mail-dns-type"><code>{record.type}</code>{record.priority != null && <small>{t('priority {n}', { n: record.priority })}</small>}</span>
            {hostedZone && record.in_zone != null && <span className={`badge mail-dns-zone ${record.in_zone ? 'ok' : 'warn'}`}
              title={t("DNS Manager's zone on this server")}>{record.in_zone ? t('In the zone') : t('Not in the zone')}</span>}
            <span className={`badge mail-dns-status ${statusClass[record.status] || ''}`} title={t('What public DNS answers now')}>{statusLabel[record.status] || record.status}</span>
          </div>
          {renderCopyBlock(t('Name'), record.name)}
          {renderCopyBlock(t('Value'), record.value, { multiline: record.key === 'dkim' })}
          {record.status === 'different' && (record.found || []).length > 0 && <p className="hint">{t('Found now:')} <code>{record.found.join(' | ')}</code></p>}
          {record.key === 'webmail' && <p className="hint">{t('Only needed for webmail.{domain}; turn that on in the Domains tab once this record is in place.', { domain: domain.domain })}</p>}
        </div>)}
      </div>}
    </section>;
  }

  function relayTlsLabel(tls) {
    return { starttls: 'STARTTLS', ssl: 'SSL/TLS', none: t('no TLS') }[tls] || tls;
  }

  function renderRelayForm() {
    const f = relayForm;
    const set = patch => setRelayForm(prev => ({ ...prev, ...patch }));
    const canSave = f.name.trim() && f.host.trim() && (!f.username.trim() || f.password || f.password_set);
    return <div className="mail-tab">
      <div className="create-inline mail-relay-form">
        <div className="create-inline-head">
          <strong>{f.id ? t('Edit relay {name}', { name: f.name }) : t('New relay')}</strong>
          <button type="button" className="secondary icon-only mini" onClick={() => setRelayForm(null)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>
        </div>
        <div className="mail-settings-grid">
          <label className="field"><span className="field-label">{t('Name')}</span><input value={f.name} placeholder="Brevo" onChange={e => set({ name: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Relay host')}</span><input value={f.host} placeholder="smtp-relay.brevo.com" spellCheck={false} onChange={e => set({ host: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Port')}</span><input type="number" min="1" max="65535" value={f.port}
            onChange={e => set({ port: e.target.value, ...(e.target.value === '465' ? { tls: 'ssl' } : f.tls === 'ssl' ? { tls: 'starttls' } : {}) })} /></label>
          <label className="field"><span className="field-label">TLS</span>
            <select value={f.tls} onChange={e => set({ tls: e.target.value })}>
              <option value="starttls">STARTTLS</option>
              <option value="ssl">SSL/TLS</option>
              <option value="none">{t('None (private network only)')}</option>
            </select></label>
          <label className="field"><span className="field-label">{t('Username')}</span><input value={f.username} autoComplete="off" spellCheck={false} onChange={e => set({ username: e.target.value })} data-lpignore="true" data-1p-ignore="true" /></label>
          <label className="field"><span className="field-label">{t('Password')}</span><input type="password" value={f.password} autoComplete="new-password"
            placeholder={f.password_set ? t('Saved — leave empty to keep') : ''} onChange={e => set({ password: e.target.value })} data-lpignore="true" data-1p-ignore="true" /></label>
        </div>
        <div className="mail-relay-template">
          <strong>{t('Mail DNS template')}</strong>
          <p className="hint">{t("What every domain that sends through this relay must publish. Customers see it on their domain's DNS records page and set up their domain from it.")}</p>
          <label className="field"><span className="field-label">{t('SPF for this relay')} <em>{t('added to the SPF record of every domain that uses it')}</em></span>
            <input value={f.spf_include} placeholder="include:spf.brevo.com" spellCheck={false} list="mail-spf-includes" onChange={e => set({ spf_include: e.target.value })} />
            <datalist id="mail-spf-includes">{MAIL_SPF_INCLUDES.map(item => <option key={item} value={item} />)}</datalist></label>
          <div className="field"><span className="field-label">{t('DNS records the relay asks for')}</span>
            {renderDnsRecordEditor(f.dns_records, rows => set({ dns_records: rows }))}</div>
        </div>
        {!f.id && <label className="check-line"><input type="checkbox" checked={!!f.make_default} onChange={e => set({ make_default: e.target.checked })} /> {t('Use it as the default relay')}</label>}
        <p className="hint">{t("587 uses STARTTLS and 465 SSL/TLS, and the relay's certificate must be valid. Leave the username empty for a relay that knows this server by its address.")}</p>
        <div className="actions">
          <button type="button" className="secondary-light" onClick={() => setRelayForm(null)}>{t('Cancel')}</button>
          <button type="button" disabled={!canSave || !!loading} onClick={saveRelay}><Save size={14}/> {t('Save relay')}</button>
        </div>
      </div>
    </div>;
  }

  function renderMailRelays() {
    if (relayForm) return renderRelayForm();
    const data = mailRelays;
    const relays = data?.relays || [];
    return <div className="mail-tab">
      <p className="hint">{t('A relay (smarthost) sends this server\'s outgoing mail for it: needed where the provider blocks port 25, and it can help mail reach the inbox. Each domain uses the default relay unless its DNS page picks another one or direct delivery.')}</p>
      <div className="mail-toolbar">
        <label className="field mail-default-relay"><span className="field-label">{t('Default relay')}</span>
          <select value={data?.default_relay || ''} disabled={!data || !!loading} onChange={e => setDefaultRelay(e.target.value)}>
            <option value="">{t('None: deliver directly')}</option>
            {relays.map(relay => <option key={relay.id} value={relay.id}>{relay.name}</option>)}
          </select></label>
        <button type="button" onClick={() => editRelay(null)}><Plus size={15}/> {t('New relay')}</button>
      </div>
      {data === null && <p className="hint">{t('Loading…')}</p>}
      {data && relays.length === 0 && <EmptyState icon={Send} message={t('No relay yet: mail leaves this server directly.')} />}
      {relays.length > 0 && <div className="table">
        {relays.map(relay => <div className="row mail-relay-row" key={relay.id}>
          <span className="mail-row-name">
            <strong>{relay.name}{relay.default && <span className="badge ok">{t('Default')}</span>}</strong>
            <small>{relay.host}:{relay.port} · {relayTlsLabel(relay.tls)}{relay.username ? ` · ${relay.username}` : ` · ${t('no login')}`}</small>
          </span>
          <span className="mail-relay-meta">
            {relay.spf_include && <small><code>{relay.spf_include}</code></small>}
            {(relay.dns_records || []).length > 0 && <small>{t('{n} DNS records', { n: relay.dns_records.length })}</small>}
            {(relay.domains || []).length > 0 && <small>{t('Chosen by {domains}', { domains: relay.domains.join(', ') })}</small>}
          </span>
          <span className="row-actions">
            <button className="mini secondary" disabled={!!loading} onClick={() => editRelay(relay)}><Pencil size={13}/> {t('Edit')}</button>
            <button className="mini danger" disabled={!!loading} onClick={() => deleteRelay(relay)} aria-label={t('Delete {name}', { name: relay.name })} title={t('Delete')}><Trash2 size={13}/></button>
          </span>
        </div>)}
      </div>}
      <h3 className="mail-subhead">{t('Send a test message')}</h3>
      <div className="mail-relay-test">
        <input type="email" value={relayTestTo} onChange={e => setRelayTestTo(e.target.value)} placeholder="you@gmail.com" aria-label={t('Send a test message to')} />
        <button className="secondary" disabled={!!loading || !relayTestTo.includes('@')} onClick={testRelay}><Send size={14}/> {t('Send a test message')}</button>
      </div>
      <p className="hint">{t('Sent from postmaster at the server name, through the relay the default route uses. What Exim logged for it is shown, the receiving server\'s answer included.')}</p>
      {relayTestLines && <pre className="mail-log">{relayTestLines.length ? relayTestLines.join('\n') : t('Exim logged nothing more about it.')}</pre>}
    </div>;
  }

  function rspamdActionLabel(action) {
    return {
      'no action': t('Delivered'),
      'add header': t('Marked as spam'),
      'rewrite subject': t('Subject marked'),
      greylist: t('Greylisted'),
      'soft reject': t('Deferred'),
      reject: t('Rejected'),
    }[action] || action;
  }

  function renderLogViewer(lines, query, setQuery, reload) {
    return <>
      <div className="mail-toolbar mail-log-toolbar">
        <form className="mail-search" onSubmit={e => { e.preventDefault(); reload(query); }}>
          <input value={query.q} placeholder={t('Filter, e.g. an address or a message ID')} aria-label={t('Filter')} onChange={e => setQuery(prev => ({ ...prev, q: e.target.value }))} />
          <button type="submit" className="secondary icon-only" aria-label={t('Search')} title={t('Search')}><Search size={14}/></button>
        </form>
        <select value={query.lines} aria-label={t('Lines')} onChange={e => { const next = { ...query, lines: Number(e.target.value) }; setQuery(next); reload(next); }}>
          {[200, 500, 1000, 3000].map(n => <option key={n} value={n}>{t('Last {n} lines', { n })}</option>)}
        </select>
        <button type="button" className="secondary" disabled={!!loading} onClick={() => reload(query)}><RefreshCw size={14}/> {t('Refresh')}</button>
      </div>
      {lines === null ? <p className="hint">{t('Loading…')}</p>
        : lines.length ? <pre className="mail-log">{lines.join('\n')}</pre>
          : <p className="hint">{query.q ? t('No line matches.') : t('The log is empty.')}</p>}
    </>;
  }

  function renderMailRspamd() {
    const stat = rspamdStat;
    const list = rspamdHistory;
    const pages = Math.max(1, Math.ceil((list?.total || 0) / (list?.per_page || 50)));
    const actionClass = { reject: 'bad', 'soft reject': 'warn', greylist: 'warn', 'add header': 'warn', 'rewrite subject': 'warn', 'no action': 'ok' };
    const cards = [['Scanned', stat?.scanned], ['Spam', stat?.spam], ['Ham', stat?.ham], ['Learned', stat?.learned]];
    const addressOf = text => (String(text || '').match(/[^\s<>"]+@[^\s<>"]+/) || [''])[0].toLowerCase();
    const f = mailSettingsForm;
    return <div className="mail-tab">
      <div className="mail-stat-grid">
        {cards.map(([label, value]) => <div className="mail-stat" key={label}><small>{t(label)}</small><strong>{value ?? '—'}</strong></div>)}
        {stat && Object.entries(stat.actions || {}).filter(([, count]) => count > 0).map(([action, count]) =>
          <div className="mail-stat" key={action}><small>{rspamdActionLabel(action)}</small><strong>{count}</strong></div>)}
      </div>
      <div className="segmented-control" role="tablist" aria-label="Rspamd">
        {[['history', 'Scan history'], ['log', 'Log'], ['allow', 'Allowlist']].map(([id, label]) => <button key={id} type="button" role="tab"
          aria-selected={rspamdView === id} className={rspamdView === id ? 'active' : ''} onClick={() => setRspamdView(id)}>{t(label)}</button>)}
      </div>
      {rspamdView === 'history' && <>
        <div className="mail-toolbar">
          <form className="mail-search" onSubmit={e => { e.preventDefault(); loadRspamdHistory(1); }}>
            <input value={rspamdFilter.q} placeholder={t('Sender, recipient, subject or IP')} aria-label={t('Search')} onChange={e => setRspamdFilter(prev => ({ ...prev, q: e.target.value }))} />
            <button type="submit" className="secondary icon-only" aria-label={t('Search')} title={t('Search')}><Search size={14}/></button>
          </form>
          <select value={rspamdFilter.action} aria-label={t('Result')} onChange={e => loadRspamdHistory(1, e.target.value)}>
            <option value="">{t('Every result')}</option>
            {['no action', 'add header', 'rewrite subject', 'greylist', 'soft reject', 'reject'].map(action => <option key={action} value={action}>{rspamdActionLabel(action)}</option>)}
          </select>
          <button type="button" className="secondary" disabled={!!loading} onClick={() => { loadRspamdStat(); loadRspamdHistory(rspamdFilter.page); }}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {list === null && <p className="hint">{t('Loading…')}</p>}
        {list && list.items.length === 0 && <EmptyState icon={ShieldCheck} message={rspamdFilter.q || rspamdFilter.action ? t('No scanned message matches.') : t('No message has been scanned yet.')} />}
        {list && list.items.length > 0 && <div className="table">
          {list.items.map((item, index) => {
            const sender = addressOf(item.from) || addressOf(item.envelope_from);
            const senderDomain = sender.split('@')[1] || '';
            return <div className="row rspamd-row" key={`${item.time}-${index}`}>
              <span className="rspamd-when">
                <small>{formatFileTime(item.time)}</small>
                <span className={`badge ${actionClass[item.action] || ''}`}>{rspamdActionLabel(item.action)}</span>
              </span>
              <span className="mail-row-name">
                <strong title={item.subject}>{item.subject || t('(no subject)')}</strong>
                <small>{item.from || '—'} → {item.to.join(', ') || '—'}</small>
                {item.ip && <small>{item.ip}{item.user ? ` · ${t('signed in as {user}', { user: item.user })}` : ''}</small>}
                {item.allowed
                  ? <small className="rspamd-allowed">{t('This sender is on the allowlist.')}</small>
                  : sender && item.action !== 'no action' && <span className="rspamd-allow">
                      <button className="mini secondary" disabled={!!loading} onClick={() => allowMailSender(sender)}><Check size={12}/> {t('Allow {sender}', { sender })}</button>
                      {senderDomain && <button className="mini secondary" disabled={!!loading} onClick={() => allowMailSender(senderDomain)}><Check size={12}/> {t('Allow everyone at {domain}', { domain: senderDomain })}</button>}
                    </span>}
              </span>
              <span className="rspamd-score"><strong>{item.score}</strong><small>/ {item.required}</small></span>
              <span className="rspamd-symbols">{item.symbols.slice(0, 10).map(symbol =>
                <code key={symbol.name} className={symbol.score > 0 ? 'pos' : symbol.score < 0 ? 'neg' : ''} title={String(symbol.score)}>{symbol.name}{symbol.score ? ` ${symbol.score > 0 ? '+' : ''}${symbol.score}` : ''}</code>)}</span>
            </div>;
          })}
        </div>}
        {pages > 1 && <div className="firewall-ip-pager">
          <button className="mini secondary" disabled={rspamdFilter.page <= 1} onClick={() => loadRspamdHistory(rspamdFilter.page - 1)}>{t('Previous')}</button>
          <span className="hint">{t('Page {page} of {pages}', { page: rspamdFilter.page, pages })}</span>
          <button className="mini secondary" disabled={rspamdFilter.page >= pages} onClick={() => loadRspamdHistory(rspamdFilter.page + 1)}>{t('Next')}</button>
        </div>}
        <p className="hint">{t('Rspamd keeps the last 2000 scans. A message sent by a signed-in mailbox is not scanned. A message stopped by a test pattern (GTUBE) is not kept.')}</p>
      </>}
      {rspamdView === 'log' && renderLogViewer(rspamdLog, rspamdLogQuery, setRspamdLogQuery, loadRspamdLog)}
      {rspamdView === 'allow' && (f ? <div className="create-inline mail-settings">
        <p className="hint">{t('One email address or domain per line. Mail from them is never blocked or sent to Junk: use it when the scan history shows a mistake.')}</p>
        <textarea className="mail-allow" rows={8} value={f.allow || ''} spellCheck={false} placeholder={'friend@example.com\nexample.org'}
          onChange={e => setMailSettingsForm(prev => ({ ...prev, allow: e.target.value }))} />
        <div className="actions"><button type="button" disabled={!!loading} onClick={saveMailSettings}><Save size={14}/> {t('Save allowlist')}</button></div>
      </div> : <p className="hint">{t('Loading…')}</p>)}
    </div>;
  }

  function renderMailServer() {
    const f = mailSettingsForm;
    const status = mailSettings?.status || {};
    const set = patch => setMailSettingsForm(prev => ({ ...prev, ...patch }));
    return <div className="mail-tab">
      {!f ? <p className="hint">{t('Loading…')}</p> : <div className="create-inline mail-settings">
        <div className="create-inline-head"><strong>{t('Mail server')}</strong></div>
        <p className="hint">{t('Server name: {host}. Messages waiting to be sent: {queue}.', { host: mailSettings?.hostname || '—', queue: mailSettings?.queue ?? '—' })}</p>
        <div className="dns-server">
          {[['exim', 'Exim'], ['dovecot', 'Dovecot'], ['rspamd', 'Rspamd'], ['webmail', 'Webmail']].map(([key, label]) =>
            <span key={key} className={`badge ${status[key] ? 'ok' : key === 'rspamd' && !f.spam_enabled ? '' : 'bad'}`}>{status[key] ? t('{name} is running', { name: label }) : t('{name} is not running', { name: label })}</span>)}
          <span className={`badge ${status.outbound_smtp ? 'ok' : 'warn'}`}>{status.outbound_smtp ? t('Can send to other mail servers') : t('Outgoing port 25 is blocked')}</span>
        </div>
        {!status.outbound_smtp && <p className="hint">{t('This server cannot reach other mail servers on port 25, so mail to outside addresses waits in the queue and comes back after a few days. Ask the provider to open it, or send through a relay (Relays tab).')}</p>}
        {f.spam_enabled && status.resolver === 'system' && <p className="hint">{t("This server's provider lets DNS out only to its own resolvers, so Rspamd uses them; Spamhaus and other DNS blocklists refuse such resolvers, so those checks are off. The other checks still run.")}</p>}
        <div className="mail-settings-grid">
          <label className="field"><span className="field-label">{t('Recipients per mailbox per hour')} <em>{t('0 = no limit')}</em></span><input type="number" min="0" value={f.auth_rate_per_hour ?? 300} onChange={e => set({ auth_rate_per_hour: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Messages per website account per hour')} <em>{t('0 = no limit')}</em></span><input type="number" min="0" value={f.local_rate_per_hour ?? 300} onChange={e => set({ local_rate_per_hour: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Largest message (MB)')}</span><input type="number" min="1" max="200" value={f.max_message_mb ?? 50} onChange={e => set({ max_message_mb: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('New mailbox size (MB)')}</span><input type="number" min="1" value={f.default_quota_mb ?? 1024} onChange={e => set({ default_quota_mb: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Spam score: move to Junk')}</span><input type="number" min="1" max="100" step="0.5" value={f.spam_header_score ?? 6} disabled={!f.spam_enabled} onChange={e => set({ spam_header_score: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Spam score: refuse')}</span><input type="number" min="1" max="100" step="0.5" value={f.spam_reject_score ?? 15} disabled={!f.spam_enabled} onChange={e => set({ spam_reject_score: e.target.value })} /></label>
        </div>
        <label className="check-line"><input type="checkbox" checked={!!f.spam_enabled} onChange={e => set({ spam_enabled: e.target.checked })} />
          {t('Spam filter (Rspamd) for mail from outside')}</label>
        <label className="check-line"><input type="checkbox" checked={!!f.greylisting} disabled={!f.spam_enabled} onChange={e => set({ greylisting: e.target.checked })} />
          {t('Greylisting: doubtful senders are asked to retry a few minutes later')}</label>
        <div className="actions"><button type="button" disabled={!!loading} onClick={saveMailSettings}><Save size={14}/> {t('Apply mail settings')}</button></div>
      </div>}
      <h3 className="mail-subhead">{t('Exim log')}</h3>
      {renderLogViewer(eximLog, eximLogQuery, setEximLogQuery, loadEximLog)}
    </div>;
  }

  function renderMailClientHelp() {
    const client = mailInfo?.client || {};
    return <section className="section">
      <div className="section-title">
        <div><h2>{t('Mail app settings')}</h2>
          <p className="hint">{t("For Outlook, Thunderbird, Apple Mail or a phone. The username is the full email address, the password the mailbox's own.")}</p></div>
      </div>
      <div className="sftp-connect-grid">
        {renderCopyBlock(t('Server (IMAP, POP3 and SMTP)'), client.host || '—')}
      </div>
      <ul className="mail-client-ports">
        <li><strong>IMAP</strong> {t('port {port}, SSL/TLS', { port: client.imap_port || 993 })}</li>
        <li><strong>POP3</strong> {t('port {port}, SSL/TLS', { port: client.pop3_port || 995 })}</li>
        <li><strong>SMTP</strong> {t('port {port}, SSL/TLS — or {submission} with STARTTLS', { port: client.smtp_port || 465, submission: client.submission_port || 587 })}</li>
      </ul>
    </section>;
  }

  function renderMailModals() {
    return <>
      {mailboxEdit && <div className="modal-overlay" onClick={() => setMailboxEdit(null)}>
        <div className="modal-card" onClick={e => e.stopPropagation()}>
          <div className="modal-header">
            <h3>{mailboxEdit.box.address}</h3>
            <button className="secondary-light" onClick={() => setMailboxEdit(null)} aria-label={t('Close')}><X size={16}/></button>
          </div>
          <div className="modal-body">
            <label className="field"><span className="field-label">{t('New password')} <small>{t('(leave empty to keep)')}</small></span>
              <div className="password-with-generate">
                <input value={mailboxEdit.password} autoComplete="new-password" spellCheck={false} onChange={e => setMailboxEdit(prev => ({ ...prev, password: e.target.value }))} data-lpignore="true" data-1p-ignore="true" />
                <button type="button" className="secondary icon-only" title={t('Generate random password')} aria-label={t('Generate random password')} onClick={() => setMailboxEdit(prev => ({ ...prev, password: mailPassword() }))}><Dices size={15}/></button>
                <button type="button" className="secondary icon-only" title={t('Copy')} aria-label={t('Copy')} onClick={() => copyText(mailboxEdit.password, t('Copied to clipboard.'))}><Copy size={15}/></button>
              </div>
            </label>
            <label className="field"><span className="field-label">{t('Size (MB)')}{isAdmin && <em> {t('0 = unlimited')}</em>}</span>
              <input type="number" min={isAdmin ? 0 : 1} value={mailboxEdit.quota_mb} onChange={e => setMailboxEdit(prev => ({ ...prev, quota_mb: e.target.value }))} />
            </label>
            <p className="hint">{t('A new password takes effect at once: mail apps using the old one must be updated.')}</p>
          </div>
          <div className="modal-actions">
            <button className="secondary-light" onClick={() => setMailboxEdit(null)}>{t('Cancel')}</button>
            <button disabled={!!loading || (mailboxEdit.password !== '' && (mailboxEdit.password.length < 8 || !/[A-Za-z]/.test(mailboxEdit.password) || !/\d/.test(mailboxEdit.password)))} onClick={saveMailboxEdit}><Save size={14}/> {t('Save')}</button>
          </div>
        </div>
      </div>}
      {forwarderEdit && <div className="modal-overlay" onClick={() => setForwarderEdit(null)}>
        <div className="modal-card" onClick={e => e.stopPropagation()}>
          <div className="modal-header">
            <h3>{forwarderEdit.item.address}</h3>
            <button className="secondary-light" onClick={() => setForwarderEdit(null)} aria-label={t('Close')}><X size={16}/></button>
          </div>
          <div className="modal-body">
            <label className="field"><span className="field-label">{t('Forward to')}</span>
              <textarea rows={3} value={forwarderEdit.destinations} spellCheck={false} onChange={e => setForwarderEdit(prev => ({ ...prev, destinations: e.target.value }))} />
            </label>
            <p className="hint">{t('One or more addresses, separated by commas.')}</p>
          </div>
          <div className="modal-actions">
            <button className="secondary-light" onClick={() => setForwarderEdit(null)}>{t('Cancel')}</button>
            <button disabled={!!loading || splitAddresses(forwarderEdit.destinations).length === 0} onClick={saveForwarderEdit}><Save size={14}/> {t('Save')}</button>
          </div>
        </div>
      </div>}
    </>;
  }

  function renderMail() {
    const info = mailInfo;
    if (!info) return <section className="section"><h2>{t('Email')}</h2><p className="hint">{t('Loading…')}</p></section>;
    if (mailDns) return <>{renderMailDns()}{renderMailModals()}</>;
    const domains = info.domains || [];
    const limit = info.mailbox_limit;
    const tabs = [
      ['mailboxes', 'Mailboxes', Inbox], ['forwarders', 'Forwarders', Forward], ['domains', 'Domains', Globe],
      // Server-wide: relays, the spam filter and the mail server itself.
      ...(isAdmin ? [['relay', 'Relays', Send], ['rspamd', 'Rspamd', ShieldCheck], ['server', 'Server', Server]] : []),
    ];
    const serverTabs = ['relay', 'rspamd', 'server'];
    const activeTab = domains.length || serverTabs.includes(mailTab) ? mailTab : 'domains';
    return <>
      <section className="section mail-page">
        <div className="section-title">
          <div><h2>{t('Email')}</h2>
            <p className="hint">{isAdmin
              ? t('Mailboxes, forwarders and DNS records of every mail domain on this server.')
              : limit ? t('{used} of {limit} mailboxes used.', { used: info.mailbox_count, limit }) : t('{n} mailboxes.', { n: info.mailbox_count })}</p></div>
          <div className="actions">
            <button type="button" className="secondary" onClick={() => window.open(info.webmail_url, '_blank', 'noopener,noreferrer')}><ExternalLink size={14}/> {t('Webmail')}</button>
            <button type="button" className="secondary" disabled={!!loading} onClick={refreshMail}><RefreshCw size={14}/> {t('Refresh')}</button>
          </div>
        </div>
        <div className="segmented-control backup-tabs" role="tablist" aria-label={t('Email sections')}>
          {tabs.map(([id, label, Icon]) => <button key={id} type="button" role="tab" aria-selected={activeTab === id}
            className={activeTab === id ? 'active' : ''} disabled={!domains.length && !['domains', ...serverTabs].includes(id)}
            onClick={() => { setMailTab(id); setMailPage(1); }}><Icon size={14}/>{t(label)}</button>)}
        </div>
        {activeTab === 'mailboxes' && renderMailboxes()}
        {activeTab === 'forwarders' && renderForwarders()}
        {activeTab === 'domains' && renderMailDomains()}
        {activeTab === 'relay' && renderMailRelays()}
        {activeTab === 'rspamd' && renderMailRspamd()}
        {activeTab === 'server' && renderMailServer()}
      </section>
      {domains.length > 0 && !serverTabs.includes(activeTab) && renderMailClientHelp()}
      {renderMailModals()}
    </>;
  }

  function renderDemoAccounts() {
    const candidates = demoSettings?.candidates || { admin: [], customer: [] };
    const setSlot = (slot, field, value) => setDemoDraft(prev => ({ ...prev, [slot]: { ...prev[slot], [field]: value } }));
    // BPanel offers two fixed places, an administrator and a customer; each is
    // left empty or given an account and the password the login page shows.
    const slots = [['admin', 'Administrator'], ['customer', 'Customer']];
    const tooShort = slots.some(([slot]) => demoDraft[slot].username && demoDraft[slot].password.length < 6);
    return <div className="addon-panel demo-settings">
      <div className="addon-panel-head"><strong>{t('Demo accounts')}</strong></div>
      <p className="hint">{t('Each demo account can open every page its role allows and change nothing. Use accounts made for the demo, on a server with sample data only.')}</p>
      {slots.map(([slot, label]) => <div className="demo-account-row" key={slot}>
        <select value={demoDraft[slot].username} disabled={!!loading} onChange={e => setSlot(slot, 'username', e.target.value)} aria-label={t(label)}>
          <option value="">{t('{role}: not offered', { role: t(label) })}</option>
          {/* Not yourself - the server refuses it - unless you are looking at it from the
              demo account itself, which must still show what is chosen. */}
          {(candidates[slot] || []).filter(name => name !== currentUser?.username || name === demoDraft[slot].username).map(name => <option key={name} value={name}>{name} ({t(label)})</option>)}
        </select>
        <input value={demoDraft[slot].password} disabled={!!loading || !demoDraft[slot].username} onChange={e => setSlot(slot, 'password', e.target.value)}
          placeholder={t('Public password (6+ characters)')} aria-label={t('Public password')} autoComplete="off" spellCheck={false} data-lpignore="true" data-1p-ignore="true"/>
        <button type="button" className="mini secondary-light icon-only" aria-label={t('Generate')} title={t('Generate')} disabled={!!loading || !demoDraft[slot].username}
          onClick={() => setSlot(slot, 'password', generateRandomPassword(16))}><Dices size={14}/></button>
      </div>)}
      <p className="hint">{t('The login page shows these accounts and their passwords to everyone, with a one-click sign-in.')}</p>
      <div className="actions">
        <button type="button" disabled={!!loading || tooShort} onClick={saveDemoAccounts}>
          <Save size={14}/> {t('Save demo accounts')}</button>
      </div>
    </div>;
  }

  function renderAddons() {
    if (!isAdmin) return <section className="section"><h2>{t('Addons')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const openMail = tab => { setMailTab(tab); navigateToPage('mail'); };
    return <section className="section">
      <div className="section-title">
        <div>
          <h2>{t('Addons')}</h2>
          <p className="hint">{t('Optional components this panel release can install for you. Each one ships with the panel, so a new addon arrives with a panel update.')}</p>
        </div>
        <button className="secondary-light" disabled={!!loading} onClick={loadAddons}><RefreshCw size={14}/> {t('Refresh')}</button>
      </div>

      {addons.loaded && addons.items.length === 0 && <p className="hint">{t('No addons in this release.')}</p>}

      <div className="addon-grid">
        {addons.items.map(addon => {
          const open = addonOpen === addon.slug;
          // BPanel installs and removes within the request and has no
          // start/stop, so an addon is installed or it is not.
          const stateBadge = addon.installed
            ? <span className="badge ok">{t('Installed')}</span>
            : <span className="badge">{t('Not installed')}</span>;
          const version = addon.installed ? (addon.installed_version || addon.version) : addon.version;
          const installedAt = addon.installed_at ? new Date(addon.installed_at) : null;
          return <div className="addon-card" key={addon.slug}>
            <div className="addon-card-head">
              <div className="addon-card-title">
                <PackageOpen size={16}/>
                <strong>{t(addon.name)}</strong>
                {version && <span className="hint addon-version">v{version}</span>}
              </div>
              {stateBadge}
            </div>
            <p className="addon-summary">{t(addon.summary)}</p>
            {addon.installed && addon.installed_version && addon.installed_version !== addon.version &&
              <p className="hint">{t('v{version} available', { version: addon.version })}</p>}
            {addon.installed && installedAt && <p className="hint">{t('Installed')} {Number.isNaN(installedAt.getTime()) ? addon.installed_at : installedAt.toLocaleString()}</p>}

            <div className="actions addon-actions">
              {!addon.installed && <button disabled={!!loading} onClick={() => setAddonInstalled(addon.slug, true)}>
                <Download size={14}/> {t('Install')}</button>}
              {/* What an addon installs and what to know first can be read
                  before installing it, not only in Manage afterwards. */}
              <button className="secondary-light" disabled={!!loading} onClick={() => setAddonOpen(open ? '' : addon.slug)}>
                {addon.installed ? <SettingsIcon size={14}/> : <FileText size={14}/>} {open ? t('Hide') : addon.installed ? t('Manage') : t('Details')}</button>
              {addon.installed && <button className="danger-light" disabled={!!loading}
                onClick={() => setAddonInstalled(addon.slug, false)}><Trash2 size={14}/> {t('Remove')}</button>}
            </div>

            {open && <div className="addon-detail">
              {addon.details?.length > 0 && <p className="addon-description">{addon.details.map(line => t(line)).join(' ')}</p>}
              {addon.notes?.length > 0 && <ul className="addon-notes">
                {addon.notes.map((note, idx) => <li key={idx}>{t(note)}</li>)}
              </ul>}
              {addon.slug === 'application' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Node.js apps, containers and Docker Compose')}</strong>
                  <button className="mini" onClick={() => navigateToPage('applications')}><Boxes size={13}/> {t('Open Applications')}</button></div>
              </div>}
              {addon.slug === 'fail2ban' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Status and banned addresses')}</strong>
                  <button className="mini" onClick={() => navigateToPage('firewall')}><Shield size={13}/> {t('Open Firewall')}</button></div>
              </div>}
              {addon.slug === 'mcp' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Tokens and client setup')}</strong>
                  <button className="mini" onClick={() => navigateToPage('mcp')}><Bot size={13}/> {t('Open AI assistants (MCP)')}</button></div>
                <p className="hint">{t('Endpoint:')} <code>{`${window.location.origin}/api/mcp`}</code></p>
              </div>}
              {addon.slug === 'demo' && addon.installed && renderDemoAccounts()}
              {addon.slug === 'mail' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Mailboxes, relays, the spam filter and server settings')}</strong></div>
                <div className="actions">
                  <button type="button" className="mini" onClick={() => openMail('mailboxes')}><Mail size={13}/> {t('Open Email')}</button>
                  <button type="button" className="mini secondary" onClick={() => openMail('relay')}><Send size={13}/> {t('Relays')}</button>
                  <button type="button" className="mini secondary" onClick={() => openMail('rspamd')}><ShieldCheck size={13}/> Rspamd</button>
                  <button type="button" className="mini secondary" onClick={() => openMail('server')}><Server size={13}/> {t('Server')}</button>
                </div>
              </div>}
              {addon.slug === 'dns' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Zones, records and nameservers')}</strong>
                  <button className="mini" onClick={() => navigateToPage('dns')}><Network size={13}/> {t('Open DNS Manager')}</button></div>
              </div>}
              {addon.slug === 'malware' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Scans, schedules and real-time protection')}</strong>
                  <button className="mini" onClick={() => navigateToPage('malware')}><Bug size={13}/> {t('Open Malware Scanner')}</button></div>
              </div>}
              {addon.slug === 'notifications' && addon.installed && <div className="addon-panel">
                <div className="addon-panel-head"><strong>{t('Channels, recipients and events')}</strong>
                  <button className="mini" onClick={() => navigateToPage('notifications')}><Bell size={13}/> {t('Open Notifications')}</button></div>
              </div>}
            </div>}
          </div>;
        })}
      </div>
    </section>;
  }

  function renderApplications() {
    const [portFrom, portTo] = siteApps.port_range || [21000, 21999];
    const atLimit = !isAdmin && siteApps.limit > 0 && siteApps.used >= siteApps.limit;
    const dockerReady = !!siteRuntimes.docker?.installed;
    const kindHint = (SITE_APP_KINDS.find(([value]) => value === siteAppDraft.kind) || [])[2];
    // Making one is occasional; the list is why the page is opened. With no
    // application yet the form is the only thing to do, so it starts open.
    const createOpen = !atLimit && (showCreateApp || siteApps.items.length === 0);
    const statusBadge = app => app.status === 'running'
      ? <span className="badge ok">{t('Running')}</span>
      : app.status === 'error' ? <span className="badge bad">{t('Failed')}</span> : <span className="badge">{t('Stopped')}</span>;
    const appDetail = app => [
      app.kind === 'node' ? `${app.start_kind} ${app.start_arg} · Node v${app.node_major || '22'}` : '',
      app.kind === 'docker' ? `${app.image} · ${t('port {port}', { port: app.container_port })} · ${app.cpu_limit} CPU` : '',
      app.kind === 'compose' && app.web_service ? `${t('Serves domain')}: ${app.web_service}` : '',
      app.websites?.length ? app.websites.join(', ') : '',
    ].filter(Boolean).join(' · ');
    const renderComposeReport = (plan, fixLabel) => plan && <div className={`compose-report ${plan.ok ? 'ok' : 'bad'}`}>
      {plan.ok
        ? <p><Check size={14}/> {t('{n} service(s) will run.', { n: plan.services.length })} <strong>{plan.web_service}</strong> {t('serves the domain.')}</p>
        : <p><AlertCircle size={14}/> {fixLabel}</p>}
      {plan.issues.length > 0 && <ul>
        {plan.issues.map((issue, index) => <li key={index}>
          {issue.service && <code>{issue.service}</code>} {issue.message}
        </li>)}
      </ul>}
      {plan.notes?.length > 0 && <ul className="compose-notes">
        {plan.notes.map((note, index) => <li key={index}>{note}</li>)}
      </ul>}
      {plan.ok && plan === composePlan && <ul className="compose-services">
        {plan.services.map(service => <li key={service.name}>
          <code>{service.name}</code> {service.image}
          {service.web ? ` · ${t('serves the domain')}` : ` · ${t('internal only')}`}
          {service.container_port ? ` · ${t('port {port}', { port: service.container_port })}` : ''}
        </li>)}
      </ul>}
    </div>;
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
          <div className="actions">
            <button className="secondary" disabled={!!loading} onClick={() => { loadSiteApps(); loadSiteRuntimes(); }}><RefreshCw size={14}/> {t('Refresh')}</button>
            {!createOpen && !atLimit && <button type="button" onClick={() => setShowCreateApp(true)}><Plus size={15}/> {t('New application')}</button>}
          </div>
        </div>
        <div className="site-runtime-strip">
          <span>{t('Docker:')} <strong>{dockerReady ? (siteRuntimes.docker.version || t('installed')) : t('not installed')}</strong></span>
          <span>{t('Node:')} <strong>{siteRuntimes.node_majors?.length ? siteRuntimes.node_majors.map(major => `v${major}`).join(', ') : t('system version only')}</strong></span>
          {isAdmin && !dockerReady && <button className="mini secondary" disabled={!!loading} onClick={installDockerEngine}><Download size={13}/> {t('Install Docker')}</button>}
          {isAdmin && <button className="mini secondary" disabled={!!loading} onClick={() => setNodeMajorDraft('22')}><Plus size={13}/> {t('Add Node version')}</button>}
        </div>
        {isAdmin && dockerReady && siteRuntimes.docker?.disk?.length > 0 && <div className="site-runtime-strip">
          <span>{t('Docker disk (whole server, not counted against customer quotas):')}</span>
          {siteRuntimes.docker.disk.map(row => <span key={row.type}>
            {row.type}: <strong>{row.size}</strong>{row.reclaimable && !row.reclaimable.startsWith('0B') ? <> · {t('{size} reclaimable', { size: row.reclaimable })}</> : null}
          </span>)}
          <button className="mini secondary" disabled={!!loading} onClick={pruneDocker}><Trash2 size={13}/> {t('Prune unused layers')}</button>
        </div>}
        {atLimit && <p className="hint">{t('This package allows {n} application(s). Delete one to install another.', { n: siteApps.limit })}</p>}

        {createOpen && <div className="create-inline">
          <div className="create-inline-head">
            <strong>{t('New application')}</strong>
            {siteApps.items.length > 0 && <button type="button" className="secondary icon-only mini" onClick={() => { setShowCreateApp(false); setComposePlan(null); }} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>}
          </div>
          <div className="site-app-form">
            <label className="field"><span className="field-label">{t('Name')}</span>
              <input value={siteAppDraft.name} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, name: e.target.value }))} />
            </label>
            <label className="field"><span className="field-label">{t('Runtime')}</span>
              <select value={siteAppDraft.kind} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, kind: e.target.value }))}>
                {SITE_APP_KINDS.map(([value, label]) => <option key={value} value={value} disabled={value === 'docker' && !dockerReady}>{t(label)}</option>)}
              </select>
            </label>
            <label className="field"><span className="field-label">{t('Port')}</span>
              <input type="number" value={siteAppDraft.port} min={portFrom} max={portTo} disabled={!!loading}
                placeholder={t('auto ({from}-{to})', { from: portFrom, to: portTo })}
                onChange={e => setSiteAppDraft(prev => ({ ...prev, port: e.target.value }))} />
            </label>
            <label className="field"><span className="field-label">{t('Memory (MB)')}</span>
              <input type="number" value={siteAppDraft.memory_limit_mb} min={64} max={siteApps.memory_ceiling_mb || 512} disabled={!!loading}
                placeholder={String(siteApps.memory_ceiling_mb || 512)}
                onChange={e => setSiteAppDraft(prev => ({ ...prev, memory_limit_mb: e.target.value }))} />
            </label>
            {siteAppDraft.kind === 'node' && <>
              <label className="field"><span className="field-label">{t('Start with')}</span>
                <select value={siteAppDraft.start_kind} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, start_kind: e.target.value }))}>
                  <option value="npm">npm run</option>
                  <option value="npx">npx</option>
                  <option value="yarn">yarn</option>
                  <option value="node">node</option>
                </select>
              </label>
              <label className="field"><span className="field-label">{siteAppDraft.start_kind === 'node' ? t('Entry file') : t('Script or package')}</span>
                <input value={siteAppDraft.start_arg} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, start_arg: e.target.value }))} placeholder={siteAppDraft.start_kind === 'node' ? 'server.js' : 'start'} />
              </label>
              <label className="field"><span className="field-label">{t('Node version')}</span>
                <select value={siteAppDraft.node_major} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, node_major: e.target.value }))}>
                  {(siteRuntimes.node_majors?.length ? siteRuntimes.node_majors : ['22']).map(major => <option key={major} value={major}>Node {major}</option>)}
                </select>
              </label>
            </>}
            {siteAppDraft.kind === 'compose' && <>
              <label className="field site-app-env"><span className="field-label">docker-compose.yml</span>
                <textarea
                  className="code-editor"
                  rows={12}
                  value={siteAppDraft.compose_source}
                  disabled={!!loading}
                  spellCheck={false}
                  onChange={e => { setSiteAppDraft(prev => ({ ...prev, compose_source: e.target.value })); setComposePlan(null); }}
                  placeholder={'services:\n  app:\n    image: myorg/app:1.0\n    ports: ["3000:3000"]\n  db:\n    image: postgres:16\n    volumes: ["pgdata:/var/lib/postgresql/data"]\nvolumes:\n  pgdata:'}
                />
              </label>
              {composePlan?.services?.length > 0 && <label className="field"><span className="field-label">{t('Service behind the domain')}</span>
                <select value={siteAppDraft.web_service} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, web_service: e.target.value }))}>
                  <option value="">{t('Choose for me')}</option>
                  {composePlan.services.map(service => <option key={service.name} value={service.name}>{service.name}{service.container_port ? ` · :${service.container_port}` : ''}</option>)}
                </select>
              </label>}
              {composeWebPorts(composePlan, siteAppDraft.web_service).length > 1 && <label className="field"><span className="field-label">{t('Port behind the domain')}</span>
                <select value={siteAppDraft.container_port} disabled={!!loading} onChange={e => { setSiteAppDraft(prev => ({ ...prev, container_port: e.target.value })); setComposePlan(null); }}>
                  {composeWebPorts(composePlan, siteAppDraft.web_service).map(port => <option key={port} value={port}>{port}</option>)}
                </select>
              </label>}
              <label className="field"><span className="field-label">{t('CPU per service')}</span>
                <input value={siteAppDraft.cpu_limit} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, cpu_limit: e.target.value }))} placeholder="1" />
              </label>
              <p className="compose-hint">{t('Where the file refers to')} <code>{'${VAR}'}</code>, set the value in the <strong>.env</strong> box below,
                exactly as an <code>.env</code> file beside <code>docker-compose.yml</code> would. For a public address
                (an OAuth callback, a webhook) use <code>{'${BPANEL_URL}'}</code> / <code>{'${BPANEL_DOMAIN}'}</code>:
                the app only ever sees its internal port, and the panel fills in the domain of the website pointing at it.</p>
            </>}
            {siteAppDraft.kind === 'docker' && <>
              <label className="field"><span className="field-label">{t('Image')}</span>
                <input value={siteAppDraft.image} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, image: e.target.value }))} placeholder="n8nio/n8n:latest" />
              </label>
              <label className="field"><span className="field-label">{t('Port in container')}</span>
                <input type="number" value={siteAppDraft.container_port} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, container_port: e.target.value }))} placeholder="3000" />
              </label>
              <label className="field"><span className="field-label">CPU</span>
                <input value={siteAppDraft.cpu_limit} disabled={!!loading} onChange={e => setSiteAppDraft(prev => ({ ...prev, cpu_limit: e.target.value }))} placeholder="1" />
              </label>
            </>}
            <label className="field site-app-env"><span className="field-label">{siteAppDraft.kind === 'compose' ? t('.env (KEY=value, one per line)') : t('Environment (KEY=value, one per line)')}</span>
              <textarea
                className="code-editor"
                rows={4}
                value={siteAppDraft.env}
                disabled={!!loading}
                spellCheck={false}
                onChange={e => setSiteAppDraft(prev => ({ ...prev, env: e.target.value }))}
                placeholder={'N8N_ENCRYPTION_KEY=...\nGENERIC_TIMEZONE=Asia/Ho_Chi_Minh'}
              />
            </label>
            <div className="site-app-form-actions">
              {siteAppDraft.kind === 'compose' && <button className="secondary" disabled={!!loading || !siteAppDraft.compose_source.trim()} onClick={checkComposeFile}><Check size={14}/> {t('Check file')}</button>}
              <button className="secondary" disabled={!!loading} onClick={suggestSiteAppPort}>{t('Pick free port')}</button>
              <button disabled={!!loading || !siteAppDraft.name.trim()} onClick={createSiteApp}><Plus size={14}/> {t('Install application')}</button>
            </div>
            {renderComposeReport(composePlan, t('{n} thing(s) to fix before importing:', { n: composePlan?.issues?.length || 0 }))}
          </div>
          {kindHint && <p className="hint">{t(kindHint)} {t('Containers publish on 127.0.0.1 only, run as your own user with no capabilities, and are capped at the memory shown.')} {t('Images come from {list}.', { list: (siteRuntimes.allowed_registries || []).join(', ') || t('the allowed registries') })}</p>}
        </div>}

        {siteApps.items.length === 0 && !createOpen && <EmptyState icon={Server} message={t('No applications yet.')} action={atLimit ? undefined : { label: t('New application'), icon: Plus, onClick: () => setShowCreateApp(true) }} />}
        {siteApps.items.length > 0 && <div className="table">
          {siteApps.items.map(app => <div className="row site-app-row" key={app.id}>
            <div className="user-main">
              <strong>{app.name}</strong>
              <small><code>127.0.0.1:{app.port}</code> · {app.directory}</small>
              {appDetail(app) && <small>{appDetail(app)}</small>}
            </div>
            <span className="badge">{SITE_APP_KIND_LABELS[app.kind] || app.kind}</span>
            {statusBadge(app)}
            <div className="row-actions">
              <button className="mini secondary-light" disabled={!!loading} onClick={() => openAppFileManager(app)}><FolderOpen size={13}/> {t('Files')}</button>
              <button className="mini" disabled={!!loading} onClick={() => deploySiteApp(app)}><Play size={13}/> {t('Deploy')}</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => controlSiteApp(app, 'restart')}><RotateCcw size={13}/> {t('Restart')}</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => controlSiteApp(app, 'stop')}><Square size={13}/> {t('Stop')}</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => openSiteAppLog(app)}><FileText size={13}/> {t('Log')}</button>
              <button className="mini secondary-light" disabled={!!loading} onClick={() => openSiteAppEdit(app)}><Pencil size={13}/> {t('Edit')}</button>
              <button className="mini danger" disabled={!!loading} onClick={() => deleteSiteApp(app)} aria-label={t('Delete {name}', { name: app.name })} title={t('Delete')}><Trash2 size={13}/></button>
            </div>
            {app.last_error && <p className="site-app-error">{app.last_error}</p>}
            {siteAppEdit?.id === app.id && <div className="user-edit-panel">
              <div className="user-edit-heading">
                <div><strong>{t('Edit')} {app.name}</strong><small>{t('Unit')}: {app.unit}</small></div>
                <button className="user-edit-close secondary-light" onClick={() => { setSiteAppEdit(null); setSiteAppEditPlan(null); }} aria-label={t('Close')} title={t('Close')}><X size={16}/></button>
              </div>
              <div className="user-edit-grid">
                <label><span>{t('Port')}</span>
                  <input type="number" value={siteAppEdit.port} min={portFrom} max={portTo} disabled={!!loading}
                    onChange={e => setSiteAppEdit(prev => ({ ...prev, port: e.target.value }))} />
                </label>
                <label><span>{t('Memory (MB)')}</span>
                  <input type="number" value={siteAppEdit.memory_limit_mb} min={64} max={isAdmin ? 16384 : (siteApps.memory_ceiling_mb || 512)} disabled={!!loading}
                    onChange={e => setSiteAppEdit(prev => ({ ...prev, memory_limit_mb: e.target.value }))} />
                </label>
                {app.kind === 'docker' && <label><span>CPU</span>
                  <input value={siteAppEdit.cpu_limit} disabled={!!loading} onChange={e => setSiteAppEdit(prev => ({ ...prev, cpu_limit: e.target.value }))} />
                </label>}
                {app.kind === 'compose' && siteAppEditPlan?.services?.length > 0 && <label><span>{t('Service behind the domain')}</span>
                  <select value={siteAppEdit.web_service} disabled={!!loading} onChange={e => setSiteAppEdit(prev => ({ ...prev, web_service: e.target.value }))}>
                    <option value="">{t('Choose for me')}</option>
                    {siteAppEditPlan.services.map(service => <option key={service.name} value={service.name}>{service.name}{service.container_port ? ` · :${service.container_port}` : ''}</option>)}
                  </select>
                </label>}
                {app.kind === 'compose' && composeWebPorts(siteAppEditPlan, siteAppEdit.web_service).length > 1 && <label><span>{t('Port behind the domain')}</span>
                  <select value={siteAppEdit.container_port} disabled={!!loading} onChange={e => { setSiteAppEdit(prev => ({ ...prev, container_port: e.target.value })); setSiteAppEditPlan(null); }}>
                    {composeWebPorts(siteAppEditPlan, siteAppEdit.web_service).map(port => <option key={port} value={port}>{port}</option>)}
                  </select>
                </label>}
              </div>
              {app.kind === 'compose' && <>
                <label className="field"><span className="field-label">docker-compose.yml</span>
                  <textarea
                    className="code-editor"
                    rows={14}
                    value={siteAppEdit.compose_source}
                    disabled={!!loading}
                    spellCheck={false}
                    onChange={e => { setSiteAppEdit(prev => ({ ...prev, compose_source: e.target.value })); setSiteAppEditPlan(null); }}
                  />
                </label>
                <p className="compose-hint">{t('The panel reads this file and generates the one it actually runs.')} <code>{'${VAR}'}</code> comes
                  from the .env box; for a public address use <code>{'${BPANEL_URL}'}</code> / <code>{'${BPANEL_DOMAIN}'}</code>
                  {app.websites?.length > 0 ? ` (currently ${app.websites[0]})` : ' (point a website at this app first)'}.</p>
              </>}
              <label className="field"><span className="field-label">{app.kind === 'compose' ? t('.env (KEY=value, one per line)') : t('Environment (KEY=value, one per line)')}</span>
                <textarea
                  className="code-editor"
                  rows={app.kind === 'compose' ? 6 : 8}
                  value={siteAppEdit.env}
                  disabled={!!loading}
                  spellCheck={false}
                  onChange={e => { setSiteAppEdit(prev => ({ ...prev, env: e.target.value })); if (app.kind === 'compose') setSiteAppEditPlan(null); }}
                />
              </label>
              {renderComposeReport(siteAppEditPlan, t('{n} thing(s) to fix:', { n: siteAppEditPlan?.issues?.length || 0 }))}
              <div className="user-edit-actions">
                {app.kind === 'compose' && <button className="secondary" disabled={!!loading || !siteAppEdit.compose_source.trim()} onClick={checkSiteAppEdit}><Check size={14}/> {t('Check file')}</button>}
                <button className="secondary-light" onClick={() => { setSiteAppEdit(null); setSiteAppEditPlan(null); }}>{t('Cancel')}</button>
                <button disabled={!!loading} onClick={() => saveSiteAppEdit(app)}><Save size={14}/> {t('Save')}</button>
              </div>
            </div>}
          </div>)}
        </div>}
      </section>

      {siteAppLog && <section className="section log-viewer">
        <div className="section-title">
          <div className="nginx-config-title"><h2>{t('Log')} - {siteAppLog.name}</h2></div>
          <button className="secondary-light" onClick={() => setSiteAppLog(null)}><X size={14}/> {t('Close')}</button>
        </div>
        <pre className="log-output">{siteAppLog.log}</pre>
      </section>}

      {nodeMajorDraft !== null && <div className="modal-overlay" onClick={() => setNodeMajorDraft(null)}>
        <div className="modal-card" onClick={e => e.stopPropagation()}>
          <div className="modal-header">
            <h3>{t('Add Node version')}</h3>
            <button className="secondary-light" onClick={() => setNodeMajorDraft(null)} aria-label={t('Close')}><X size={16}/></button>
          </div>
          <div className="modal-body">
            <label className="field"><span className="field-label">{t('Node major version')}</span>
              <input value={nodeMajorDraft} inputMode="numeric" placeholder="22" onChange={e => setNodeMajorDraft(e.target.value.replace(/[^0-9]/g, ''))} />
            </label>
            {siteRuntimes.node_majors?.length > 0 && <p className="hint">{t('Installed:')} {siteRuntimes.node_majors.map(major => `v${major}`).join(', ')}</p>}
          </div>
          <div className="modal-actions">
            <button className="secondary-light" onClick={() => setNodeMajorDraft(null)}>{t('Cancel')}</button>
            <button disabled={!!loading || !nodeMajorDraft.trim()} onClick={() => { const major = nodeMajorDraft.trim(); setNodeMajorDraft(null); installNodeMajor(major); }}><Download size={14}/> {t('Install')}</button>
          </div>
        </div>
      </div>}
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
          <h2>{fullConfig ? t('Full Nginx config') : t('Website settings')} - {nginxCustomEditing.domain}</h2>
          <p className="hint">{fullConfig
            ? t('This is read-only. BPanel manages the main vhost template.')
            : t('Managed settings rewrite the main vhost safely. Custom Nginx is still stored as a separate include.')}</p>
        </div>
        <div className="actions">
          {!fullConfig && isAdmin && <button className="secondary-light" disabled={!!loading} onClick={viewFullNginxConfig}><FileText size={14}/> {t('View all')}</button>}
          {fullConfig && <button className="secondary-light" disabled={!!loading} onClick={() => setNginxCustomEditing(prev => ({ ...prev, mode: 'custom', content: prev?.customContent ?? prev?.content ?? '' }))}><SettingsIcon size={14}/> {t('Settings')}</button>}
          <button className="secondary-light" onClick={() => setNginxCustomEditing(null)}><X size={14}/> {t('Close')}</button>
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
          {NGINX_REWRITE_MODES.map(mode => <option key={mode.value} value={mode.value}>{t(mode.label)}</option>)}
        </select></label>
        <div className="website-settings-actions">
          <button disabled={!!loading} onClick={saveWebsiteSettings}><Save size={14}/> {t('Save settings')}</button>
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
              <Globe size={12}/>{alias.domain}<span>{alias.mode === 'redirect' ? t('Redirect') : t('Alias')}</span>
              <button type="button" disabled={!!loading} title={t('Remove {domain}', { domain: alias.domain })} aria-label={t('Remove {domain}', { domain: alias.domain })} onClick={() => deleteWebsiteAlias(settingsSite, alias)}><X size={12}/></button>
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
          <button className="secondary-light" disabled={!!loading || !(aliasDrafts[nginxCustomEditing.id] || '').trim()} onClick={() => addWebsiteAlias(settingsSite)}><Plus size={14}/> {t('Add domain')}</button>
        </div>
      </div>}
      {/* BPanel's own: extra Nginx directives, kept as a separate include. */}
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
        {!fullConfig && <button disabled={!!loading} onClick={saveNginxCustom}><Save size={14}/> {t('Save and reload Nginx')}</button>}
        {!fullConfig && <button className="secondary-light" disabled={!!loading} onClick={resetNginxDefault}><RotateCcw size={14}/> {t('Reset custom')}</button>}
        <button className="secondary-light" disabled={!!loading} onClick={() => setNginxCustomEditing(null)}>{fullConfig ? t('Close') : t('Cancel')}</button>
      </div>
    </section>;
  }


  function renderWebsiteTerminal() {
    if (!terminalViewer) return null;
    return <section className="section nginx-modal terminal-modal">
      <div className="section-title">
        <h2>{t('Terminal -')} {terminalViewer.domain}</h2>
        <button className="secondary-light" onClick={() => setTerminalViewer(null)}><X size={14}/> {t('Close')}</button>
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
          <h2>{t('Webserver logs -')} {logViewer.domain}</h2>
          <p className="hint">{logViewer.path || `/var/log/nginx/${logViewer.domain}.${logViewer.kind}.log`}</p>
        </div>
        <button className="secondary-light" onClick={() => setLogViewer(null)}><X size={14}/> {t('Close')}</button>
      </div>
      <div className="log-toolbar">
        <div className="segmented-control">
          <button className={logViewer.kind === 'access' ? 'active' : ''} disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, 'access', logViewer.lines, logViewer.domain)}>{t('Access')}</button>
          <button className={logViewer.kind === 'error' ? 'active' : ''} disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, 'error', logViewer.lines, logViewer.domain)}>{t('Errors (PHP + server)')}</button>
        </div>
        <select value={logViewer.lines} onChange={e => loadWebsiteLog(logViewer.id, logViewer.kind, Number(e.target.value), logViewer.domain)} disabled={!!loading}>
          <option value={100}>{t('100 lines')}</option>
          <option value={200}>{t('200 lines')}</option>
          <option value={500}>{t('500 lines')}</option>
          <option value={1000}>{t('1000 lines')}</option>
          <option value={2000}>{t('2000 lines')}</option>
        </select>
        <button className="secondary" disabled={!!loading} onClick={() => loadWebsiteLog(logViewer.id, logViewer.kind, logViewer.lines, logViewer.domain)}><RefreshCw size={14}/> {t('Refresh')}</button>
      </div>
      <pre className="log-output">{logViewer.exists
        ? (logViewer.content || t('Log is empty.'))
        : (logViewer.kind === 'error' ? t('No errors logged yet.') : t('Log file has not been created yet.'))}</pre>
    </section>;
  }

  function renderWebsites() {
    const wpFieldsEnabled = siteType === 'wordpress' && installWordPress;
    // Filtered here, as OPanel's list is: the page already holds every site.
    // The path and the Linux user still match, as BPanel's search always did.
    const wsQuery = websiteSearch.trim().toLowerCase();
    const filteredWebsites = wsQuery
      ? websites.filter(s => (s.domain || '').toLowerCase().includes(wsQuery)
          || (s.aliases || []).some(a => (a.domain || '').toLowerCase().includes(wsQuery))
          || (s.root_path || '').toLowerCase().includes(wsQuery)
          || (s.linux_user || '').toLowerCase().includes(wsQuery))
      : websites;
    const createOpen = createFormOpen || websites.length === 0;
    const openCreate = () => {
      setCreateFormOpen(true);
      setTimeout(() => { const el = document.getElementById('create-website-domain'); el?.scrollIntoView({ behavior: 'smooth', block: 'center' }); el?.focus(); }, 0);
    };
    const sslAfterCreate = createSslMode !== 'none';
    // What secures a site, in OPanel's words: a wildcard, a certificate
    // borrowed from another site, or its own.
    const sslBadge = site => !site.ssl_enabled ? t('No SSL')
      : site.ssl_mode === 'cloudflare' ? t('Wildcard')
        : site.ssl_mode === 'shared' ? t('Shared cert') : t('SSL OK');
    const wpPanel = wordpressInstaller;
    return <>
      {createOpen && <section className="section create-panel">
        <div className="section-title">
          <h2>{t('Create website')}</h2>
          {websites.length > 0 && <button type="button" className="secondary icon-only mini" onClick={() => setCreateFormOpen(false)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>}
        </div>
        <div className="form-row create-site-row">
          <input id="create-website-domain" value={domain} onChange={e => setDomain(e.target.value)} placeholder="domain.com" />
          {isReseller && users.length > 0 && <select value={siteOwnerId} onChange={e => setSiteOwnerId(e.target.value)} aria-label={t('Owner')} title={t('Owner')}>
            <option value="">{t('For yourself')}</option>
            {users.filter(u => u.id !== currentUser?.id).map(u => <option key={u.id} value={u.id}>{t('For {name}', { name: u.username })}</option>)}
          </select>}
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
          <button disabled={!!loading || !domain} onClick={createWordPress}><Plus size={15}/> {t('Create')}</button>
        </div>
        {siteType === 'application' && siteApps.items.length === 0 && <p className="hint">{t('No applications installed yet. Install one on the')}<button type="button" className="link-button" onClick={() => navigateToPage('applications')}>{t('Applications')}</button> page first.
        </p>}
        {siteType === 'wordpress' && <label className="check-line">
          <input type="checkbox" checked={installWordPress} onChange={e => setInstallWordPress(e.target.checked)} />
          {t('Install WordPress (creates database, downloads WP, configures vhost)')}
        </label>}
        <label className="check-line">
          <input type="checkbox" checked={sslAfterCreate} onChange={e => setCreateSslMode(e.target.checked ? 'letsencrypt' : 'none')} />
          {t('Set up SSL after creating')}
        </label>
        {sslAfterCreate && <div className="create-ssl-box">
          <div className="segmented ssl-mode-tabs">
            <button className={createSslMode === 'letsencrypt' ? 'active' : ''} onClick={() => setCreateSslMode('letsencrypt')}><Lock size={13}/> Let's Encrypt</button>
            <button className={createSslMode === 'wildcard' ? 'active' : ''} onClick={() => setCreateSslMode('wildcard')}><Globe size={13}/> {t('Wildcard (Cloudflare)')}</button>
            <button className={createSslMode === 'shared' ? 'active' : ''} onClick={() => setCreateSslMode('shared')}><RefreshCw size={13}/> {t('Use existing')}</button>
            <button className={createSslMode === 'manual' ? 'active' : ''} onClick={() => setCreateSslMode('manual')}><KeyRound size={13}/> {t('Manual')}</button>
          </div>
          {createSslMode === 'letsencrypt' && <p className="hint">{t("certbot HTTP-01 — the domain must point to this server's IP first.")}</p>}
          {createSslMode === 'wildcard' && <div className="create-ssl-fields">
            <input type="password" autoComplete="off" placeholder={t('Cloudflare API Token')} value={createSslToken} onChange={e => setCreateSslToken(e.target.value)} />
            <p className="hint">{t('A scoped')} <strong>{t('API Token')}</strong> {t('(My Profile → API Tokens → Create Token),')} <strong>{t('not')}</strong> {t('the Global API Key. Permission')} <code>Zone → DNS → Edit</code> {t('for the zone(s) you issue certs for. Stored encrypted for renewal. Issues one cert for the zone and *.zone — no DNS record or port 80 needed. Leave the token blank to reuse one already saved for the zone.')}</p>
          </div>}
          {createSslMode === 'shared' && <p className="hint">{t('After the site is created the panel points it at an existing certificate that covers this domain (a wildcard first). If none does, the site is created without SSL.')}</p>}
          {createSslMode === 'manual' && <div className="create-ssl-fields">
            <textarea rows={4} placeholder="-----BEGIN CERTIFICATE-----" value={createSslManual.certificate} onChange={e => setCreateSslManual(p => ({ ...p, certificate: e.target.value }))} />
            <textarea rows={4} placeholder="-----BEGIN PRIVATE KEY-----" value={createSslManual.private_key} onChange={e => setCreateSslManual(p => ({ ...p, private_key: e.target.value }))} />
            <textarea rows={3} placeholder={t('CA bundle (optional)')} value={createSslManual.ca_bundle} onChange={e => setCreateSslManual(p => ({ ...p, ca_bundle: e.target.value }))} />
            <p className="hint">{t('Left empty, the SSL page opens after the site is created so you can paste them there.')}</p>
          </div>}
        </div>}
        <p className="hint">{t(wpFieldsEnabled
          ? 'WordPress will be installed and the panel will show the URL, admin account, and password after creation.'
          : siteType === 'application'
            ? 'Nginx will forward this domain to the selected application on 127.0.0.1, including WebSocket upgrades.'
            : 'A virtual host will be created with public_html/ folder. Upload your PHP, HTML, or static files via File Manager.')}</p>
      </section>}
      <section className="section">
        <div className="section-title">
          <h2>{t('Website list')}</h2>
          <div className="actions">
            <button className="secondary" disabled={!!loading} onClick={() => loadWebsiteList('', true)}><RefreshCw size={15}/> {t('Refresh')}</button>
            {!createOpen && <button type="button" onClick={openCreate}><Plus size={15}/> {t('New website')}</button>}
          </div>
        </div>
        {websites.length > 0 && <div className="website-search">
          <Search size={15}/>
          <NoAutofillInput name="website-search" value={websiteSearch} onChange={e => setWebsiteSearch(e.target.value)} placeholder={t('Filter domains…')} />
          {websiteSearch && <button className="mini secondary-light" aria-label={t('Clear search')} onClick={() => setWebsiteSearch('')}><X size={13}/></button>}
          <span className="hint">{wsQuery
            ? t('{shown} of {total}', { shown: filteredWebsites.length, total: websites.length })
            : (websites.length === 1 ? t('{n} website', { n: websites.length }) : t('{n} websites', { n: websites.length }))}</span>
        </div>}
        {websites.length === 0 && <EmptyState icon={Globe} message="No websites yet." action={{ label: t('New website'), icon: Plus, onClick: openCreate }} />}
        {websites.length > 0 && filteredWebsites.length === 0 && <EmptyState icon={Globe} message={t('No domain matches “{query}”.', { query: websiteSearch })} />}
        <div className="site-grid">
          {filteredWebsites.map(site => <div className="site-stack" key={site.id}>
          <article className="site-card">
            <div className="site-head">
              <div>
                <a className="site-link" href={websiteUrl(site)} target="_blank" rel="noopener noreferrer">{site.domain}</a>
                <small>{site.root_path}</small>
              </div>
            </div>
            <div className="site-meta">
              <span className={`badge site-ssl-badge ${site.ssl_enabled ? 'ok' : ''}`}>{sslBadge(site)}</span>
              <span>{t(APP_TYPE_LABELS[site.app_type || 'wordpress'] || site.app_type)}</span>
              {site.app_type !== 'static' && <span>PHP <strong>{site.php_version}</strong></span>}
              {site.app_type === 'php' && site.nginx_rewrite_mode && site.nginx_rewrite_mode !== 'none' && <span>{t('Rewrite')} <strong>{site.nginx_rewrite_mode}</strong></span>}
              {site.nginx_custom && <span className="badge ok">{t('Custom Nginx')}</span>}
              {site.waf_enabled && <span className="badge ok">WAF</span>}
              {site.http_flood_enabled && <span className="badge ok">{t('HTTP Flood')}</span>}
              {(site.aliases || []).length > 0 && <span>{t('Domains')} <strong>{(site.aliases || []).length + 1}</strong></span>}
            </div>
            <div className="site-actions" aria-label={t('Website actions for {domain}', { domain: site.domain })}>
              <div className="site-feature-actions">
                <button className="site-icon-button secondary-light" data-tooltip="Files" title={t('Files')} aria-label={t('Open file manager for {domain}', { domain: site.domain })} disabled={!!loading} onClick={() => openWebsiteFileManager(site)}><FolderOpen size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Logs" title={t('Logs')} aria-label={t('View logs for {domain}', { domain: site.domain })} disabled={!!loading} onClick={() => openWebsiteLogs(site)}><FileText size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Terminal" title={t('Terminal')} aria-label={t('Open terminal for {domain}', { domain: site.domain })} disabled={!!loading} onClick={() => openWebsiteTerminal(site)}><TerminalIcon size={15}/></button>
                <button className="site-icon-button secondary-light" data-tooltip="Settings" title={t('Settings')} aria-label={t('Edit settings for {domain}', { domain: site.domain })} disabled={!!loading} onClick={() => openNginxCustom(site)}><SettingsIcon size={15}/></button>
                {!site.wordpress_installed && <button className="site-icon-button secondary-light" data-tooltip={t('Install WP')} title={t('Install WordPress')} aria-label={t('Install WordPress on {domain}', { domain: site.domain })} disabled={!!loading} onClick={() => openWordPressInstaller(site)}><Download size={15}/></button>}
                {site.wordpress_installed && <button className="site-icon-button secondary-light" data-tooltip={t('Update WP')} title={t('Update WordPress')} aria-label={t('Update WordPress on {domain}', { domain: site.domain })} disabled={!!loading} onClick={() => openWordPressUpdate(site)}><RefreshCw size={15}/></button>}
                <button className="site-icon-button danger" data-tooltip="Delete" title={t('Delete')} aria-label={t('Delete {name}', { name: site.domain })} disabled={!!loading} onClick={() => deleteWebsite(site.id)}><Trash2 size={15}/></button>
              </div>
            </div>
          </article>
          {nginxCustomEditing?.id === site.id && renderNginxEditor()}
          {logViewer?.id === site.id && renderWebsiteLogViewer()}
          {terminalViewer?.id === site.id && renderWebsiteTerminal()}
          {wpPanel && String(wpPanel.website_id) === String(site.id) && <div className="wp-manager-panel">
            <div className="user-edit-heading">
              <strong>{wpPanel.mode === 'update' ? t('Update WordPress on {domain}', { domain: site.domain }) : t('Install WordPress on {domain}', { domain: site.domain })}</strong>
              <button className="user-edit-close secondary-light" aria-label={t('Close')} onClick={() => setWordpressInstaller(null)}><X size={16}/></button>
            </div>
            {wpPanel.mode !== 'update' ? <div className="user-edit-grid">
              <p className="hint">{t('Creates a database, downloads WordPress, configures vhost.')}</p>
              <label><span>{t('Site title')}</span><input value={wpPanel.title} onChange={e => setWordpressInstaller(prev => ({ ...prev, title: e.target.value }))} /></label>
              <label><span>{t('Admin username')}</span><input value={wpPanel.admin_user} onChange={e => setWordpressInstaller(prev => ({ ...prev, admin_user: e.target.value }))} /></label>
              <label><span>{t('Admin email')}</span><input type="email" value={wpPanel.admin_email} onChange={e => setWordpressInstaller(prev => ({ ...prev, admin_email: e.target.value }))} /></label>
              <label><span>{t('Admin password')}</span><input type="password" autoComplete="new-password" value={wpPanel.admin_password} onChange={e => setWordpressInstaller(prev => ({ ...prev, admin_password: e.target.value }))} placeholder={t('Min 10 characters')} /></label>
              <div className="user-edit-actions">
                <button className="secondary-light" onClick={() => setWordpressInstaller(null)}>{t('Cancel')}</button>
                <button disabled={!!loading || !wpPanel.admin_user || !wpPanel.admin_email || String(wpPanel.admin_password || '').length < 10} onClick={installWordPressOnSite}><Download size={14}/> {t('Install WordPress')}</button>
              </div>
            </div> : <div>
              <p className="hint">{t('Updates WordPress core, all plugins, and all themes to the latest version.')}</p>
              <div className="user-edit-actions">
                <button className="secondary-light" onClick={() => setWordpressInstaller(null)}>{t('Cancel')}</button>
                <button disabled={!!loading} onClick={() => updateWordPressAll(site)}><RefreshCw size={14}/> {t('Update All')}</button>
              </div>
            </div>}
          </div>}
          </div>)}
        </div>
      </section>
    </>;
  }

  function renderSsl() {
    // Named as OPanel names them. BPanel's modes: a Cloudflare wildcard, a
    // certificate borrowed from another site ("shared"), one uploaded by hand,
    // or Let's Encrypt.
    const sslLabel = !currentSite?.ssl_enabled ? t('SSL Disabled')
      : currentSite.ssl_mode === 'manual' ? t('Manual SSL')
        : currentSite.ssl_mode === 'shared' ? t('Existing certificate')
          : currentSite.ssl_mode === 'cloudflare' ? t('Wildcard SSL')
            : t('SSL Enabled');
    const locale = language === 'vi' ? 'vi-VN' : 'en-GB';
    const sslUpdated = currentSite?.ssl_updated_at ? new Date(currentSite.ssl_updated_at).toLocaleString(locale) : '';
    const wildcardActive = currentSite?.ssl_enabled && currentSite?.ssl_mode === 'cloudflare';
    const wildcardZone = cfZone.zone || currentSite?.domain;
    // Every site on one list, as OPanel has it: the unsecured first, then the
    // rest by name, each a click from the form above.
    const sslSites = [...websites].sort((a, b) => (a.ssl_enabled === b.ssl_enabled
      ? String(a.domain).localeCompare(String(b.domain)) : a.ssl_enabled ? 1 : -1));
    const securedCount = websites.filter(site => site.ssl_enabled).length;
    const siteSslLabel = site => !site.ssl_enabled ? t('No SSL')
      : site.ssl_mode === 'manual' ? t('Manual SSL')
        : site.ssl_mode === 'shared' ? t('Shared cert')
          : site.ssl_mode === 'cloudflare' ? t('Wildcard') : t('SSL OK');
    return <>
    <section className="section" id="ssl-manage">
      <h2>{t('SSL Certificate')}</h2>
      <WebsiteSelect />
      {currentSite && <div className="info-box" style={{marginTop:8}}>
        <strong>{currentSite.domain}</strong>
        <span className={currentSite.ssl_enabled ? 'badge ok' : 'badge'} style={{justifySelf:'start'}}>{sslLabel}</span>
        {wildcardActive && currentSite.ssl_source_domain && <span className="badge ok" style={{justifySelf:'start'}}>*.{currentSite.ssl_source_domain}</span>}
        {currentSite.ssl_enabled && currentSite.ssl_mode === 'shared' && currentSite.ssl_source_domain && <span className="hint">{currentSite.ssl_source_domain}</span>}
        {sslUpdated && <span className="hint">{t('Updated')} {sslUpdated}</span>}
        {currentSite.ssl_mode === 'manual' && currentSite.ssl_has_ca && <span className="badge ok" style={{justifySelf:'start'}}>{t('CA Bundle')}</span>}
      </div>}
      <div className="segmented ssl-mode-tabs">
        <button className={sslMode === 'letsencrypt' ? 'active' : ''} onClick={() => setSslMode('letsencrypt')}><Lock size={14}/> Let's Encrypt</button>
        <button className={sslMode === 'wildcard' ? 'active' : ''} onClick={() => setSslMode('wildcard')}><Globe size={14}/> {t('Wildcard (Cloudflare)')}</button>
        <button className={sslMode === 'shared' ? 'active' : ''} onClick={() => { setSslMode('shared'); if (selectedWebsiteId) loadSslSources(selectedWebsiteId); }}><RefreshCw size={14}/> {t('Use existing')}</button>
        <button className={sslMode === 'manual' ? 'active' : ''} onClick={() => setSslMode('manual')}><KeyRound size={14}/> {t('Manual SSL')}</button>
      </div>
      {sslMode === 'letsencrypt' ? <>
        <button className="manual-ssl-submit" disabled={!selectedWebsiteId || !!loading} onClick={() => enableSsl(selectedWebsiteId)}><Lock size={15}/> {t('Install / Renew SSL')}</button>
        <p className="hint">{t("certbot HTTP-01 — the domain must point to this server's IP before issuing.")}</p>
      </> : sslMode === 'wildcard' ? <div className="manual-ssl-grid">
        <label style={{gridColumn:'1 / -1'}}>{t('Cloudflare API Token')}
          <input type="password" autoComplete="off" value={wildcardToken} onChange={e => setWildcardToken(e.target.value)} placeholder={cfZone.has_token ? t('Stored — leave blank to reuse') : t('Scoped API Token (not the Global API Key)')} />
        </label>
        <button className="manual-ssl-submit" disabled={!selectedWebsiteId || !!loading} onClick={installWildcardSsl}><Globe size={15}/> {wildcardActive ? t('Renew / re-issue wildcard') : t('Issue wildcard certificate')}</button>
        <p className="hint" style={{gridColumn:'1 / -1'}}>{t('Use a')} <strong>{t('scoped API Token')}</strong> {t('from Cloudflare (My Profile → API Tokens → Create Token → permission')} <code>Zone → DNS → Edit</code> {t('for the zone),')} <strong>{t('not')}</strong> {t('the account Global API Key. It is stored encrypted and re-used for automatic renewal. Issues one cert for')} <strong>{wildcardZone || t('the domain')}</strong> {t('and')} <strong>*.{wildcardZone || t('domain')}</strong> {t('via a Cloudflare DNS challenge — no DNS record or port 80 needed. Other websites can then pick this cert under "Use existing".')}</p>
      </div> : sslMode === 'shared' ? <div className="manual-ssl-grid">
        {/* BPanel borrows the certificate of another website that covers
            this one; the list holds only those. */}
        <div className="form-row" style={{gridColumn:'1 / -1'}}>
          <select value={sharedSource} onChange={e => setSharedSource(e.target.value)}>
            <option value="">{t('— pick a certificate on this server —')}</option>
            {sslSources.map(s => <option key={s.domain} value={s.domain}>
              {s.domain}{s.wildcard ? ` · ${t('Wildcard')}` : ''}{s.not_after ? ` · ${t('Expires')} ${s.not_after}` : ''}
            </option>)}
          </select>
          <button className="secondary-light" type="button" disabled={!selectedWebsiteId || !!loading} onClick={() => loadSslSources(selectedWebsiteId)}><RefreshCw size={13}/> {t('Refresh')}</button>
        </div>
        <button className="manual-ssl-submit" disabled={!selectedWebsiteId || !sharedSource || !!loading} onClick={installSharedSsl}><Lock size={15}/> {t('Use this certificate')}</button>
        <p className="hint" style={{gridColumn:'1 / -1'}}>{sslSources.length === 0
          ? t("No certificate on this server covers {domain}. Note a *.example.com wildcard covers x.example.com but not example.com itself. Issue a Let's Encrypt or wildcard cert first.", { domain: currentSite?.domain || '' })
          : t('A *.example.com wildcard covers every x.example.com — issue it once, reuse it everywhere.')}</p>
      </div> : <div className="manual-ssl-grid">
        <label>
          {t('Certificate (.crt/.pem)')}
          <input type="file" accept=".crt,.pem" onChange={e => setManualSslFiles(prev => ({ ...prev, certificate: e.target.files?.[0] || null }))} />
        </label>
        <label>
          {t('Private key (.key/.pem)')}
          <input type="file" accept=".key,.pem" onChange={e => setManualSslFiles(prev => ({ ...prev, private_key: e.target.files?.[0] || null }))} />
        </label>
        <label>
          {t('CA bundle (.ca/.crt/.pem)')}
          <input type="file" accept=".ca,.crt,.pem" onChange={e => setManualSslFiles(prev => ({ ...prev, ca_bundle: e.target.files?.[0] || null }))} />
        </label>
        <textarea rows={7} disabled={!!manualSslFiles.certificate} value={manualSslForm.certificate} onChange={e => setManualSslForm(prev => ({ ...prev, certificate: e.target.value }))} placeholder="-----BEGIN CERTIFICATE-----" />
        <textarea rows={7} disabled={!!manualSslFiles.private_key} value={manualSslForm.private_key} onChange={e => setManualSslForm(prev => ({ ...prev, private_key: e.target.value }))} placeholder="-----BEGIN PRIVATE KEY-----" />
        <textarea rows={7} disabled={!!manualSslFiles.ca_bundle} value={manualSslForm.ca_bundle} onChange={e => setManualSslForm(prev => ({ ...prev, ca_bundle: e.target.value }))} placeholder={t('Optional CA bundle')} />
        <button className="manual-ssl-submit" disabled={!selectedWebsiteId || !!loading} onClick={installManualSsl}><Upload size={15}/> {t('Install Manual SSL')}</button>
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
    // Filtered here, as OPanel's list is: the page already holds them all.
    const dbQuery = dbSearch.trim().toLowerCase();
    const siteById = new Map(websites.map(site => [String(site.id), site.domain]));
    const filteredDatabases = dbQuery
      ? databases.filter(db => (db.db_name || '').toLowerCase().includes(dbQuery)
          || (db.db_user || '').toLowerCase().includes(dbQuery)
          || (siteById.get(String(db.website_id)) || '').toLowerCase().includes(dbQuery))
      : databases;
    function copyToClipboard(text, field) {
      const doCopy = navigator.clipboard ? navigator.clipboard.writeText(text) : new Promise((resolve, reject) => {
        try { const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); resolve(); } catch(e) { reject(e); }
      });
      doCopy.then(() => { setCopiedField(field); setTimeout(() => setCopiedField(null), 2000); }).catch(() => setError(t('Copy failed.')));
    }
    const createOpen = dbCreateOpen || databases.length === 0;
    const openCreate = () => {
      setDbCreateOpen(true);
      setTimeout(() => { const el = document.getElementById('create-database-name'); el?.scrollIntoView({ behavior: 'smooth', block: 'center' }); el?.focus(); }, 0);
    };
    return <section className="section">
      <div className="section-title">
        <h2>{t('Databases')}</h2>
        <div className="actions">
          <button className="secondary" disabled={!!loading} onClick={() => loadDatabases(true)}><RefreshCw size={15}/> {t('Refresh')}</button>
          {!createOpen && <button type="button" onClick={openCreate}><Plus size={15}/> {t('New database')}</button>}
        </div>
      </div>
      {createOpen && <div className="create-inline">
        <div className="create-inline-head">
          <strong>{t('Create database')}</strong>
          {databases.length > 0 && <button type="button" className="secondary icon-only mini" onClick={() => setDbCreateOpen(false)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>}
        </div>
      <div className="form-row">
        <input id="create-database-name" name="new-db-name" autoComplete="off" value={newDatabase.db_name} onChange={e => setNewDatabase(prev => ({ ...prev, db_name: e.target.value }))} placeholder="database_name" />
        <input name="new-db-user" autoComplete="off" value={newDatabase.db_user} onChange={e => setNewDatabase(prev => ({ ...prev, db_user: e.target.value }))} placeholder={t('db_user (default = db_name)')} />
        {/* new-password, or the browser offers the panel's own password here. */}
        <input name="new-db-password" autoComplete="new-password" value={newDatabase.db_password} onChange={e => setNewDatabase(prev => ({ ...prev, db_password: e.target.value }))} placeholder={t('password (min 12 chars)')} />
        <button type="button" className="mini secondary-light" title={t('Generate random password')} onClick={() => setNewDatabase(prev => ({ ...prev, db_password: generateRandomPassword() }))}><Dices size={13}/></button>
        <button disabled={!!loading || !newDatabase.db_name.trim()} onClick={createDatabase}><Plus size={15}/> {t('Create database')}</button>
      </div>
      </div>}
      {createdDbInfo && <div className="info-box db-created-box">
        <div className="db-created-head"><strong>{t('Database created successfully')}</strong><button className="mini secondary-light" onClick={() => setCreatedDbInfo(null)}><X size={13}/></button></div>
        <div className="db-created-grid">
          <label>{t('Database')}</label><span>{createdDbInfo.db_name} <button className="mini secondary-light" title={copiedField === 'db_name' ? t('Copied!') : t('Copy')} onClick={() => copyToClipboard(createdDbInfo.db_name, 'db_name')}>{copiedField === 'db_name' ? <Check size={12} style={{color:'var(--success)'}}/> : <Copy size={12}/>}</button></span>
          <label>{t('User')}</label><span>{createdDbInfo.db_user} <button className="mini secondary-light" title={copiedField === 'db_user' ? t('Copied!') : t('Copy')} onClick={() => copyToClipboard(createdDbInfo.db_user, 'db_user')}>{copiedField === 'db_user' ? <Check size={12} style={{color:'var(--success)'}}/> : <Copy size={12}/>}</button></span>
          <label>{t('Password')}</label><span><code>{createdDbInfo.db_password}</code> <button className="mini secondary-light" title={copiedField === 'db_password' ? t('Copied!') : t('Copy')} onClick={() => copyToClipboard(createdDbInfo.db_password, 'db_password')}>{copiedField === 'db_password' ? <Check size={12} style={{color:'var(--success)'}}/> : <Copy size={12}/>}</button></span>
        </div>
      </div>}
      {databases.length === 0 && !createdDbInfo && <EmptyState icon={Database} message="No databases found." action={{ label: t('New database'), icon: Plus, onClick: openCreate }} />}
      {databases.length > 0 && <div className="list-search">
        <Search size={15}/>
        <NoAutofillInput name="database-search" value={dbSearch} onChange={e => setDbSearch(e.target.value)} placeholder={t('Filter databases…')} />
        {dbSearch && <button className="mini secondary-light" aria-label={t('Clear search')} onClick={() => setDbSearch('')}><X size={13}/></button>}
        <span className="hint">{dbQuery
          ? t('{shown} of {total}', { shown: filteredDatabases.length, total: databases.length })
          : (databases.length === 1 ? t('{n} database', { n: databases.length }) : t('{n} databases', { n: databases.length }))}</span>
      </div>}
      {databases.length > 0 && filteredDatabases.length === 0 && <EmptyState icon={Database} message={t('No database matches “{query}”.', { query: dbSearch })} />}
      <div className="table">
        {filteredDatabases.map(db => {
          // The site a database belongs to, where it belongs to one.
          const dbSite = siteById.get(String(db.website_id));
          const dbOwner = isAdmin ? (users.find(user => user.id === db.owner_id)?.username || `#${db.owner_id}`) : '';
          return <div className="row db-row" key={db.id}>
          <span><strong>{db.db_name}</strong>{dbSite && <small className="db-owner">{dbSite}</small>}{dbOwner && <small className="db-owner">{t('Owner:')} {dbOwner}</small>}</span>
          <span className="db-user"><small>{t('User')}</small> {db.db_user}</span>
          <span className="db-actions">
            <button className="mini secondary" disabled={!!loading} onClick={() => openPhpMyAdmin(db.id)}>phpMyAdmin</button>
            <button className="mini secondary-light" disabled={!!loading} title={t('Download SQL dump')}
                    aria-label={t('Download SQL dump of {name}', { name: db.db_name })}
                    onClick={() => downloadDatabase(db.id, db.db_name)}><Download size={14}/></button>
            <button className="mini secondary-light" disabled={!!loading} title={t('Change database password')}
                    aria-label={t('Change the password for {name}', { name: db.db_name })}
                    onClick={() => changeDbPassword(db.id)}><KeyRound size={14}/></button>
            <button className="mini danger" disabled={!!loading} title={t('Delete database')}
                    aria-label={t('Delete {name}', { name: db.db_name })}
                    onClick={() => deleteDatabase(db.id, db.db_name)}><Trash2 size={14}/></button>
          </span>
        </div>})}
      </div>
      <p className="hint">{t('Click phpMyAdmin to sign in directly. Token expires after 60s.')}</p>
      {isAdmin && databases.length > 0 && <div className="section" style={{marginTop:16}}>
        <h2>{t('Assign database to user')}</h2>
        <div className="assign-row">
          <select value={assignDbId} onChange={e => setAssignDbId(e.target.value)}>
            <option value="">{t('Select database')}</option>
            {databases.map(db => <option key={db.id} value={db.id}>{db.db_name}</option>)}
          </select>
          <select value={assignDbUserId} onChange={e => setAssignDbUserId(e.target.value)}>
            <option value="">{t('Select user')}</option>
            {users.map(user => <option key={user.id} value={user.id}>{user.username} ({t(roleLabel(user.role))})</option>)}
          </select>
          <button disabled={!assignDbId || !assignDbUserId || !!loading} onClick={assignDatabaseToUser}>{t('Assign')}</button>
        </div>
        <p className="hint">{t('The database, its MariaDB user and its password stay as they are; only who manages it in the panel changes. A database linked to a website moves with that website.')}</p>
      </div>}
    </section>;
  }

  function renderSftp() {
    const host = sftpAccounts.find(account => account.host)?.host || window.location.hostname;
    const port = 22;
    const mainUsername = currentUser?.sftp_username || currentUser?.username || '';
    const atLimit = !sftpLimits.unlimited && Number(sftpLimits.limit || 0) > 0
      && Number(sftpLimits.used || 0) >= Number(sftpLimits.limit || 0);
    const noAllowance = !sftpLimits.unlimited && Number(sftpLimits.limit || 0) <= 0;
    const createOpen = showCreateSftp && !atLimit && !noAllowance;
    const canCreate = !!selectedWebsiteId && newSftpAccount.label.trim().length >= 2;
    const editing = sftpPasswordFor;
    const editingOwn = !!editing && !editing.account;
    const canSavePassword = !!editing && editing.password.length >= 12
      && (!editingOwn || (!!editing.current_password && (!currentUser?.totp_enabled || editing.code.trim().length >= 6)));
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('SFTP connection')}</h2>
            <p className="hint">{t('Use FileZilla, WinSCP, Cyberduck or any SFTP client. SSH shells are not available; each login only sees its own folder.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={loadSftpAccounts}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="sftp-connect-grid">
          {renderCopyBlock(t('Host'), host)}
          {renderCopyBlock(t('Port'), String(port))}
          {mainUsername && renderCopyBlock(t('Username'), mainUsername)}
        </div>
        {mainUsername && <div className="info-box sftp-primary">
          <strong>{t('Your main login')}</strong>
          {currentUser?.sftp_password_set_at
            ? <p className="hint">{t('Separate from your panel password. Changing one does not change the other.')} {t('It reaches every website on this account.')}</p>
            : <p className="hint alarm">{t('This login still uses your panel password. Anyone who guesses it over SFTP is also in the panel. Set a separate password — your panel password will stop working for SFTP the moment you do.')}</p>}
          <div className="actions"><button className="mini secondary" onClick={() => setSftpPasswordFor({ account: null, password: generateRandomPassword(), current_password: '', code: '' })}><KeyRound size={13}/> {t('Change password')}</button></div>
        </div>}
        {mainUsername && renderCopyBlock(t('Command line'), `sftp -P ${port} ${mainUsername}@${host}`)}
      </section>

      <section className="section">
        <div className="section-title">
          <div><h2>{t('Extra SFTP accounts')}</h2>
            <p className="hint">{t('A separate login and password for one website — for a developer or designer who should see that website and nothing else.')}</p></div>
          <div className="actions">
            {!createOpen && !atLimit && !noAllowance && <button type="button" onClick={() => setShowCreateSftp(true)}><Plus size={15}/> {t('New SFTP account')}</button>}
          </div>
        </div>
        {noAllowance && <p className="hint">{t('Your hosting package does not include SFTP accounts.')}</p>}
        {atLimit && <p className="hint">{t('You have used all {n} SFTP accounts in your package.', { n: sftpLimits.limit })}</p>}
        {!noAllowance && !sftpLimits.unlimited && !atLimit &&
          <p className="hint">{t('{used} of {limit} SFTP accounts used.', { used: sftpLimits.used, limit: sftpLimits.limit })}</p>}

        {createOpen && <div className="create-inline">
          <div className="create-inline-head">
            <strong>{t('New SFTP account')}</strong>
            <button type="button" className="secondary icon-only mini" onClick={() => setShowCreateSftp(false)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>
          </div>
          <div className="sftp-create-grid">
            <div className="field"><span className="field-label">{t('Website')}</span><WebsiteSelect /></div>
            <div className="field"><span className="field-label">{t('Name')}</span>
              <input value={newSftpAccount.label} maxLength={32} placeholder={t('Name, e.g. designer')} aria-label={t('SFTP account name')}
                onChange={e => setNewSftpAccount(prev => ({ ...prev, label: e.target.value }))} />
            </div>
            <div className="field"><span className="field-label">{t('Password')}</span>
              <div className="password-with-generate">
                <input value={newSftpAccount.password} placeholder={t('password (empty = generate)')} aria-label={t('SFTP password')}
                  onChange={e => setNewSftpAccount(prev => ({ ...prev, password: e.target.value }))} />
                <button type="button" className="secondary icon-only" title={t('Generate random password')} aria-label={t('Generate random password')} onClick={() => setNewSftpAccount(prev => ({ ...prev, password: generateRandomPassword() }))}><Dices size={15}/></button>
              </div>
            </div>
            <button className="sftp-create-submit" disabled={!canCreate || !!loading} onClick={createSftpAccount}><Plus size={14}/> {t('Create')}</button>
          </div>
          <p className="hint">{t('Each account reaches one website and nothing else — not your other sites, and not the server. It signs in over SFTP on port 22 with its own password, which is separate from your panel password.')}</p>
        </div>}

        {createdSftpInfo && <div className="info-box">
          <div className="create-inline-head">
            <strong>{t('SFTP account ready')}</strong>
            <button type="button" className="secondary icon-only mini" onClick={() => setCreatedSftpInfo(null)} aria-label={t('Close')} title={t('Close')}><X size={15}/></button>
          </div>
          <div className="sftp-connect-grid">
            {renderCopyBlock(t('Host'), createdSftpInfo.host)}
            {renderCopyBlock(t('Port'), String(createdSftpInfo.port))}
            {renderCopyBlock(t('Username'), createdSftpInfo.username)}
            {createdSftpInfo.password && renderCopyBlock(t('Password'), createdSftpInfo.password)}
          </div>
          <p className="hint">{t('Folder')}: <code>{createdSftpInfo.path}</code></p>
          {createdSftpInfo.password && <p className="hint">{t('This password is shown once. It is not stored anywhere the panel can read it back.')}</p>}
        </div>}

        {sftpAccounts.length === 0 && !createOpen && !createdSftpInfo && <EmptyState icon={KeyRound} message={t('No extra SFTP accounts yet.')} />}
        {sftpAccounts.length > 0 && <div className="table">
          {sftpAccounts.map(account => <div className="row sftp-row" key={account.id}>
            <span className="sftp-row-name"><strong>{account.username}</strong><small>{account.label}{account.is_active ? '' : ` · ${t('Suspended')}`}</small></span>
            <span className="sftp-row-folder"><code>{account.path}</code>{account.domain && <small>{account.domain}</small>}</span>
            <span className="row-actions">
              <button className="mini secondary" disabled={!!loading} onClick={() => setSftpPasswordFor({ account, password: generateRandomPassword(), current_password: '', code: '' })}><KeyRound size={13}/> {t('Change password')}</button>
              <button className="mini danger" disabled={!!loading} onClick={() => deleteSftpAccount(account)} aria-label={t('Delete {name}', { name: account.username })} title={t('Delete')}><Trash2 size={13}/></button>
            </span>
          </div>)}
        </div>}
      </section>

      {editing && <div className="modal-overlay" onClick={() => setSftpPasswordFor(null)}>
        <div className="modal-card" onClick={e => e.stopPropagation()}>
          <div className="modal-header">
            <h3>{t('New password')} — {editing.account ? editing.account.username : mainUsername}</h3>
            <button className="secondary-light" onClick={() => setSftpPasswordFor(null)} aria-label={t('Close')}><X size={16}/></button>
          </div>
          <div className="modal-body">
            <div className="password-with-generate">
              <input value={editing.password} onChange={e => setSftpPasswordFor(prev => ({ ...prev, password: e.target.value }))} aria-label={t('New password')} />
              <button type="button" className="secondary icon-only" title={t('Generate random password')} aria-label={t('Generate random password')} onClick={() => setSftpPasswordFor(prev => ({ ...prev, password: generateRandomPassword() }))}><Dices size={15}/></button>
              <button type="button" className="secondary icon-only" title={t('Copy')} aria-label={t('Copy')} onClick={() => copyText(editing.password, t('Copied to clipboard.'))}><Copy size={15}/></button>
            </div>
            {editingOwn && <>
              <label className="field"><span className="field-label">{t('Current password')}</span>
                <input type="password" value={editing.current_password} autoComplete="current-password" placeholder={t('Required to confirm')}
                  onChange={e => setSftpPasswordFor(prev => ({ ...prev, current_password: e.target.value }))} />
              </label>
              {currentUser?.totp_enabled && <label className="field"><span className="field-label">{t('2FA code')}</span>
                <input value={editing.code} maxLength={12} inputMode="numeric" placeholder={t('6-digit code')}
                  onChange={e => setSftpPasswordFor(prev => ({ ...prev, code: e.target.value }))} />
              </label>}
            </>}
            <p className="hint">{t('Copy it before saving — it is not shown again. Open sessions of this login keep running until they disconnect.')}</p>
            {editingOwn && <p className="hint">{t('Separate from your panel password. Changing one does not change the other.')}</p>}
          </div>
          <div className="modal-actions">
            <button className="secondary-light" onClick={() => setSftpPasswordFor(null)}>{t('Cancel')}</button>
            <button disabled={!!loading || !canSavePassword} onClick={saveSftpPassword}><Save size={14}/> {t('Save')}</button>
          </div>
        </div>
      </div>}
    </>;
  }

  function cronScheduleLabel(expr) {
    const preset = CRON_PRESETS.find(([value]) => value === normalizeCron(expr));
    return preset ? t(preset[1]) : expr;
  }

  // A preset dropdown beside the raw expression. Picking a preset fills the
  // expression; typing in it (or choosing "Custom") switches to custom.
  function renderSchedulePicker(key, value, onChange, inputId) {
    const preset = CRON_PRESETS.find(([expr]) => expr === normalizeCron(value));
    const custom = customSchedules[key] || !preset;
    return <div className="schedule-picker">
      <select value={custom ? 'custom' : preset[0]} onChange={e => {
        const next = e.target.value;
        if (next === 'custom') {
          setCustomSchedules(prev => ({ ...prev, [key]: true }));
          setTimeout(() => document.getElementById(inputId)?.focus(), 0);
          return;
        }
        setCustomSchedules(prev => ({ ...prev, [key]: false }));
        onChange(next);
      }}>
        {CRON_PRESETS.map(([expr, label]) => <option key={expr} value={expr}>{t(label)}</option>)}
        <option value="custom">{t('Custom…')}</option>
      </select>
      <input id={inputId} value={value} spellCheck={false} placeholder="*/15 * * * *" aria-label={t('Cron expression')}
        onChange={e => { setCustomSchedules(prev => ({ ...prev, [key]: true })); onChange(e.target.value); }} />
    </div>;
  }

  // Named starting points for a cron command, as [key, label, command]. Only
  // what BPanel's cron accepts: the WP-CLI maintenance commands, and a PHP
  // script inside the website with its output discarded or kept in a log.
  function cronCommandTemplates(site) {
    const wordpress = !site || (site.app_type || 'wordpress') === 'wordpress';
    return [
      ...(wordpress ? [['wp-due', 'WP-CLI: run due cron events', 'wp cron event run --due-now']] : []),
      ...(wordpress ? [['wp-plugins', 'WP-CLI: update all plugins', 'wp plugin update --all']] : []),
      ...(wordpress ? [['wp-themes', 'WP-CLI: update all themes', 'wp theme update --all']] : []),
      ...(wordpress ? [['wp-core', 'WP-CLI: update WordPress core', 'wp core update']] : []),
      ['php', 'Run a PHP script', 'php -q cron.php'],
      ['php-quiet', 'Run a PHP script, discard its output', 'php cron.php >/dev/null 2>&1'],
      ['php-log', 'Run a PHP script, keep its output in a log', 'php cron.php >> ../logs/cron.log 2>&1'],
    ];
  }

  function renderCron() {
    const sitePhpVersion = cronPhpInfo.php_version || currentSite?.php_version || '';
    const sitePhpBinary = cronPhpInfo.php_binary || (sitePhpVersion ? `/usr/bin/php${sitePhpVersion}` : 'php');
    const templates = cronCommandTemplates(currentSite);
    const template = templates.find(([, , command]) => command === cronCommand.trim());
    return <section className="section">
      <div className="section-title">
        <div><h2>{t('Cron manager')}</h2></div>
        <button className="secondary" disabled={!selectedWebsiteId || !!loading} onClick={listCron}><RefreshCw size={14}/> {t('Refresh')}</button>
      </div>
      <div className="cron-builder">
        <div className="field"><span className="field-label">{t('Website')}</span><WebsiteSelect /></div>
        <div className="field"><span className="field-label">{t('Schedule')}</span>{renderSchedulePicker('cron', cronSchedule, setCronSchedule, 'cron-schedule-input')}</div>
        <div className="field"><span className="field-label">{t('Command template')}</span>
          <select value={template ? template[0] : 'custom'} onChange={e => { const picked = templates.find(([key]) => key === e.target.value); if (picked) setCronCommand(picked[2]); }}>
            {templates.map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}
            <option value="custom">{t('Custom command')}</option>
          </select>
        </div>
        <div className="field"><span className="field-label">{t('Command')}</span>
          <input value={cronCommand} spellCheck={false} onChange={e => setCronCommand(e.target.value)} placeholder="php -q cron.php >/dev/null 2>&1" />
        </div>
        <button className="cron-add" disabled={!selectedWebsiteId || !cronCommand.trim() || !!loading} onClick={addCron}><Plus size={14}/> {t('Add cron')}</button>
      </div>
      {selectedWebsiteId && <p className="hint">{t('Cron runs as')} <strong>{cronUser || currentSite?.linux_user || 'www-data'}</strong> {t('for the selected website. Accepted commands:')} {t('WP-CLI maintenance commands, or a')} <code>.php</code> {t('file inside public_html.')} {t('Write')} <code>php</code> {t('and BPanel rewrites it to')} <code>{sitePhpBinary}</code>.</p>}
      <div className="cron-list">
        {selectedWebsiteId && cronItems.length === 0 && <EmptyState icon={Clock} message="No cron jobs found for this website." />}
        {cronItems.map(item => <div className="cron-item" key={`${item.index}-${item.line}`}>
          <span className="badge">#{item.index}</span>
          <span><strong>{cronScheduleLabel(item.schedule)} <code className="cron-expr">{item.schedule}</code></strong><small>{item.command || item.line}</small></span>
          <button className="mini danger" disabled={!!loading} onClick={() => deleteCron(item.index)} aria-label={t('Delete')} title={t('Delete')}><Trash2 size={13}/></button>
        </div>)}
      </div>
    </section>;
  }

  function renderChmodDialog() {
    const targets = chmodTarget || [];
    if (targets.length === 0) return null;
    // The octal mode edited as a grid of checkboxes. Any combination is
    // allowed; setgid on a folder is the one special bit the panel sets, and a
    // world-writable mode is warned about rather than refused.
    const bits = octalToPermissionBits(chmodMode);
    const valid = /^[0-7]{3,4}$/.test(chmodMode);
    const onlyDirs = targets.every(item => item.is_dir);
    const hasFiles = targets.some(item => !item.is_dir);
    const worldWritable = !!(bits.other & 2);
    const setBit = (classKey, bitValue) => setChmodMode(permissionBitsToOctal({
      ...bits,
      [classKey]: bits[classKey] ^ bitValue,
    }));
    const title = targets.length === 1 ? targets[0].name : t('{n} selected items', { n: targets.length });
    return <div className="modal-overlay" onClick={() => setChmodTarget(null)}>
      <div className="modal-card chmod-card" role="dialog" aria-modal="true" aria-label={t('Change permissions')} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{t('Permissions')} — {title}</h3>
          <button className="secondary-light" onClick={() => setChmodTarget(null)} aria-label={t('Close')}><X size={16}/></button>
        </div>
        <div className="modal-body">
          <table className="chmod-grid">
            <thead><tr><th></th>{PERMISSION_BITS.map(bit => <th key={bit.key}>{t(bit.label)}</th>)}</tr></thead>
            <tbody>
              {PERMISSION_CLASSES.map(group => <tr key={group.key}>
                <th scope="row">{t(group.label)}</th>
                {PERMISSION_BITS.map(bit => <td key={bit.key}>
                  <input type="checkbox" checked={!!(bits[group.key] & bit.value)}
                    onChange={() => setBit(group.key, bit.value)} aria-label={`${t(group.label)} ${t(bit.label)}`} />
                </td>)}
              </tr>)}
            </tbody>
          </table>
          <div className="chmod-mode-row">
            <label><span>{t('Numeric mode')}</span>
              <input value={chmodMode} maxLength={4} inputMode="numeric" onChange={e => setChmodMode(e.target.value.replace(/[^0-7]/g, '').slice(0, 4))} />
            </label>
            <div className="chmod-presets">
              {(onlyDirs ? PERMISSION_PRESETS.dir : PERMISSION_PRESETS.file).map(([mode, label]) => <button key={mode} type="button" title={t(label)}
                className={`mini ${chmodMode === mode ? 'toggle-on' : 'secondary'}`} onClick={() => setChmodMode(mode)}>{mode}</button>)}
            </div>
          </div>
          {onlyDirs && <label className="check-line">
            <input type="checkbox" checked={bits.special === 2}
              onChange={() => setChmodMode(permissionBitsToOctal({ ...bits, special: bits.special === 2 ? 0 : 2 }))} />
            <span>{t('Setgid — new files inside keep the folder\'s group. BPanel sets this on site folders; leave it on unless you know otherwise.')}</span>
          </label>}
          {worldWritable && <p className="hint alarm"><AlertCircle size={13}/> {hasFiles
            ? t('World-writable: anyone with an account on the server can change these files. Use 755 unless something really needs it.')
            : t('World-writable: anyone with an account on the server can change what is inside these folders. Use 755 unless something really needs it.')}</p>}
          <p className="hint">{t('Any permission combination is allowed. The setuid and sticky bits are not — setgid on a folder is the only special bit the panel sets.')}</p>
        </div>
        <div className="modal-actions">
          <button className="secondary-light" onClick={() => setChmodTarget(null)}>{t('Cancel')}</button>
          <button disabled={!!loading || !valid} onClick={applyChmod}><Save size={14}/> {t('Apply')}</button>
        </div>
      </div>
    </div>;
  }

  function renderFiles() {
    const allSelected = files.length > 0 && selectedFilePaths.length === files.length;
    const activeFileApp = currentFileApp();
    // The websites whose files these are: their own folders are not served.
    const servedDomains = activeFileApp
      ? websites.filter(site => String(site.app_id || '') === String(activeFileApp.id)).map(site => site.domain)
      : [];
    const targetKey = fileTargetKey();
    // A finished extraction leaves the list on its own; a failed one stays
    // until it is dismissed.
    const visibleFileJobs = fileJobs
      .filter(job => (job.target_key || `site:${job.website_id}`) === targetKey && job.status !== 'done')
      .slice(0, 4);
    const selectedArchive = selectedFilePaths.length === 1
      ? files.find(item => item.path === selectedFilePaths[0] && isArchiveFile(item))
      : null;
    const selectedChmodItems = files.filter(item => selectedFilePaths.includes(item.path));
    return <section className="section">
      {renderChmodDialog()}
      <div className="section-title">
        <div><h2>{t('File manager')}</h2></div>
        <button className="secondary" disabled={!hasFileTarget() || !!loading} onClick={() => listFiles(fileListPath)}><RefreshCw size={14}/> {t('Refresh')}</button>
      </div>
      <div className="file-manager">
        <div className="file-panel">
          <div className="file-controls">
            <FileTargetSelect />
            {activeFileApp
              ? <div className="file-meta">
                <span>{t('Application:')} <strong>{activeFileApp.name}</strong></span>
                {servedDomains.length > 0 && <span>{t('Serves:')} <strong>{servedDomains.join(', ')}</strong></span>}
                <span>{t('Root:')} <strong>{activeFileApp.directory}{fileListPath ? `/${fileListPath}` : ''}</strong></span>
                {currentUser && !isAdmin && <span>{t('Storage:')} <strong>{storageUsageText(currentUser)}</strong></span>}
              </div>
              : currentSite && <div className="file-meta">
                <span>{t('Website:')} <strong>{currentSite.domain}</strong></span>
                <span>{t('Root:')} <strong>{currentSite.root_path}{fileListPath ? `/${fileListPath}` : ''}</strong></span>
                {currentUser && !isAdmin && <span>{t('Storage:')} <strong>{storageUsageText(currentUser)}</strong></span>}
              </div>}
            <div className="path-pill breadcrumb-line">
              <button className="crumb" disabled={!hasFileTarget() || fileListPath === ''} onClick={() => listFiles('')}>{t('root')}</button>
              {fileBreadcrumbs(fileListPath).map(crumb => <button className="crumb" key={crumb.path} onClick={() => listFiles(crumb.path)}>{crumb.label}</button>)}
            </div>
            <div className="file-toolbar">
              <button className="secondary" disabled={!hasFileTarget() || fileListPath === '' || !!loading} onClick={() => listFiles(parentFilePath(fileListPath))}>{t('Up')}</button>
              <button className="secondary" disabled={!hasFileTarget() || !!loading} onClick={makeFileDirectory}><Plus size={14}/> {t('Folder')}</button>
              <button className="secondary" disabled={!hasFileTarget() || !!loading} onClick={makeFile}><FileText size={14}/> {t('File')}</button>
              <label className={`upload-button ${(!hasFileTarget() || !!loading) ? 'disabled' : ''}`}>
                <Upload size={14}/> {t('Upload')}
                <input type="file" disabled={!hasFileTarget() || !!loading} onChange={e => { uploadSiteFile(e.target.files?.[0]); e.target.value = ''; }} />
              </label>
              <select value={archiveFormat} onChange={e => setArchiveFormat(e.target.value)} disabled={!hasFileTarget() || !!loading}>
                <option value="zip">zip</option>
                <option value="tar.gz">tar.gz</option>
              </select>
              <button className="secondary" disabled={selectedFilePaths.length === 0 || !!loading} onClick={copySelectedFiles}><Copy size={14}/> {t('Copy')}</button>
              <button className="secondary" disabled={selectedFilePaths.length === 0 || !!loading} onClick={moveSelectedFiles}><MoveRight size={14}/> {t('Move')}</button>
              <button className="secondary" disabled={selectedFilePaths.length === 0 || !!loading} onClick={archiveSelectedFiles}><Archive size={14}/> {t('Archive')}</button>
              <button className="secondary" disabled={!selectedArchive || !!loading} onClick={() => extractArchiveFile(selectedArchive.path)}><PackageOpen size={14}/> {t('Extract')}</button>
              <button className="secondary" disabled={selectedChmodItems.length === 0 || !!loading} onClick={() => openChmodDialog(selectedChmodItems)}><Lock size={14}/> {t('Permissions')}</button>
              <button className="danger" disabled={selectedFilePaths.length === 0 || !!loading} onClick={deleteSelectedFiles}><Trash2 size={14}/> {t('Delete')}</button>
            </div>
            {visibleFileJobs.length > 0 && <div className="file-job-list">
              {visibleFileJobs.map(job => <div className={`file-job ${job.status}`} key={job.job_id}>
                <Clock size={14}/>
                <span><strong>{job.archive_path?.split('/').pop() || t('Archive')}</strong> {job.status === 'done' ? t('completed') : job.status === 'error' ? t('failed') : job.status}</span>
                {job.error && <small>{job.error}</small>}
                <button className="file-job-dismiss" onClick={() => dismissFileJob(job.job_id)} aria-label={t('Dismiss')} title={t('Dismiss')}><X size={13}/></button>
              </div>)}
            </div>}
          </div>
          <div className="file-list-header">
            <label><input type="checkbox" checked={allSelected} onChange={toggleAllFiles} disabled={files.length === 0} /> {t('Select')}</label>
            <span>{t('{n} item(s)', { n: files.length })}</span>
          </div>
          <div className="file-list">
            {files.length === 0 && <div className="empty-box">{t('No files in this folder.')}</div>}
            {files.map(item => <div className={`file-item ${selectedFilePaths.includes(item.path) ? 'selected' : ''}`} key={item.path}>
              <input type="checkbox" checked={selectedFilePaths.includes(item.path)} onChange={() => toggleFileSelection(item.path)} />
              <button className="file-name" onClick={() => item.is_dir ? listFiles(item.path) : (isTextEditable(item) ? openFileEditorTab(item.path) : downloadFile(item.path))}>
                {item.is_dir ? <FolderOpen size={16}/> : <FileText size={16}/>} <strong>{item.name}</strong>
              </button>
              <button type="button" className="file-mode" disabled={!!loading} title={t('Change permissions')} aria-label={t('Change permissions of {name}', { name: item.name })}
                onClick={() => openChmodDialog(item)}>{item.mode || '---'}</button>
              <span className="file-size">{item.is_dir ? t('Folder') : formatBytes(item.size)}{item.modified ? <span className="file-date-inline"> · {formatFileTime(item.modified)}</span> : null}</span>
              <span className="file-date" title={formatFileTime(item.modified, true)}>{formatFileTime(item.modified)}</span>
              <div className="file-row-actions">
                {!item.is_dir && <button className="mini secondary-light" disabled={!!loading} onClick={() => downloadFile(item.path)} aria-label={t('Download')} title={t('Download')}><Download size={13}/></button>}
                {isArchiveFile(item) && <button className="mini secondary-light" disabled={!!loading} onClick={() => extractArchiveFile(item.path)}><PackageOpen size={13}/> {t('Extract')}</button>}
                <button className="mini secondary-light" disabled={!!loading} onClick={() => renameFileItem(item)}>{t('Rename')}</button>
              </div>
            </div>)}
          </div>
        </div>
      </div>
    </section>;
  }

  // ISO time from the server as the file manager shows times.
  function formatIsoTime(value) {
    const ms = Date.parse(value || '');
    return Number.isFinite(ms) ? formatFileTime(ms / 1000) : '';
  }

  // DirectAdmin's restore, step by step: where the backups are, what it takes
  // to reach them, which accounts, go. Upload backups puts archives into the
  // source picked in step 1; the list in step 3 then shows them.
  function renderRestoreWizard() {
    const allGroups = restoreGroupsOf(restoreListing);
    const needle = restoreFilter.trim().toLowerCase();
    const groups = needle
      ? allGroups.filter(group => `${group.username} ${group.backups.map(item => item.name).join(' ')}`.toLowerCase().includes(needle))
      : allGroups;
    const pickedGroups = allGroups.filter(group => restorePicks.includes(group.id));
    const allPicked = groups.length > 0 && groups.every(group => restorePicks.includes(group.id));
    const somePicked = groups.some(group => restorePicks.includes(group.id));
    const job = restoreJob;
    const jobActive = !!job && ['queued', 'running'].includes(job.status);
    const remote = restoreRemote;
    const targets = sftpTargets.filter(target => target.is_active !== false);
    const sources = [
      ['local', HardDrive, 'This server', 'Backups the panel made, and archives uploaded for restore.'],
      ['target', Network, 'Backup Destination', 'An S3 or SFTP destination saved under Backup Destination.'],
      ['remote', Server, 'Another server', 'Pull backups from another server over SFTP, FTP or FTPS.'],
    ];
    const restoreStepTwo = { local: 'Backups on this server', target: 'Destination', remote: 'Connection' }[restoreSource];
    const remoteReady = !!remote.host.trim() && !!remote.username.trim() && !!remote.password;
    const canUse = !loading && !jobActive && (restoreSource !== 'target' || !!restoreTargetId) && (restoreSource !== 'remote' || remoteReady);
    const restoreUpload = <label className={`upload-button secondary${canUse ? '' : ' disabled'}`} aria-disabled={!canUse}>
      <Upload size={14}/> {t('Upload backups')}
      <input type="file" multiple accept=".tar.gz,application/gzip" disabled={!canUse}
        onChange={e => { uploadRestoreBackups(e.target.files); e.target.value = ''; }} />
    </label>;
    const restoreRefresh = <button className="secondary" disabled={!canUse} onClick={() => listRestoreSource(currentRestoreSource())}><RefreshCw size={14}/> {t('Refresh')}</button>;
    const rowStatus = { queued: ['Waiting', 'badge'], fetching: ['Downloading', 'badge warn'], restoring: ['Restoring', 'badge warn'], done: ['Restored', 'badge ok'], failed: ['Failed', 'badge bad'] };
    const restoredCount = (job?.results || []).filter(row => row.status === 'done').length;

    return <div className="backup-tab-panel restore-wizard">
      <div className="backup-panel-title">
        <div><h3>{t('Restore')}</h3><p className="hint">{t('Where the backups are, what that needs, which users - then restore. The same steps as DirectAdmin.')}</p></div>
      </div>

      <section className="restore-step">
        <h4><span className="restore-step-no">1</span>{t('Source')}</h4>
        <div className="restore-sources" role="radiogroup" aria-label={t('Source')}>
          {sources.map(([id, Icon, label, hint]) => <button
            key={id}
            type="button"
            role="radio"
            aria-checked={restoreSource === id}
            disabled={!!loading || jobActive}
            className={`restore-source${restoreSource === id ? ' active' : ''}`}
            onClick={() => chooseRestoreSource(id)}
          >
            <span className="settings-tile-icon"><Icon size={18}/></span>
            <span className="settings-tile-text"><strong>{t(label)}</strong><small>{t(hint)}</small></span>
          </button>)}
        </div>
      </section>

      <section className="restore-step">
        <h4><span className="restore-step-no">2</span>{t(restoreStepTwo)}</h4>
        {restoreSource === 'local' && <>
          <p className="hint">
            {t('Scheduled and manual backups kept on this server, and the ones uploaded here.')}{restoreListing?.location && <> <code>{restoreListing.location}</code></>}
          </p>
          <div className="actions restore-local-actions">{restoreUpload}{restoreRefresh}</div>
        </>}
        {restoreSource === 'target' && <>
          <div className="restore-form-row">
            <select value={restoreTargetId} disabled={!!loading || jobActive} aria-label={t('Destination')}
              onChange={e => { setRestoreTargetId(e.target.value); if (e.target.value) listRestoreSource(`target:${e.target.value}`); }}>
              {!restoreTargetId && <option value="">{t('Choose a destination')}</option>}
              {targets.map(target => <option key={target.id} value={target.id}>{target.name} ({target.kind === 's3' ? 'S3' : 'SFTP'})</option>)}
            </select>
            <div className="actions restore-local-actions">{restoreRefresh}{restoreUpload}</div>
          </div>
          {targets.length === 0 && <p className="hint">{t('No destination saved yet. Add one under Backup Destination.')}</p>}
          {restoreListing?.location && <p className="hint"><code>{restoreListing.location}</code></p>}
        </>}
        {restoreSource === 'remote' && <form className="restore-remote" onSubmit={e => { e.preventDefault(); if (canUse) listRestoreSource('remote'); }} autoComplete="off">
          <label className="field"><span className="field-label">{t('Protocol')}</span>
            <select value={remote.protocol} disabled={jobActive} onChange={e => editRestoreRemote({ protocol: e.target.value })}>
              <option value="sftp">SFTP</option>
              <option value="ftp">FTP</option>
              <option value="ftps">{t('FTPS (FTP over TLS)')}</option>
            </select>
          </label>
          <label className="field"><span className="field-label">{t('Host')}</span><input value={remote.host} placeholder="203.0.113.10" spellCheck={false} disabled={jobActive} onChange={e => editRestoreRemote({ host: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Port')}</span><input value={remote.port} inputMode="numeric" placeholder={remote.protocol === 'sftp' ? '22' : '21'} disabled={jobActive} onChange={e => editRestoreRemote({ port: e.target.value.replace(/[^0-9]/g, '') })} /></label>
          <label className="field"><span className="field-label">{t('Username')}</span><input value={remote.username} spellCheck={false} disabled={jobActive} onChange={e => editRestoreRemote({ username: e.target.value })} /></label>
          <label className="field"><span className="field-label">{t('Password')}</span><input type="password" value={remote.password} autoComplete="new-password" disabled={jobActive} onChange={e => editRestoreRemote({ password: e.target.value })} /></label>
          <label className="field restore-remote-wide"><span className="field-label">{t('Folder')}</span><input value={remote.path} placeholder="/backups" spellCheck={false} disabled={jobActive} onChange={e => editRestoreRemote({ path: e.target.value })} /></label>
          {remote.protocol === 'ftp' && <p className="hint restore-remote-wide">{t('Plain FTP sends the password unencrypted. Use SFTP or FTPS if the server offers it.')}</p>}
          <div className="actions restore-remote-wide">
            <button type="submit" disabled={!canUse}><Search size={14}/> {t('Connect and list backups')}</button>
            {restoreUpload}
            <span className="hint">{t('Used for this restore only; nothing here is saved.')}</span>
          </div>
        </form>}
        {restoreListing?.host_key && <p className="hint">{t('Server key:')} <code>{restoreListing.host_key.type} {restoreListing.host_key.fingerprint}</code></p>}
      </section>

      <section className="restore-step">
        <h4><span className="restore-step-no">3</span>{t('Accounts to restore')}</h4>
        {!restoreListing && <p className="hint">{loading ? t('Reading backups...') : t('The accounts appear here once the source has been read.')}</p>}
        {restoreListing && allGroups.length === 0 && <EmptyState icon={Archive} message={t('No backups found here.')} />}
        {restoreListing && allGroups.length > 0 && <>
          <div className="restore-toolbar">
            <label className="schedule-toggle">
              <input
                type="checkbox"
                checked={allPicked}
                disabled={!!loading || jobActive}
                ref={box => { if (box) box.indeterminate = somePicked && !allPicked; }}
                onChange={e => {
                  const ids = groups.map(group => group.id);
                  setRestorePicks(prev => e.target.checked ? [...new Set([...prev, ...ids])] : prev.filter(id => !ids.includes(id)));
                }}
              />
              <span>{t('Select all')}</span>
            </label>
            {allGroups.length > 6 && <input className="restore-filter" value={restoreFilter} onChange={e => setRestoreFilter(e.target.value)} placeholder={t('Filter accounts')} aria-label={t('Filter accounts')} />}
            <span className="hint">{pickedGroups.length ? t('{n} selected', { n: pickedGroups.length }) : t('{n} account(s)', { n: allGroups.length })}</span>
          </div>
          <div className="restore-accounts">
            {groups.map(group => {
              const chosen = chosenRestoreBackup(group);
              const picked = restorePicks.includes(group.id);
              const exists = !!group.username && (restoreListing.existing || []).includes(group.username);
              const toggle = () => { if (!loading && !jobActive) toggleRestorePick(group.id); };
              const detail = [formatBytes(chosen.size), formatIsoTime(chosen.modified),
                group.username ? '' : t('The user is read from the backup when it is restored')].filter(Boolean).join(' · ');
              return <div
                key={group.id}
                className={`restore-account${picked ? ' picked' : ''}`}
                role="checkbox"
                aria-checked={picked}
                tabIndex={0}
                onClick={toggle}
                onKeyDown={e => { if (e.target === e.currentTarget && (e.key === ' ' || e.key === 'Enter')) { e.preventDefault(); toggle(); } }}
              >
                <input type="checkbox" checked={picked} disabled={!!loading || jobActive} tabIndex={-1} onChange={toggle} onClick={e => e.stopPropagation()} aria-hidden="true" />
                <span className="restore-account-main">
                  <strong>{group.username || chosen.name}</strong>
                  <small>{detail}</small>
                </span>
                {group.username
                  ? <span className={exists ? 'badge warn' : 'badge ok'} title={exists ? t('Exists on this server - will be overwritten') : t('New on this server')}>{exists ? t('Overwrite') : t('New')}</span>
                  : <span />}
                {group.backups.length > 1
                  ? <select className="restore-version" value={chosen.key} disabled={!!loading || jobActive} aria-label={t('Backup to restore')}
                      onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}
                      onChange={e => setRestoreChoice(prev => ({ ...prev, [group.id]: e.target.value }))}>
                      {group.backups.map(item => <option key={item.key} value={item.key}>{item.name}{item.modified ? ` · ${formatIsoTime(item.modified)}` : ''}</option>)}
                    </select>
                  : group.username
                    ? <span className="restore-version-name" title={chosen.key}>{chosen.name}</span>
                    : <span />}
                <span className="restore-delete-spacer" />
              </div>;
            })}
            {groups.length === 0 && <p className="hint">{t('No account matches this filter.')}</p>}
          </div>
        </>}
      </section>

      <section className="restore-step">
        <h4><span className="restore-step-no">4</span>{t('Restore')}</h4>
        <div className="actions">
          <button disabled={!!loading || jobActive || pickedGroups.length === 0} onClick={runRestore}>
            <RotateCcw size={14}/> {pickedGroups.length ? t('Restore {n} account(s)', { n: pickedGroups.length }) : t('Restore')}
          </button>
          {!pickedGroups.length && !jobActive && <span className="hint">{t('Pick at least one account above.')}</span>}
        </div>
        {job && <div className={`backup-job ${job.status}`} aria-live="polite">
          <Clock size={14}/>
          <span>
            <strong>{jobActive ? t('Restoring') : job.status === 'done' ? t('Restore finished') : t('Restore finished with errors')}</strong>
            <small className="restore-job-message">{jobActive
              ? t('Restoring: {done} of {total} done', { done: restoredCount, total: (job.results || []).length })
              : t('Finished: {done} of {total} restored', { done: restoredCount, total: (job.results || []).length })}</small>
            {jobActive && <span className="job-progress">
              <span className="progress-bar indeterminate"><span className="progress-bar-fill" /></span>
            </span>}
          </span>
          <span className={job.status === 'done' ? 'badge ok' : job.status === 'error' ? 'badge bad' : 'badge'}>{job.status}</span>
        </div>}
        {(job?.results || []).length > 0 && <div className="backup-list">
          {job.results.map((row, index) => {
            const [label, badge] = rowStatus[row.status] || rowStatus.queued;
            return <div className="backup-item" key={`${row.name}-${index}`}>
              <span>{row.username || row.name}{row.status === 'failed' && row.detail && <small>{row.detail}</small>}</span>
              <span className={badge}>{t(label)}</span>
            </div>;
          })}
        </div>}
      </section>
    </div>;
  }

  function renderBackups() {
    const selectedBackupUser = users.find(user => String(user.id) === String(selectedBackupUserId));
    const jobTitle = job => ({ site_backup: t('Website backup'), user_backup: t('Full user backup'), sftp_backup: t('SFTP backup'), user_restore: t('Restore') }[job.kind] || t('Backup task'));
    const jobDetail = job => job.error || job.remote_file || job.backup_file || job.message || job.status;
    const jobTimestamp = job => {
      const stamp = job.finished_at || job.started_at || job.created_at || '';
      if (!stamp) return t('No timestamp');
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
    const nameSuffixLabels = { none: 'Append: nothing', day_of_week: 'Append: day of week', week_of_month: 'Append: week of month', full_date: 'Append: full date' };
    const backupTabs = isAdmin
      ? [
        ['website', 'Backup website', Globe],
        ['user', 'Backup user', Users],
        ['restore', 'Restore', RotateCcw],
        ['schedule', 'Scheduled backups', Clock],
        ['destination', 'Backup Destination', Network],
        ['logs', 'Backup logs', FileText],
        ['da-import', 'DA Import', ArchiveRestore],
      ]
      : [
        ['website', 'Backup website', Globe],
        ['logs', 'Backup logs', FileText],
      ];
    const activeBackupTab = backupTabs.some(([id]) => id === backupTab) ? backupTab : 'website';

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

      {activeBackupTab === 'logs' && <div className="backup-tab-panel backup-logs-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup logs')}</h3><p className="hint">{t('Recent queued, running, completed, and failed backup tasks.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={() => loadBackupJobs(true)}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {backupJobs.length === 0 && <EmptyState icon={FileText} message={t('No backup logs found.')} />}
        {backupJobs.length > 0 && <div className="backup-job-list">
          {backupJobs.map(job => <div className={`backup-job ${job.status}`} key={job.job_id}>
            <Clock size={14}/>
            <span>
              <strong>{jobTitle(job)}</strong>
              <small>{jobDetail(job)}</small>
              {/* No percentage: the server reports a task as queued, running
                  or finished, nothing in between. */}
              {(job.status === 'running' || job.status === 'queued') && <span className="job-progress">
                <span className="progress-bar indeterminate"><span className="progress-bar-fill" /></span>
              </span>}
              <small className="backup-job-time">{jobTimestamp(job)}</small>
            </span>
            <span className={job.status === 'done' ? 'badge ok' : job.status === 'error' ? 'badge bad' : 'badge'}>{job.status}</span>
          </div>)}
        </div>}
      </div>}

      {activeBackupTab === 'website' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup website')}</h3><p className="hint">{t('Backups include website source files and a database SQL export.')}</p></div>
        </div>
        <WebsiteSelect />
        <div className="actions backup-toolbar">
          <button disabled={!selectedWebsiteId || !!loading} onClick={createBackup}><Plus size={14}/> {t('Create backup')}</button>
          <button className="secondary" disabled={!selectedWebsiteId || !!loading} onClick={refreshBackupArea}><RefreshCw size={14}/> {t('Refresh')}</button>
          <label className="upload-button secondary">
            <Upload size={14}/> {t('Upload backup')}
            <input type="file" accept=".tar.gz,application/gzip" onChange={e => { uploadBackup(e.target.files?.[0]); e.target.value = ''; }} />
          </label>
        </div>
        {backups.length === 0 && selectedWebsiteId && <EmptyState icon={Archive} message={t('No backups found for this website.')} action={{ label: t('Create backup'), icon: Plus, onClick: () => { if (!loading) createBackup(); } }} />}
        <div className="backup-list">
          {backups.map(file => <div className="backup-item" key={file}>
            <span>{file.split('/').pop()}</span>
            <div className="actions">
              <button className="secondary" disabled={!!loading} onClick={() => downloadBackup(file)}><Download size={14}/> {t('Download')}</button>
              <button className="secondary" disabled={!!loading} onClick={() => restoreBackup(file)}><RotateCcw size={14}/> {t('Restore')}</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteBackup(file)} aria-label={t('Delete')} title={t('Delete')}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'user' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup user')}</h3><p className="hint">{t('Includes the panel user, all owned websites, source files, database dumps, and restore metadata.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={refreshUserBackupArea}><RefreshCw size={14}/> {t('Reload')}</button>
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
          <button disabled={!selectedBackupUserId || !!loading} onClick={createUserBackup}><Archive size={14}/> {t('Create backup')}</button>
        </div>
        {selectedBackupUser && <p className="hint">{t('Current user:')} <strong>{selectedBackupUser.username}</strong></p>}
        <div className="actions backup-subactions">
          <button className="secondary" disabled={!selectedBackupUserId || !!loading} onClick={() => listUserBackups()}><RefreshCw size={14}/> {t('Refresh list')}</button>
        </div>
        {selectedBackupUserId && userBackups.length === 0 && <EmptyState icon={Archive} message={t('No user backups found.')} />}
        <div className="backup-list">
          {userBackups.map(file => <div className="backup-item" key={file}>
            <span>{file.split('/').pop()}</span>
            <div className="actions">
              <button className="secondary" disabled={!!loading} onClick={() => downloadUserBackup(file)}><Download size={14}/> {t('Download')}</button>
              <button className="secondary" disabled={!!loading} onClick={() => restoreUserBackup(file)}><RotateCcw size={14}/> {t('Restore user')}</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteUserBackup(file)} aria-label={t('Delete')} title={t('Delete')}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>

        <div className="backup-panel-title backup-subtitle">
          <div><h3>{t('Restore folder')}</h3><p className="hint">{restoreBackupDir || '/var/backups/bpanel/users/restore'}</p></div>
          <div className="actions">
            <button className="secondary" disabled={!!loading} onClick={loadRestoreBackups}><RefreshCw size={14}/> {t('Refresh')}</button>
            <label className="upload-button secondary">
              <Upload size={14}/> {t('Upload backups')}
              <input type="file" multiple accept=".tar.gz,application/gzip" onChange={e => { uploadUserBackups(e.target.files); e.target.value = ''; }} />
            </label>
          </div>
        </div>
        {restoreBackups.length === 0 && <EmptyState icon={ArchiveRestore} message={t('No backups found here.')} />}
        <div className="backup-list">
          {restoreBackups.map(item => <div className="backup-item" key={item.backup_file}>
            <span>{item.filename || item.backup_file.split('/').pop()}<small>{item.valid ? `${item.source === 'opanel' ? 'OPanel · ' : ''}` + t('{user} - {n} website(s)', { user: item.username || t('unknown user'), n: item.websites || 0 }) : (item.error || t('Invalid backup'))}</small></span>
            <div className="actions">
              <button className="secondary" disabled={!!loading} onClick={() => downloadUserBackup(item.backup_file)}><Download size={14}/> {t('Download')}</button>
              <button className="secondary" disabled={!!loading || !item.valid} onClick={() => restoreUserBackup(item.backup_file)}><RotateCcw size={14}/> {t('Restore user')}</button>
              <button className="danger" disabled={!!loading} onClick={() => deleteRestoreBackup(item.backup_file)} aria-label={t('Delete')} title={t('Delete')}><Trash2 size={14}/></button>
            </div>
          </div>)}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'restore' && renderRestoreWizard()}

      {isAdmin && activeBackupTab === 'schedule' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Scheduled backups')}</h3><p className="hint">{t('Runs a full user backup on a schedule, with an optional off-server destination.')} {t('With a destination, the backups are kept there only: each one is removed from this server once it has uploaded, and stays here only if the upload fails.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={refreshScheduledBackupArea}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="backup-schedule-builder with-name">
          <div className="field"><span className="field-label">{t('Accounts')}</span>
            <label className="check-line">
              <input type="checkbox" checked={!!newBackupSchedule.all_users} onChange={e => setNewBackupSchedule(prev => ({ ...prev, all_users: e.target.checked }))} />
              {t('All users')}
            </label>
            {!newBackupSchedule.all_users && <select multiple value={newBackupSchedule.user_ids || []} onChange={e => setNewBackupSchedule(prev => ({ ...prev, user_ids: Array.from(e.target.selectedOptions, option => option.value) }))}>
              {users.map(user => <option key={user.id} value={String(user.id)}>{user.username}</option>)}
            </select>}
          </div>
          <div className="field"><span className="field-label">{t('Schedule')}</span>{renderSchedulePicker('backup', newBackupSchedule.schedule, value => setNewBackupSchedule(prev => ({ ...prev, schedule: value })), 'backup-schedule-input')}</div>
          <div className="field"><span className="field-label">{t('Destination')}</span>
            <select value={newBackupSchedule.target_id} onChange={e => setNewBackupSchedule(prev => ({ ...prev, target_id: e.target.value }))}>
              <option value="">{t('Local only')}</option>
              {sftpTargets.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}
            </select>
          </div>
          <div className="field"><span className="field-label">{t('Stored file name')}</span>
            <select value={newBackupSchedule.name_suffix} aria-label={t('Stored file name')}
              onChange={e => setNewBackupSchedule(prev => ({ ...prev, name_suffix: e.target.value }))}>
              <option value="none">{t('Append: nothing')}</option>
              <option value="day_of_week">{t('Append: day of week')}</option>
              <option value="week_of_month">{t('Append: week of month')}</option>
              <option value="full_date">{t('Append: full date')}</option>
            </select>
          </div>
          <button className="backup-schedule-add" disabled={(!newBackupSchedule.all_users && (!newBackupSchedule.user_ids || newBackupSchedule.user_ids.length === 0)) || !!loading} onClick={createBackupSchedule}><Clock size={14}/> {t('Schedule')}</button>
        </div>
        <p className="hint">{t('The name suffix decides how many copies are kept: nothing keeps one per account, day of week keeps seven, week of month five, and full date one a day until retention removes it.')}</p>
        <div className="backup-list">
          {backupSchedules.map(item => {
            const scheduleTarget = sftpTargets.find(target => target.id === item.target_id);
            const suffix = item.name_suffix && item.name_suffix !== 'full_date' && nameSuffixLabels[item.name_suffix];
            return <div className="backup-item" key={item.id}>
              <span>{scheduleUserLabel(item)} - {cronScheduleLabel(item.schedule)}{scheduleTarget ? ` - ${scheduleTarget.name}` : ''}{suffix ? ` - ${t(suffix)}` : ''}
                {item.last_status === 'running'
                  ? <>
                    <small>{item.last_message || t('Running')}</small>
                    <span className="job-progress">
                      <span className="progress-bar indeterminate"><span className="progress-bar-fill" /></span>
                    </span>
                  </>
                  : <small>{item.last_status}: {item.last_message || t('not run yet')}</small>}
              </span>
              <div className="actions">
                <button className="secondary" disabled={!!loading || item.last_status === 'running'} onClick={() => runBackupScheduleNow(item)}><Play size={14}/> {t('Run now')}</button>
                <button className="danger" disabled={!!loading} onClick={() => deleteBackupSchedule(item.id)} aria-label={t('Delete')} title={t('Delete')}><Trash2 size={14}/></button>
              </div>
            </div>;
          })}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'destination' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('Backup Destination')}</h3><p className="hint">{t('Where off-server backup copies are sent. SFTP, or any S3-compatible object storage.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={loadSftpTargets}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="sftp-form sftp-target-form">
          <input value={newSftpTarget.name} onChange={e => setNewSftpTarget(prev => ({ ...prev, name: e.target.value }))} placeholder={t('Destination name')} />
          <select value={newSftpTarget.kind} onChange={e => setNewSftpTarget(prev => ({ ...prev, kind: e.target.value }))} aria-label={t('Destination type')}>
            <option value="sftp">SFTP</option>
            <option value="s3">{t('S3 compatible')}</option>
          </select>

          {newSftpTarget.kind === 'sftp' ? <>
            <input value={newSftpTarget.host} onChange={e => setNewSftpTarget(prev => ({ ...prev, host: e.target.value }))} placeholder={t('Host')} />
            <input value={newSftpTarget.port} onChange={e => setNewSftpTarget(prev => ({ ...prev, port: e.target.value }))} placeholder="22" inputMode="numeric" />
            <input value={newSftpTarget.username} onChange={e => setNewSftpTarget(prev => ({ ...prev, username: e.target.value }))} placeholder={t('Username')} />
            <input value={newSftpTarget.password} onChange={e => setNewSftpTarget(prev => ({ ...prev, password: e.target.value }))} placeholder={t('Password')} type="password" />
            <input value={newSftpTarget.remote_path} onChange={e => setNewSftpTarget(prev => ({ ...prev, remote_path: e.target.value }))} placeholder="/backups/bpanel" />
            <textarea value={newSftpTarget.private_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, private_key: e.target.value }))} placeholder={t('Private key (optional)')} rows={4} />
          </> : <>
            <input id="s3-bucket" value={newSftpTarget.bucket} onChange={e => setNewSftpTarget(prev => ({ ...prev, bucket: e.target.value }))} placeholder={t('Bucket')} />
            <input id="s3-endpoint" value={newSftpTarget.endpoint} onChange={e => setNewSftpTarget(prev => ({ ...prev, endpoint: e.target.value }))} placeholder="s3.wasabisys.com" />
            <input id="s3-region" value={newSftpTarget.region} onChange={e => setNewSftpTarget(prev => ({ ...prev, region: e.target.value }))} placeholder={t('Region (optional)')} />
            <input id="s3-access" value={newSftpTarget.access_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, access_key: e.target.value }))} placeholder={t('Access key')} />
            <input id="s3-secret" value={newSftpTarget.secret_key} onChange={e => setNewSftpTarget(prev => ({ ...prev, secret_key: e.target.value }))} placeholder={t('Secret key')} type="password" />
            <input id="s3-prefix" value={newSftpTarget.prefix} onChange={e => setNewSftpTarget(prev => ({ ...prev, prefix: e.target.value }))} placeholder={t('Prefix, e.g. bpanel/nightly (optional)')} />
            <label className="check-line">
              <input id="s3-secure" type="checkbox" checked={!!newSftpTarget.secure} onChange={e => setNewSftpTarget(prev => ({ ...prev, secure: e.target.checked }))} />
              {t('Use HTTPS')}
            </label>
          </>}

          <button disabled={!!loading || !newSftpTarget.name || (newSftpTarget.kind === 's3'
            ? (!newSftpTarget.endpoint || !newSftpTarget.bucket || !newSftpTarget.access_key || !newSftpTarget.secret_key)
            : (!newSftpTarget.host || !newSftpTarget.username || (!newSftpTarget.password && !newSftpTarget.private_key)))}
            onClick={createSftpTarget}><Plus size={14}/> {t('Save destination')}</button>
        </div>
        {newSftpTarget.kind === 's3' && <p className="hint">{t('Works with S3 and anything that speaks its API: Wasabi, Backblaze B2, DigitalOcean Spaces, Cloudflare R2, MinIO. The bucket is checked before the target is saved, so a destination that cannot be reached never gets attached to a schedule.')}</p>}
        {sftpTargets.length === 0 && <EmptyState icon={Network} message={t('No backup destinations found.')} />}
        <div className="backup-list">
          {sftpTargets.map(target => <div className="backup-item" key={target.id}>
            <span>
              <span className="badge">{target.kind === 's3' ? 'S3' : 'SFTP'}</span>{' '}
              {target.name} &mdash; {target.kind === 's3'
                ? `${target.endpoint}/${target.bucket}${target.prefix ? '/' + target.prefix : ''}`
                : `${target.username}@${target.host}:${target.remote_path}`}
            </span>
            <span className="backup-item-actions">
              <button className="danger" disabled={!!loading} onClick={() => deleteSftpTarget(target.id)} aria-label={t('Delete')} title={t('Delete')}><Trash2 size={14}/></button>
            </span>
          </div>)}
        </div>
      </div>}

      {isAdmin && activeBackupTab === 'da-import' && <div className="backup-tab-panel">
        <div className="backup-panel-title">
          <div><h3>{t('DirectAdmin Import')}</h3><p className="hint">{t('Import websites, databases, and users from a DirectAdmin backup archive.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={() => listDaBackups()}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="actions backup-toolbar">
          <label className="upload-button">
            <Upload size={14}/> {t('Upload DA backup')}
            <input ref={daFileInputRef} type="file" accept=".tar.zst,.tzst,.tar.gz,.tgz,.tar.bz2,.tbz2,.tar.xz,.txz,.tar" onChange={e => { uploadDaBackup(e.target.files?.[0]); e.target.value = ''; }} />
          </label>
          <label className="check-line">
            <input type="checkbox" checked={daReplaceExisting} onChange={e => setDaReplaceExisting(e.target.checked)} />
            {t('Replace existing users/websites')}
          </label>
        </div>
        {daReplaceExisting && <p className="hint alarm">{t('Imports will delete any existing panel user, website, files and databases that share a name with the backup. Leave this off to have conflicting imports stop instead.')}</p>}
        {daBackups.length === 0 && <EmptyState icon={ArchiveRestore} message={t('No DirectAdmin backups uploaded. Upload a DA backup archive to get started.')} />}
        {daBackups.length > 0 && <>
          <div className="restore-toolbar">
            <label className="schedule-toggle">
              <input type="checkbox" checked={selectedDaBackups.length === daBackups.length && daBackups.length > 0} onChange={toggleSelectAllDaBackups} />
              <span>{t('Select all ({n})', { n: daBackups.length })}</span>
            </label>
            {selectedDaBackups.length > 0 && <div className="actions">
              <button disabled={!!loading} onClick={() => bulkImportDaBackups()}><ArchiveRestore size={14}/> {t('Restore selected ({n})', { n: selectedDaBackups.length })}</button>
              <button className="danger" disabled={!!loading} onClick={bulkDeleteDaBackups}><Trash2 size={14}/> {t('Delete selected ({n})', { n: selectedDaBackups.length })}</button>
            </div>}
          </div>
          <div className="restore-accounts">
            {daBackups.map(file => {
              const picked = selectedDaBackups.includes(file.path);
              const toggle = () => toggleDaBackupSelect(file.path);
              return <div
                key={file.path}
                className={`restore-account${picked ? ' picked' : ''}`}
                role="checkbox"
                aria-checked={picked}
                tabIndex={0}
                onClick={toggle}
                onKeyDown={e => { if (e.target === e.currentTarget && (e.key === ' ' || e.key === 'Enter')) { e.preventDefault(); toggle(); } }}
              >
                <input type="checkbox" checked={picked} tabIndex={-1} onChange={toggle} onClick={e => e.stopPropagation()} aria-hidden="true" />
                <span className="restore-account-main"><strong>{file.filename}</strong><small>{formatBytes(file.size)}</small></span>
                <span className="badge">DirectAdmin</span>
                <span className="actions" onClick={e => e.stopPropagation()}>
                  <button className="mini secondary" disabled={!!loading} onClick={() => scanDaBackup(file.path)}><Search size={13}/> {t('Scan')}</button>
                  <button className="mini secondary" disabled={!!loading} onClick={() => importDaBackup(file.path)}><ArchiveRestore size={13}/> {t('Import')}</button>
                </span>
                <button type="button" className="danger restore-delete" disabled={!!loading} aria-label={t('Delete')} title={t('Delete')}
                  onClick={e => { e.stopPropagation(); deleteDaBackup(file.path); }}><Trash2 size={14}/></button>
              </div>;
            })}
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

        {daImportJob && <div className={`backup-job ${daImportJob.status}`}>
          <Clock size={14}/>
          <span><strong>{t('DA Import')}</strong><small>{daImportJob.archive || ''}</small></span>
          <span className={daImportJob.status === 'completed' ? 'badge ok' : daImportJob.status === 'failed' ? 'badge bad' : 'badge'}>{daImportJob.status}</span>
        </div>}
        {daImportJob?.status === 'failed' && <div className="da-scan-result">
          {daImportJob.error && <p className="hint alarm">{daImportJob.error}</p>}
          {daImportJob.log?.length > 0 && <details className="da-creds-details">
            <summary>{t('Import log')}</summary>
            <pre className="da-credentials">{daImportJob.log.join('\n')}</pre>
          </details>}
        </div>}
        {daImportJob?.status === 'completed' && daImportJob.result?.summary && <div className="da-scan-result">
          <h4>{t('Import summary')}</h4>
          {daImportJob.result.errors?.length > 0 && <p className="hint alarm">{t('Errors:')} {daImportJob.result.errors.join('; ')}</p>}
          {daImportJob.result.summary.map((item, i) => <div key={i} className="da-user-block">
            <p className="da-user-head"><strong>{item.username}</strong> <span className="badge ok">{t('{n} domain(s)', { n: item.imported_domains?.length || 0 })}</span> <span className="badge">{t('{n} database(s)', { n: item.databases?.length || 0 })}</span></p>
            {item.aliases?.length > 0 && <p className="hint">{t('Pointers:')} {item.aliases.join(', ')}</p>}
            {item.ssl_enabled_domains?.length > 0 && <p className="hint">{t('SSL enabled:')} {item.ssl_enabled_domains.join(', ')}</p>}
            {item.warnings?.length > 0 && <p className="hint alarm">{t('Warnings:')} {item.warnings.join('; ')}</p>}
          </div>)}
          {daImportJob.result.credentials && <details className="da-creds-details">
            <summary>{t('Generated credentials (click to show)')}</summary>
            <pre className="da-credentials">{daImportJob.result.credentials.join('\n')}</pre>
          </details>}
        </div>}

        {daBulkImportJob && <div className={`backup-job ${daBulkImportJob.status}`}>
          <Clock size={14}/>
          <span><strong>{t('Bulk restore')}</strong><small>{daBulkImportJob.status === 'running' ? `${daBulkImportJob.current + 1}/${daBulkImportJob.total}: ${daBulkImportJob.current_archive}` : t('{n} backup(s)', { n: daBulkImportJob.total })}</small></span>
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
        <div><h2>{t('Services')}</h2><p className="hint">{t('Auto-refreshes every 10s')}</p></div>
        <button className="secondary" disabled={!!loading} onClick={checkAllServices}><RefreshCw size={15}/> {t('Refresh')}</button>
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
              <button className="secondary" disabled={active} onClick={() => runServiceAction(name, 'start')}><Play size={13}/> {t('Start')}</button>
              {canStop && <button className="danger-light" disabled={inactive} onClick={() => runServiceAction(name, 'stop')}><Square size={13}/> {t('Stop')}</button>}
              <button className="secondary" onClick={() => runServiceAction(name, 'restart')}><RotateCcw size={13}/> {t('Restart')}</button>
            </div>}
          </div>;
        })}
      </div>
    </section>;
  }

  function renderPhpExtensions() {
    const versions = phpExtensions.versions || [];
    // Nothing to draw until the table has loaded: an empty list here is the
    // request still on its way, not a server without PHP.
    if (versions.length === 0) return null;
    return <div className="user-create-card php-ext-card" style={{ marginTop: 16 }}>
      <div className="php-ext-head">
        <h3>{t('PHP extensions')}</h3>
        <p className="hint">{t('Server-wide: every website on a PHP version gets its extensions. Installing one reloads PHP-FPM; removing is not offered here, since a website may depend on it.')}</p>
      </div>
      <div className="php-ext-table-wrap">
        <table className="php-ext-table">
          <thead><tr>
            <th>{t('Extension')}</th>
            {versions.map(v => <th key={v}>PHP {v}</th>)}
            <th aria-label={t('Install all')}></th>
          </tr></thead>
          <tbody>
            {phpExtensions.extensions.map(ext => {
              const missingOn = versions.filter(v => ext.versions[v] === 'available');
              return <tr key={ext.name}>
                <td><code>{ext.name}</code></td>
                {versions.map(v => {
                  const state = ext.versions[v];
                  if (state === 'installed' || state === 'builtin') {
                    return <td key={v}><span className="php-ext-installed" title={state === 'builtin' ? t('Built into PHP') : ''}>{t('Installed')}</span></td>;
                  }
                  if (state === 'available') {
                    return <td key={v}><button className="mini secondary-light php-ext-install" disabled={!!loading}
                      title={t('Install on PHP {version}', { version: v })} aria-label={t('Install {extension} on PHP {version}', { extension: ext.name, version: v })}
                      onClick={() => installPhpExtension(ext.name, [v])}><Download size={14}/></button></td>;
                  }
                  return <td key={v}><span className="php-ext-na" title={t('Not in repository')}>—</span></td>;
                })}
                <td className="php-ext-all">{missingOn.length > 0 && <button className="mini secondary" disabled={!!loading}
                  onClick={() => installPhpExtension(ext.name, missingOn)}>{t('Install all')}</button>}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
    </div>;
  }

  function renderPhpConfig() {
    if (!isAdmin) return <section className="section"><h2>{t('PHP config')}</h2><p className="hint">{t('You do not have permission to edit PHP config.')}</p></section>;
    const notInstalled = sortPhpVersions(phpVersions.supported.filter(v => !phpVersions.installed.includes(v)));
    const opcacheOn = !!phpTune?.opcache_enabled;
    // The settings Auto-tune would actually change. A row that already
    // matches, or one pinned by the form above (it always wins - PHP reads it
    // last), is not a decision to make.
    const tuneChanges = (phpTune?.settings || []).filter(row => row.changes && !row.overridden_value);
    // Every pool on a server is sized from the same CPU/RAM/pool-count budget,
    // so they normally all carry identical numbers. Collapse to "N/N pools
    // run X" and list only the ones that do not match.
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
        {/* Switched straight away through its own endpoint, not saved with the
            form: Auto-tune must not turn it back on behind the admin's back. */}
        <label className="php-opcache-toggle"><span>{t('OPcache')}</span>
          <button
            type="button"
            className={opcacheOn ? 'toggle-on' : 'secondary'}
            aria-pressed={opcacheOn}
            disabled={!!loading || !phpTune}
            onClick={toggleOpcache}
            title={t('OPcache is {state} for PHP {version}. Press to switch it.', { state: opcacheOn ? t('on') : t('off'), version: phpTune?.php_version || phpConfig.php_version })}
          >
            <Zap size={14}/> {opcacheOn ? t('Enabled') : t('Disabled')}
          </button>
        </label>
        <label><span>max_execution_time</span><input type="number" value={phpConfig.max_execution_time} onChange={e => setPhpConfig(prev => ({ ...prev, max_execution_time: e.target.value }))} /></label>
        <label><span>max_input_time</span><input type="number" value={phpConfig.max_input_time} onChange={e => setPhpConfig(prev => ({ ...prev, max_input_time: e.target.value }))} /></label>
        <label><span>max_input_vars</span><input type="number" value={phpConfig.max_input_vars} onChange={e => setPhpConfig(prev => ({ ...prev, max_input_vars: e.target.value }))} /></label>
        <label><span>memory_limit</span><input value={phpConfig.memory_limit} onChange={e => setPhpConfig(prev => ({ ...prev, memory_limit: e.target.value }))} placeholder="1024M" /></label>
        <label><span>post_max_size</span><input value={phpConfig.post_max_size} onChange={e => setPhpConfig(prev => ({ ...prev, post_max_size: e.target.value }))} placeholder="1024M" /></label>
        <label><span>upload_max_filesize</span><input value={phpConfig.upload_max_filesize} onChange={e => setPhpConfig(prev => ({ ...prev, upload_max_filesize: e.target.value }))} placeholder="1024M" /></label>
        <button className="secondary-light" disabled={!!loading} onClick={restorePhpDefaults}><RotateCcw size={14}/> {t('Restore defaults')}</button>
        <button className="secondary-light" disabled={!!loading} onClick={() => { setPhpTuneOpen(true); loadPhpTune(phpConfig.php_version); }}><Zap size={14}/> {t('Auto-tune')}</button>
        <button disabled={!!loading} onClick={updatePhpConfig}>{t('Save')}</button>
      </div>
      {phpTuneOpen && phpTune && <div className="user-create-card php-tune-card" style={{ marginTop: 16, borderColor: 'var(--accent)' }}>
        <h3>{t('⚡ Auto-tune Recommendation')}</h3>
        <p className="hint">{t('Based on {ram} MB RAM, {cores} CPU cores and {pools} PHP pool(s).', { ram: phpTune.facts?.total_memory_mb, cores: phpTune.facts?.cpu_count, pools: phpTune.facts?.pool_count ?? 0 })}</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 24px', margin: '12px 0', fontSize: '0.9em' }}>
          {(phpTune.settings || []).map(row => <div key={row.key}>
            <strong>{row.key}:</strong> {row.value}
            {row.changes && !row.overridden_value ? <small> ({t('now {value}', { value: row.current || t('unset') })})</small> : null}
          </div>)}
        </div>
        <p className="hint">{tuneChanges.length > 0
          ? t('Auto tune will change {n} setting(s) for PHP {version}', { n: tuneChanges.length, version: phpTune.php_version })
          : t('PHP {version} already matches what auto tune recommends for this machine.', { version: phpTune.php_version })}</p>
        {commonPools && <p className="hint">{t('PHP-FPM pools: {n}/{total} run pm.max_children={children}, idle {idle}, up to {requests} requests per process.', {
          n: commonPools.length, total: phpTune.pools.length, children: commonPools[0].max_children || '—',
          idle: commonPools[0].idle_timeout || '—', requests: commonPools[0].max_requests || '—',
        })}{poolOutliers.length > 0 ? ' ' + t('{n} other pool(s) run different settings:', { n: poolOutliers.length }) : ''}</p>}
        {poolOutliers.length > 0 && <ul className="php-tune-pool-outliers">
          {poolOutliers.map(p => <li key={p.pool}>
            <code>{p.pool}</code>
            <span>pm.max_children={p.max_children || '—'}, {t('idle {idle}, up to {requests} requests', { idle: p.idle_timeout || '—', requests: p.max_requests || '—' })}</span>
          </li>)}
        </ul>}
        {phpTuneApplied && <p className="hint"><Check size={14}/> {t('PHP {version} tuned.', { version: phpTune.php_version })}</p>}
        <button disabled={!!loading} onClick={applyPhpTune}><Zap size={14}/> {t('Apply Auto-tune to PHP')} {phpTune.php_version}</button>
        <button className="secondary-light" style={{ marginLeft: 8 }} onClick={() => setPhpTuneOpen(false)}>{t('Dismiss')}</button>
      </div>}
      {renderPhpExtensions()}
      {notInstalled.length > 0 && <div className="user-create-card" style={{ marginTop: 16 }}>
        <h3>{t('Install PHP')}</h3>
        <div className="php-install-grid">
          {notInstalled.map(v => <button key={v} className="secondary" disabled={!!loading} onClick={() => installPhpVersion(v)}>+ PHP {v}</button>)}
        </div>
      </div>}
    </section>;
  }

  // Fail2ban is managed where the rest of the firewall is: its bans are
  // firewall rules. Turning it on and off is the Addons page's job.
  function renderFirewallFail2ban() {
    const installed = addons.items.find(item => item.slug === 'fail2ban')?.installed;
    const badge = !addons.loaded ? null
      : !installed ? <span className="badge">{t('Not installed')}</span>
        : !f2b ? null
          : f2b.running ? <span className="badge ok">{t('Running')}</span>
            : <span className="badge warn">{t('Stopped')}</span>;
    const bannedPages = Math.max(1, Math.ceil((f2bBanned.total || 0) / (f2bBanned.limit || 50)));
    const bannedPage = Math.floor((f2bBanned.offset || 0) / (f2bBanned.limit || 50)) + 1;
    return <section className="section firewall-fail2ban">
      <div className="section-title">
        <div><h2 className="firewall-fail2ban-title">Fail2ban {badge}</h2>
          <p className="hint">{t('Bans an address at the firewall after repeated failed logins.')}</p></div>
        <div className="actions">
          <button className="secondary" disabled={!!loading} onClick={() => { loadFail2ban(); if (installed) loadBannedPage(0); }}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
      </div>
      {addons.loaded && !installed && <div className="info-box firewall-fail2ban-missing">
        <AlertCircle size={14}/> <span>{t('Fail2ban is not installed. Install it on the Addons page to ban addresses that keep failing to sign in.')}</span>
        <button type="button" className="mini" onClick={() => navigateToPage('addons')}><PackageOpen size={13}/> {t('Open Addons')}</button>
      </div>}
      {installed && !f2b && <p className="hint">{t('Status not loaded. Press Refresh.')}</p>}
      {installed && f2b && <>
        {f2b.warning && <p className="hint addon-error"><AlertCircle size={13}/> {f2b.warning}</p>}
        {!f2b.running && <p className="hint">{t('Fail2ban is stopped: nothing is being banned.')}</p>}
        <div className="addon-panel">
          <div className="addon-panel-head">
            <strong>{t('Ban rules')}</strong>
            {(f2b.ssh_unit || f2b.banaction) && <span className="hint">{f2b.ssh_unit || '—'} · {f2b.banaction || '—'}</span>}
          </div>
          <p className="hint">{t('Five failed attempts within an hour bans an address for an hour, and longer each time it comes back, up to a week. The server never bans its own addresses.')}</p>
          <div className="chip-row">
            <span className={f2b.bans_reach_kernel ? 'badge ok' : 'badge warn'}>{f2b.bans_reach_kernel ? t('Bans take effect') : t('Bans NOT reaching iptables')}</span>
            <span className={f2b.filter_sees_journal ? 'badge ok' : 'badge warn'}>{f2b.filter_sees_journal ? t('Reading the log') : t('Seeing NO log')}</span>
            <span className="badge">{t('{n} failures seen', { n: f2b.total_failed ?? 0 })}</span>
          </div>
        </div>

        <div className="addon-panel">
          <div className="addon-panel-head">
            <strong>{t('Banned right now')} <span className="badge">{f2b.banned ?? f2bBanned.total ?? 0}</span></strong>
            <button className="secondary-light" disabled={!!loading} onClick={() => loadBannedPage(f2bBanned.offset || 0)}><RefreshCw size={13}/> {t('Refresh')}</button>
          </div>
          {(f2bBanned.items || []).length === 0
            ? <p className="hint">{t('Nothing is banned.')}</p>
            : <table className="table addon-ban-table"><thead><tr><th>{t('Address')}</th><th></th></tr></thead>
                <tbody>{f2bBanned.items.map(ip => <tr key={ip}>
                  <td><code>{ip}</code></td>
                  <td className="row-actions"><button className="secondary-light" disabled={!!loading}
                    onClick={() => unbanAddress(ip)}><Check size={13}/> {t('Unban')}</button></td>
                </tr>)}</tbody></table>}
          {bannedPages > 1 && <div className="firewall-ip-pager">
            <button className="mini secondary" disabled={!!loading || f2bBanned.offset <= 0}
              onClick={() => loadBannedPage(Math.max(0, f2bBanned.offset - f2bBanned.limit))}>{t('Previous')}</button>
            <span className="hint">{t('Page {page} of {pages} · {total} addresses', { page: bannedPage, pages: bannedPages, total: f2bBanned.total })}</span>
            <button className="mini secondary" disabled={!!loading || f2bBanned.offset + f2bBanned.limit >= f2bBanned.total}
              onClick={() => loadBannedPage(f2bBanned.offset + f2bBanned.limit)}>{t('Next')}</button>
          </div>}
        </div>
      </>}
    </section>;
  }

  // A sub-page of Firewall, like a malware scan's detail: same URL, a back
  // button. The status already carries every rule, so it is filtered and
  // paged here rather than asked for again.
  function renderFirewallAddresses() {
    const rules = (firewallStatus?.rules || []).filter(rule => !rule.protected && rule.ip);
    const counts = {
      blocked: rules.filter(rule => rule.action === 'DENY').length,
      allowed: rules.filter(rule => rule.action !== 'DENY').length,
    };
    const query = firewallIpQuery.trim().toLowerCase();
    const matching = rules.filter(rule => (!firewallIpAction || (firewallIpAction === 'deny') === (rule.action === 'DENY'))
      && (!query || `${rule.ip} ${rule.port || ''} ${rule.protocol || ''} #${rule.id}`.toLowerCase().includes(query)));
    const size = 50;
    const pages = Math.max(1, Math.ceil(matching.length / size));
    const page = Math.min(firewallIpPage, pages);
    const items = matching.slice((page - 1) * size, page * size);
    return <section className="section firewall-ip-page">
      <div className="section-title">
        <div className="waf-detail-title">
          <button className="secondary" onClick={() => setShowFirewallIpList(false)}><ArrowLeft size={14}/> {t('Firewall')}</button>
          <div><h2>{t('Blocked and allowed addresses')}</h2><p className="hint">{t('{blocked} blocked · {allowed} allowed', counts)}</p></div>
        </div>
      </div>
      <div className="firewall-ip-toolbar">
        <input value={firewallIpQuery} autoFocus aria-label={t('Search addresses')} placeholder={t('Search an IP or network')}
               onChange={e => { setFirewallIpQuery(e.target.value); setFirewallIpPage(1); }} />
        <select value={firewallIpAction} aria-label={t('Show')} onChange={e => { setFirewallIpAction(e.target.value); setFirewallIpPage(1); }}>
          <option value="">{t('All ({n})', { n: counts.blocked + counts.allowed })}</option>
          <option value="deny">{t('Blocked ({n})', { n: counts.blocked })}</option>
          <option value="allow">{t('Allowed ({n})', { n: counts.allowed })}</option>
        </select>
      </div>
      {items.length > 0 ? <ul className="firewall-ip-list">
        {items.map(rule => <li key={rule.id}>
          <span className={`badge ${rule.action === 'DENY' ? 'bad' : 'ok'}`}>{rule.action === 'DENY' ? t('Blocked') : t('Allowed')}</span>
          <code>{rule.ip}{rule.port ? ` :${rule.port}/${String(rule.protocol || 'tcp').toUpperCase()}` : ''}</code>
          <span className="firewall-ip-note">{rule.port ? '' : t('All ports')}</span>
          <small>#{rule.id}</small>
          <button className="mini secondary-light" disabled={!!loading} onClick={() => deleteFirewallRule(rule.id)}>{rule.action === 'DENY' ? t('Unblock') : t('Remove')}</button>
        </li>)}
      </ul> : <p className="hint">{!firewallStatus ? t('Loading…') : query ? t('No address matches “{query}”.', { query: firewallIpQuery.trim() }) : t('No address is blocked or allowed by a panel rule. Blocklists and Fail2ban bans are listed on their own.')}</p>}
      {pages > 1 && <div className="firewall-ip-pager">
        <button className="mini secondary" disabled={page <= 1} onClick={() => setFirewallIpPage(Math.max(1, page - 1))}>{t('Previous')}</button>
        <span className="hint">{t('Page {page} of {pages} · {total} addresses', { page, pages, total: matching.length })}</span>
        <button className="mini secondary" disabled={page >= pages} onClick={() => setFirewallIpPage(page + 1)}>{t('Next')}</button>
      </div>}
    </section>;
  }

  function renderFirewall() {
    if (!isAdmin) return <section className="section"><h2>{t('Firewall')}</h2><p className="hint">{t('No permission.')}</p></section>;
    if (showFirewallIpList) return renderFirewallAddresses();
    const firewallText = firewallStatus?.stdout || firewallStatus?.stderr || t('Click Refresh to load status.');
    const blocklistText = firewallBlocklists?.stdout || firewallBlocklists?.stderr || t('No blocklist status loaded.');
    const blocklistUrls = parseFirewallBlocklistUrls(blocklistText);
    const allRules = firewallStatus?.rules || [];
    // A port rule has no address: the ports the panel always keeps open, then
    // the ones opened here, which can be closed again from their chip.
    const openPorts = allRules.filter(rule => rule.action === 'ALLOW' && !rule.ip && rule.port);
    const ipRules = allRules.filter(rule => !rule.protected && rule.ip);
    const ipCounts = {
      blocked: ipRules.filter(rule => rule.action === 'DENY').length,
      allowed: ipRules.filter(rule => rule.action !== 'DENY').length,
    };
    // The helper prints `Status: enabled|disabled` as its first line. Read that
    // rather than pattern-matching the whole dump, which carries the word
    // "disabled" in other contexts too.
    const statusLine = (firewallText.split('\n').find(line => line.startsWith('Status:')) || '').toLowerCase();
    const enabled = statusLine.includes('enabled');
    const stateKnown = statusLine !== '';
    // "Chain active: no" is a firewall turned on whose rules are not in force
    // (UFW still in charge, or ipset missing): the dashboard and the alert
    // call that off, so the page must not call it on.
    const chainLine = (firewallText.split('\n').find(line => line.startsWith('Chain active:')) || '').toLowerCase();
    const notApplied = enabled && chainLine.includes('no');
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Firewall (iptables)')}{' '}
              {stateKnown && <span className={notApplied ? 'badge bad' : enabled ? 'badge ok' : 'badge warn'}>{notApplied ? t('On, not applied') : enabled ? t('On') : t('Off')}</span>}
            </h2>
            <p className="hint">{t('SSH, the panel port and 80/443/465/587 are always kept open.')}</p>
          </div>
          <div className="actions">
            <button className="secondary" disabled={!!loading} onClick={loadFirewall}><RefreshCw size={14}/> {t('Refresh')}</button>
            <button className="secondary" disabled={!!loading || (stateKnown && !enabled)} onClick={reloadFirewall}>{t('Reload')}</button>
            <button className="danger-light" disabled={!!loading || (stateKnown && !enabled)} onClick={disableFirewall}>{t('Disable')}</button>
            <button disabled={!!loading || (stateKnown && enabled)} onClick={enableFirewall}><Shield size={14}/> {t('Enable')}</button>
          </div>
        </div>
        {notApplied && <div className="firewall-not-applied">
          <p>{t('The firewall is turned on, but its rules are not in force: this server still filters with UFW, or iptables and ipset are missing. An update from an older release can leave it so.')}</p>
          <button disabled={!!loading} onClick={repairFirewall}><Shield size={14}/> {t('Repair the firewall')}</button>
        </div>}
        <div className="info-box firewall-open-ports">
          <strong>{t('Open ports')}</strong>
          {openPorts.length > 0 ? <div className="firewall-port-list">
            {openPorts.map(item => <span className="firewall-port-chip" key={`${item.protocol}-${item.port}-${item.zone}-${item.id}`}>
              <code>{item.port}/{String(item.protocol || 'tcp').toUpperCase()}</code>
              <small>{item.zone || 'UserZone'}</small>
              {!item.protected && <button type="button" className="firewall-port-remove" disabled={!!loading}
                title={t('Close port {port}', { port: `${item.port}/${String(item.protocol || 'tcp').toUpperCase()}` })}
                aria-label={t('Close port {port}', { port: `${item.port}/${String(item.protocol || 'tcp').toUpperCase()}` })}
                onClick={() => deleteFirewallRule(item.id)}><X size={12}/></button>}
            </span>)}
          </div> : <p className="hint">{firewallStatus ? t('No open port rules found.') : t('Loading…')}</p>}
        </div>
        <div className="firewall-ip-summary">
          <span><strong>{t('Addresses')}</strong> {t('{blocked} blocked · {allowed} allowed', ipCounts)}</span>
          <button className="secondary" disabled={!firewallStatus} onClick={() => { setFirewallIpQuery(''); setFirewallIpAction(''); setFirewallIpPage(1); setShowFirewallIpList(true); }}><Ban size={14}/> {t('View list')}</button>
        </div>
        <details className="raw-output firewall-status">
          <summary>{t('iptables status')}</summary>
          <div className="raw-output-body">
          <pre>{firewallText}</pre>
          <div className="firewall-delete-inline">
            <label><span>{t('Delete rule #')}</span><input value={firewallDeleteNumber} onChange={e => setFirewallDeleteNumber(e.target.value)} placeholder="12" inputMode="numeric" /></label>
            <button className="danger" disabled={!!loading || !firewallDeleteNumber} onClick={() => deleteFirewallRule()}>{t('Delete')}</button>
          </div>
          </div>
        </details>
      </section>
      <div className="firewall-rule-forms">
      <section className="section">
        <h2>{t('Open port')}</h2>
        <div className="firewall-form">
          <label><span>{t('Port')}</span><input value={firewallPort} onChange={e => setFirewallPort(e.target.value)} placeholder="80" inputMode="numeric" /></label>
          <label><span>{t('Protocol')}</span><select value={firewallProtocol} onChange={e => setFirewallProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label>
          <button disabled={!!loading || !firewallPort} onClick={openFirewallPort}>{t('Open port')}</button>
        </div>
      </section>
      <section className="section">
        <h2>{t('Allow IP')}</h2>
        <div className="firewall-form">
          <label><span>{t('IP / CIDR')}</span><input value={firewallAllowIp} onChange={e => setFirewallAllowIp(e.target.value)} placeholder="1.2.3.4" /></label>
          <label><span>{t('Port (optional)')}</span><input value={firewallAllowPort} onChange={e => setFirewallAllowPort(e.target.value)} placeholder="22" inputMode="numeric" /></label>
          <label><span>{t('Protocol')}</span><select value={firewallAllowProtocol} onChange={e => setFirewallAllowProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label>
          <button disabled={!!loading || !firewallAllowIp} onClick={allowFirewallIp}>{t('Allow')}</button>
        </div>
      </section>
      <section className="section">
        <h2>{t('Block IP')}</h2>
        <div className="firewall-form">
          <label><span>{t('IP / CIDR')}</span><input value={firewallBlockIp} onChange={e => setFirewallBlockIp(e.target.value)} placeholder="5.6.7.8" /></label>
          <label><span>{t('Port (optional)')}</span><input value={firewallBlockPort} onChange={e => setFirewallBlockPort(e.target.value)} placeholder={t('All ports')} inputMode="numeric" /></label>
          <label><span>{t('Protocol')}</span><select value={firewallBlockProtocol} onChange={e => setFirewallBlockProtocol(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label>
          <button className="danger" disabled={!!loading || !firewallBlockIp} onClick={blockFirewallIp}>{t('Block')}</button>
        </div>
      </section>
      </div>
      {renderFirewallFail2ban()}
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Blocklist URLs')}</h2><p className="hint">{t('TXT files are fetched daily at 01:00 and enforced by ipset, so large lists do not create thousands of firewall rules.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={loadFirewallBlocklists}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="firewall-form firewall-blocklist-form">
          <label><span>{t('TXT URL')}</span><input value={firewallBlocklistUrl} onChange={e => setFirewallBlocklistUrl(e.target.value)} placeholder="https://example.com/blocklist.txt" /></label>
          <button disabled={!!loading || !firewallBlocklistUrl.trim()} onClick={addFirewallBlocklistUrl}><Plus size={14}/> {t('Add URL')}</button>
          <button className="secondary-light" disabled={!!loading} onClick={updateFirewallBlocklistsNow}><RefreshCw size={14}/> {t('Update now')}</button>
        </div>
        {blocklistUrls.length > 0 && <div className="table firewall-blocklist-table">
          {blocklistUrls.map(url => <div className="firewall-rule" key={url}>
            <span>{url}</span>
            <div className="firewall-rule-actions"><button className="danger" disabled={!!loading} onClick={() => deleteFirewallBlocklistUrl(url)}><Trash2 size={14}/> {t('Delete')}</button></div>
          </div>)}
        </div>}
        <details className="raw-output firewall-status"><summary>{t('Blocklist status')}</summary><pre>{blocklistText}</pre></details>
      </section>
    </>;
  }

  function renderWaf() {
    // The status probe prints whether the ModSecurity module is there; that is
    // all the list needs to say. The full dump stays folded below it.
    const wafProbe = `${wafRules.status?.stdout || ''}`;
    const wafEngine = /ModSecurity module:\s*not installed/.test(wafProbe) ? 'off' : /ModSecurity module:\s*installed/.test(wafProbe) ? 'on' : 'unknown';
    const statusText = wafRules.status?.stdout || wafRules.status?.stderr || t('Click Refresh to load WAF status.');
    // The effective list, not the site's own: a site with nothing of its own
    // still enforces the global list, and reporting "No bots" for it was a lie.
    const rowFor = id => botBlocks?.websites?.find(w => w.website_id === id);
    const botCountFor = id => (rowFor(id)?.effective_blocked_bots || []).length;
    const ownCountFor = id => (rowFor(id)?.blocked_bots || []).length;
    const savedGlobalRules = wafRules.custom_rules || '';
    return <>
      {isAdmin && <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Global bad bot')} <span className="badge">{(botBlocks?.global_blocked_bots || []).length}</span></h2>
            <p className="hint">{t('One bot per line, applied to every website. A request whose User-Agent contains the text gets 403 — plain text, no regex.')}</p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={loadBotBlocks}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <textarea className="code-editor badbot-input" value={globalBotText} onChange={e => setGlobalBotText(e.target.value)}
          spellCheck={false}
          placeholder={'AhrefsBot\nSemrushBot\nMJ12bot\nGPTBot\nBytespider'} />
        {botBlocks?.max_bots ? <p className="hint">{t('Up to {n} bots.', { n: botBlocks.max_bots })}</p> : null}
        <div className="actions"><button disabled={!!loading} onClick={() => saveGlobalBots(globalBotText)}><Shield size={14}/> {t('Save and apply to all websites')}</button></div>
      </section>}

      <section className="section">
        <div className="section-title">
          <div>
            <h2>{isAdmin ? t('Websites') : t('Your websites')} {isAdmin && <span className={wafEngine === 'on' ? 'badge ok' : wafEngine === 'off' ? 'badge warn' : 'badge'}>{wafEngine === 'on' ? t('WAF engine on') : wafEngine === 'off' ? t('WAF engine off') : t('WAF engine: checking…')}</span>}</h2>
            <p className="hint">{t('Open a website to configure its rules and bad bots.')}</p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={() => { loadBotBlocks(); if (isAdmin) { loadWafRules(); loadCrs(); } }}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {websites.length === 0
          ? <EmptyState icon={Globe} message={t('No websites yet.')} />
          : <div className="waf-site-table">
              {websites.map(site => {
                const bots = botCountFor(site.id);
                // No CRS here: "WAF on" beside "CRS block" read as two things
                // to worry about. CRS is switched on the site's own page.
                return <button key={site.id} type="button" className="waf-site-row"
                  disabled={!!loading} onClick={() => openWafSite(site.id)}>
                  <span className="waf-site-domain">{site.domain}</span>
                  <span className="waf-site-badges">
                    <span className={site.waf_enabled ? 'badge ok' : 'badge'}>{site.waf_enabled ? t('WAF on') : t('WAF off')}</span>
                    <span className={site.http_flood_enabled ? 'badge ok' : 'badge'}>{site.http_flood_enabled ? t('Flood on') : t('Flood off')}</span>
                    <span className={bots > 0 ? 'badge ok' : 'badge'}
                      title={ownCountFor(site.id) > 0 ? t('{n} set on this website, the rest from the global list', { n: ownCountFor(site.id) }) : t('All from the global list')}
                    >{bots > 0 ? t('{n} bot(s)', { n: bots }) : t('No bots')}</span>
                  </span>
                  <span className="waf-site-open">{t('Configure')}</span>
                </button>;
              })}
            </div>}
        {isAdmin && <details className="raw-output firewall-status">
          <summary>{t('WAF status')}</summary>
          <pre>{statusText}</pre>
        </details>}
      </section>

      {isAdmin && <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('OWASP Core Rule Set')}{' '}
              {crs && <span className={crs.mode === 'block' ? 'badge ok' : 'badge'}>
                {crs.mode === 'off' ? t('Off') : (crs.mode === 'detect' ? t('Detect only') : t('Blocking'))}
              </span>}
            </h2>
            <p className="hint">{t('Inspects each request for SQL injection, XSS and similar attacks. Each website turns it on from its own page.')}</p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={loadCrs}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {!crs && <p className="hint">{t('Click Refresh to load status.')}</p>}
        {crs && <>
          <div className="chip-row">
            <span className={crs.installed ? 'badge ok' : 'badge'}>
              {crs.installed ? t('{n} rule file(s) installed', { n: crs.rule_files }) : t('Not installed')}
            </span>
            <span className="badge">{t('{n} website(s) with CRS on', { n: crs.sites_opted_in ?? 0 })}</span>
            {/* Every site that turns CRS on carries it (~50 MB), so a box
                short of memory is worth saying out loud. */}
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
          <p className="hint">
            {crs.mode === 'off' && t('Off: requests are not inspected.')}
            {crs.mode === 'detect' && t('Detect only: attacks are logged, nothing is blocked.')}
            {crs.mode === 'block' && t('Block: attacks are refused on websites with CRS on.')}
          </p>
          {crs.mode !== 'off' && crs.panel_mode !== crs.mode && (
            <p className="hint">{t('Panel setting says "{panel}" but the server reports "{server}".', { panel: crs.panel_mode, server: crs.mode })}</p>
          )}
        </>}
      </section>}

      {isAdmin && <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Global custom rules')}</h2>
            <p className="hint">{t('ModSecurity rules for every website with the WAF on. Rules an AI assistant added are marked # bpanel-mcp; delete a rule by deleting its lines.')}</p>
          </div>
          <span className="badge">{t('{n} rule(s)', { n: (wafGlobalRules.match(/^\s*SecRule/gm) || []).length })}</span>
        </div>
        <textarea className="code-editor" rows={12} spellCheck={false} value={wafGlobalRules} onChange={e => setWafGlobalRules(e.target.value)} placeholder={'SecRule ...'} />
        <div className="actions">
          <button type="button" disabled={!!loading || wafGlobalRules === savedGlobalRules} onClick={saveWafGlobalRules}>{t('Save')}</button>
          <button type="button" className="secondary-light" disabled={!!loading || wafGlobalRules === savedGlobalRules} onClick={() => setWafGlobalRules(savedGlobalRules)}>{t('Reset')}</button>
        </div>
      </section>}
    </>;
  }

  // Its own route (/waf-site), so a reload or a shared link comes back to the
  // same website; drawn as OPanel draws its in-page site view, the way back
  // first.
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
    const globalBotCount = (wafSiteConfig?.global_blocked_bots || botBlocks?.global_blocked_bots || []).length;
    // Custom rules are arbitrary ModSecurity directives: the server says
    // whether this account may write them.
    const mayEditCustomRules = wafSiteConfig?.may_edit_custom_rules !== false;
    return <>
      <section className="section">
        <div className="section-title waf-detail-head">
          <div className="waf-detail-title">
            <button className="secondary-light" onClick={() => navigateToPage('waf')}><ArrowLeft size={14}/> {t('All websites')}</button>
            <div><h2>{wafSiteConfig?.domain || selectedSite?.domain || t('Website')}</h2><p className="hint">{t('WAF configuration for this website.')}</p></div>
          </div>
          <div className="waf-detail-actions">
            <span className={selectedSite?.waf_enabled ? 'badge ok' : 'badge'}>{selectedSite?.waf_enabled ? t('WAF on') : t('WAF off')}</span>
            <button disabled={!selectedWafWebsiteId || !!loading} onClick={() => selectedSite && toggleWebsiteWaf(selectedSite)}>
              <Shield size={14}/> {selectedSite?.waf_enabled ? t('Disable WAF') : t('Enable WAF')}
            </button>
          </div>
        </div>
      </section>

      {!wafSiteConfig && websites.length === 0 && <section className="section"><EmptyState icon={Globe} message={t('No websites yet.')} /></section>}

      {wafSiteConfig && <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Bad bot')}</h2>
            <p className="hint">{t('Global list ({n}) plus anything below.', { n: globalBotCount })}</p>
          </div>
        </div>
        <label className="badbot-site-extra"><span>{t('Extra bots, this website only')}</span>
          <textarea className="code-editor badbot-input" value={siteBotText} onChange={e => setSiteBotText(e.target.value)}
            spellCheck={false} placeholder={'ScrapyBot\nSomeOtherBot'} />
        </label>
        <p className="hint">
          {t('{n} bot(s)', { n: siteBotUnique.size })}
          {siteBotNames.length !== siteBotUnique.size ? ' ' + t('({n} duplicate(s) will be dropped)', { n: siteBotNames.length - siteBotUnique.size }) : ''}
          {botBlocks?.max_bots ? ' · ' + t('Up to {n} bots.', { n: botBlocks.max_bots }) : ''}
        </p>
        <div className="actions">
          <button disabled={!!loading} onClick={saveSiteBots}><Shield size={14}/> {t('Save bad bot config')}</button>
          <button className="secondary-light" disabled={!!loading || siteBotNames.length === 0} onClick={() => setSiteBotText('')}>{t('Clear list')}</button>
        </div>
      </section>}

      {wafSiteConfig && <section className="section">
        <div className="section-title">
          <h2>{t('HTTP Flood')}</h2>
          <span className={httpFloodForm.http_flood_enabled ? 'badge ok' : 'badge'}>{httpFloodForm.http_flood_enabled ? t('On') : t('Off')}</span>
        </div>
        <label className="check-line">
          <input type="checkbox" checked={!!httpFloodForm.http_flood_enabled}
            onChange={e => setHttpFloodForm(prev => ({ ...prev, http_flood_enabled: e.target.checked }))} />
          {t('Enabled')}
        </label>
        <div className="firewall-form addon-form">
          <label><span>{t('Requests')}</span><input type="number" min="1" max="100000" value={httpFloodForm.access_limit_requests} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_requests: e.target.value }))} /></label>
          <label><span>{t('Window (sec)')}</span><input type="number" min="1" max="3600" value={httpFloodForm.access_limit_window} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_window: e.target.value }))} /></label>
          <label><span>{t('Burst')}</span><input type="number" min="0" max="100000" value={httpFloodForm.access_limit_burst} onChange={e => setHttpFloodForm(prev => ({ ...prev, access_limit_burst: e.target.value }))} /></label>
          <label><span>{t('Connections/IP')}</span><input type="number" min="1" max="10000" value={httpFloodForm.connection_limit} onChange={e => setHttpFloodForm(prev => ({ ...prev, connection_limit: e.target.value }))} /></label>
        </div>
        <div className="actions"><button disabled={!!loading} onClick={saveWebsiteHttpFlood}><Shield size={14}/> {t('Save HTTP Flood')}</button></div>
      </section>}

      {wafSiteConfig && <section className="section">
        <div className="section-title">
          <div>
            <h2>OWASP CRS</h2>
            <p className="hint">
              {t('Inspects each request for SQL injection, XSS and similar attacks. Uses about {n} MB of server RAM.', { n: crs?.rss_mb_per_site || 50 })}
              {wafSiteConfig.crs_enabled && !selectedSite?.waf_enabled ? ' ' + t('It loads when the WAF is on.') : ''}
              {wafSiteConfig.crs_enabled && selectedSite?.waf_enabled && wafSiteConfig.crs_mode === 'off' ? ' ' + t('CRS is off for the whole server, so nothing is loaded yet.') : ''}
              {wafSiteConfig?.crs_active && wafSiteConfig.crs_mode === 'detect' ? ' ' + t('Detect only: attacks are logged, nothing is blocked.') : ''}
              {wafSiteConfig?.crs_active && mayEditCustomRules ? ' ' + t('Add SecRuleRemoveById <id> to the custom rules below to excuse this site from one rule.') : ''}
            </p>
          </div>
          <span className={wafSiteConfig?.crs_active ? 'badge ok' : 'badge'}>{wafSiteConfig.crs_enabled ? t('CRS on') : t('CRS off')}</span>
        </div>
        <div className="actions">
          <button
            className={wafSiteConfig.crs_enabled ? 'secondary' : ''}
            disabled={!!loading || (!wafSiteConfig.crs_enabled && !selectedSite?.waf_enabled)}
            title={!wafSiteConfig.crs_enabled && !selectedSite?.waf_enabled ? t('Turn the WAF on first') : ''}
            onClick={() => toggleSiteCrs(wafSiteConfig)}
          ><Shield size={14}/> {wafSiteConfig.crs_enabled ? t('Turn CRS off') : t('Turn CRS on')}</button>
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
          {mayEditCustomRules
            ? <>
                <textarea className="code-editor" value={wafCustomRules} onChange={e => setWafCustomRules(e.target.value)} rows={14} spellCheck={false} placeholder="SecRule ..." />
                <p className="hint">{t('Saved into')} {wafSiteConfig.rules_file}</p>
              </>
            : <>
                {wafCustomRules
                  ? <pre className="code-editor waf-custom-readonly">{wafCustomRules}</pre>
                  : <p className="hint">{t('No custom rules on this website.')}</p>}
                <p className="hint">{t('Custom rules are written by an administrator. Everything else on this page is yours to change.')}</p>
              </>}
          <div className="actions"><button disabled={!!loading} onClick={saveWebsiteWafRules}>{t('Save website WAF rules')}</button></div>
        </div>
      </section>}
    </>;
  }

  function renderWafAccessLogs() {
    const rows = wafAccessLogs.items || [];
    const total = Number(wafAccessLogs.total || 0);
    const entryCount = total >= 1000 ? `${(total / 1000).toFixed(1)}k` : String(total);
    return <>
      <section className="access-log-hero">
        <div>
          <p className="eyebrow">{t('Protected Traffic')}</p>
          <h1>{t('Access Logs')}</h1>
        </div>
        <div className="access-log-hero-actions">
          <button className="secondary-light icon-only" onClick={() => loadWafAccessLogs(wafAccessLogFilters, true)} disabled={!!loading} aria-label={t('Refresh logs')} title={t('Refresh logs')}><RefreshCw size={16}/></button>
          <button className="secondary-light icon-only" onClick={() => navigateToPage('waf')} aria-label={t('Open WAF settings')} title={t('Open WAF settings')}><ExternalLink size={16}/></button>
        </div>
      </section>
      <section className="section access-log-section">
        <div className="access-log-toolbar">
          <div className="access-log-title">
            <strong>{t('Access Logs')}</strong>
            <span>{entryCount} {t('entries')}</span>
            <button className="secondary-light" onClick={exportWafAccessLogs} disabled={!rows.length}><Download size={14}/> {t('Export')}</button>
            <button className="danger-light" onClick={clearWafAccessLogs} disabled={!!loading || websites.length === 0}><Trash2 size={14}/> {t('Clear')}</button>
          </div>
          <div className="access-log-filters">
            <select value={wafAccessLogFilters.websiteId} onChange={e => updateWafAccessLogFilters({ websiteId: e.target.value }, true)}>
              <option value="">{t('All websites')}</option>
              {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
            </select>
            <select value={wafAccessLogFilters.verdict} onChange={e => updateWafAccessLogFilters({ verdict: e.target.value }, true)}>
              <option value="all">{t('All verdicts')}</option>
              <option value="block">{t('Block')}</option>
              <option value="allow">{t('Allow')}</option>
              <option value="error">{t('Error')}</option>
            </select>
            {/* The search runs on Enter: every request reads the logs afresh. */}
            <input value={wafAccessLogFilters.query} onChange={e => updateWafAccessLogFilters({ query: e.target.value })} onKeyDown={e => { if (e.key === 'Enter') applyWafAccessLogFilters(); }} placeholder={t('Filter logs')} />
            <select value={wafAccessLogFilters.limit} onChange={e => updateWafAccessLogFilters({ limit: Number(e.target.value) }, true)}>
              {[50, 100, 200, 500].map(size => <option key={size} value={size}>{size} {t('/ page')}</option>)}
            </select>
            <select value={wafAccessLogFilters.refresh} onChange={e => updateWafAccessLogFilters({ refresh: Number(e.target.value) })} title={t('Auto refresh')}>
              <option value={0}>{t('Auto refresh off')}</option>
              <option value={5}>{t('Refresh 5s')}</option>
              <option value={10}>{t('Refresh 10s')}</option>
              <option value={30}>{t('Refresh 30s')}</option>
            </select>
          </div>
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
                <th>{t('Reason')}</th>
                <th>{t('Status')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(item => <tr key={item.id}>
                <td><span className={`verdict-pill ${item.verdict === 'allow' ? 'allow' : item.verdict === 'error' ? 'error' : 'block'}`}>{t(accessLogVerdictLabel(item.verdict))}</span></td>
                <td><span>{formatAccessLogTime(item.timestamp) || '-'}</span><small>{item.duration_ms || 0} ms</small></td>
                <td><span>{item.domain}</span></td>
                <td>{item.method || '-'}</td>
                <td><span className="access-log-path">{item.path || '-'}</span></td>
                <td><span>{item.ip || '-'}</span><small>{accessLogCountryLabel(item) === '-' ? '' : accessLogCountryLabel(item)}</small></td>
                <td>{item.reason || (item.verdict === 'block' ? t('Blocked') : item.verdict === 'error' ? t('Error') : t('Allowed'))}</td>
                <td>{item.status || '-'}</td>
              </tr>)}
            </tbody>
          </table>
          {rows.length === 0 && <EmptyState icon={Shield} message={t('No access log entries match the current filters.')} />}
        </div>
        {(wafAccessLogs.missing || []).length > 0 && <div className="access-log-footer">
          <span>{t('Missing log files:')} {wafAccessLogs.missing.join(', ')}</span>
        </div>}
      </section>
    </>;
  }

  function renderUpdates() {
    if (!isAdmin) return <section className="section"><h2>{t('Updates')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const statusText = updatesStatus?.stdout || updatesStatus?.stderr || t('Click View logs to load update logs.');
    const panelUpdate = updatesStatus?.panel || {};
    // Three states, not two. `update_available` is null when the release check
    // could not tell, and "unknown" must not be dressed up as "up to date".
    const hasUpdate = panelUpdate.update_available;
    const panelBadge = hasUpdate === true ? t('Update available')
      : hasUpdate === false ? t('Up to date') : t('Unknown');
    const panelBadgeClass = hasUpdate === true ? 'badge warn'
      : hasUpdate === false ? 'badge ok' : 'badge';
    const currentPanelVersion = panelUpdate.current_version || appVersion || '';
    const latestPanelVersion = panelUpdate.latest_version || '';
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Updates')}</h2><p className="hint">{t('OS packages use apt; panel updates use')} <code>bpanel-update</code>.</p></div>
          <button className="secondary-light" disabled={!!loading} onClick={toggleUpdateLog}>{showUpdateLog ? <X size={14}/> : <FileText size={14}/>} {showUpdateLog ? t('Hide logs') : t('View logs')}</button>
        </div>
        <div className="info-box update-version-box">
          <div className="update-version-head"><strong>{t('Panel release')}</strong><span className={panelBadgeClass}>{panelBadge}</span></div>
          <div className="update-version-grid">
            <span>{t('Current')} <strong>{currentPanelVersion ? `v${currentPanelVersion}` : t('unknown')}</strong></span>
            <span>{t('Latest')} <strong>{latestPanelVersion ? `v${latestPanelVersion}` : t('unknown')}</strong></span>
            <span>{t('Checked')} <strong>{panelUpdate.last_checked_at || t('never')}</strong></span>
            <span>{t('State file')} <strong>{panelUpdate.state_file || '/var/lib/bpanel/update-status.json'}</strong></span>
          </div>
          {panelUpdate.check_error && <p className="hint">{t('Release check failed:')} {panelUpdate.check_error}</p>}
          {panelUpdate.last_update_status && <p className="hint">{t('Last update:')} {panelUpdate.last_update_status}{panelUpdate.last_update_ref ? ` (${panelUpdate.last_update_ref})` : ''}{panelUpdate.last_update_finished_at ? t(' at {when}', { when: panelUpdate.last_update_finished_at }) : ''}</p>}
        </div>
        <div className="actions">
          <button className="secondary-light" disabled={!!loading} onClick={() => loadUpdates(true)}><RefreshCw size={14}/> {t('Refresh status')}</button>
          <button className="secondary" disabled={!!loading || osUpdating} onClick={runOsUpdate}><RefreshCw size={14} className={osUpdating ? 'spin' : ''}/> {osUpdating ? t('Updating OS...') : t('Update OS now')}</button>
          {/* Releases, not a branch: until a newer one is out there is nothing to install. */}
          <button disabled={!!loading || panelUpdating || hasUpdate !== true} onClick={runPanelUpdate}><RotateCcw size={14} className={panelUpdating ? 'spin' : ''}/> {panelUpdating ? t('Updating panel...') : t('Update panel now')}</button>
        </div>
        {showUpdateLog && <div className="info-box firewall-status update-log-box">
          <div className="update-log-head"><strong>{t('Update logs')}</strong><button className="secondary-light" disabled={!!loading} onClick={() => loadUpdates(true)}><RefreshCw size={13}/> {t('Refresh')}</button></div>
          <pre>{statusText}</pre>
        </div>}
        {/* Number(...) > 0, not the bare value: a progress of 0 made this
            whole expression 0, and React printed a stray "0" under the buttons. */}
        {(panelUpdating || (Number(panelUpdate.progress_percent) > 0 && panelUpdate.last_update_status && panelUpdate.last_update_status !== 'completed' && panelUpdate.last_update_status !== 'failed')) && (
          <div className="info-box firewall-status update-progress-box">
            <div className="update-progress-row">
              <span className={panelUpdate.last_update_status === 'failed' ? 'badge bad' : 'badge ok'}>
                {panelUpdating ? t('Running') : (panelUpdate.last_update_status === 'failed' ? t('Failed') : (panelUpdate.last_update_status || t('Idle')))}
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
    const pk = passkeyStatus || {};
    const keys = pk.credentials || [];
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Passkey')}</h2>
            <p className="hint">
              {keys.length
                ? <>{t('Tried first when you sign in.')} <strong>{keys.length}</strong> {t('registered')}
                    {enabled ? t(', with your authenticator code as the fallback.') : '.'}</>
                : t('Sign in with a fingerprint, face, screen lock, or security key.')}
            </p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={loadPasskeyStatus}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {passkeyStatus && !pk.supported && <p className="hint">
          {t('You are reaching the panel by IP address ({host}). Browsers only create passkeys for domain names, so open the panel by its domain and add one there.', { host: pk.hostname })}
        </p>}
        {pk.supported && <p className="hint">{t('A passkey is tied to the domain')} <strong>{pk.rp_id}</strong>.{' '}
          {t('Reach the panel by any other name and it will not be offered — use Google Authenticator below for that.')}
        </p>}
        {keys.length > 0 && <div className="table">
          {keys.map(item => <div className="row passkey-row" key={item.id}>
            <span>
              <strong>{item.name}</strong>{' '}
              <span className={item.usable_here ? 'badge ok' : 'badge'}>{item.usable_here ? t('Works here') : t('Another domain')}</span>
              <small className="db-owner">
                {item.rp_id} · {t('Added')} {item.created_at ? new Date(item.created_at).toLocaleDateString() : t('recently')}
                {item.last_used_at ? t(' · last used {date}', { date: new Date(item.last_used_at).toLocaleDateString() }) : t(' · not used yet')}
              </small>
            </span>
            <button className="mini danger" disabled={!!loading}
                    title={t('Remove this passkey')} aria-label={t('Remove the passkey {name}', { name: item.name })}
                    onClick={() => removePasskey(item)}><Trash2 size={14}/></button>
          </div>)}
        </div>}
        {pk.supported && <>
          <div className="passkey-add">
            <NoAutofillInput
              name="passkey-name"
              value={passkeyName}
              onChange={e => setPasskeyName(e.target.value)}
              placeholder={t('Name this passkey (e.g. Work laptop)')}
              aria-label={t('Passkey name')}
              maxLength={64}
            />
            <input
              type="password"
              value={passkeyPassword}
              onChange={e => setPasskeyPassword(e.target.value)}
              placeholder={t('Current password')}
              autoComplete="current-password"
              aria-label={t('Current password')}
            />
            <button disabled={!!loading || !passkeyPassword} onClick={addPasskey}><Shield size={14}/> {t('Add passkey')}</button>
          </div>
          <p className="hint">{t('Your current password confirms it is you, the same as when turning on Google Authenticator.')}</p>
        </>}
        {keys.length > 0 && !enabled &&
          <p className="hint">{t('A passkey is your only second factor. Reach the panel by a different domain and there is no second factor at all — turn on Google Authenticator below as well.')}</p>}
      </section>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Google Authenticator 2FA')}</h2><p className="hint">{t('Current status:')} <strong>{enabled ? t('Enabled') : t('Disabled')}</strong></p></div>
          <button className="secondary" disabled={!!loading} onClick={loadTwoFactorStatus}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {!enabled && keys.length > 0 && <p className="hint">{t('Used when a passkey is not available on the device you are signing in from.')}</p>}
        {!enabled && <div className="security-grid">
          <div className="info-box">
            <strong>{t('Setup')}</strong>
            {twoFactorSetup?.qr_data_url ? <img className="qr-code" src={twoFactorSetup.qr_data_url} alt={t('2FA QR code')} /> : <p className="hint">{t('No setup code generated.')}</p>}
            {twoFactorSetup?.secret && <code className="secret-text">{twoFactorSetup.secret}</code>}
            <div className="actions">
              <button disabled={!!loading} onClick={setupTwoFactorAuth}><Shield size={14}/> {t('Generate QR')}</button>
            </div>
          </div>
          <div className="info-box">
            <strong>{t('Verify')}</strong>
            <input value={twoFactorCode} onChange={e => setTwoFactorCode(e.target.value)} placeholder="123456" inputMode="numeric" />
            <button disabled={!!loading || !twoFactorSetup || !twoFactorCode} onClick={enableTwoFactorAuth}><Lock size={14}/> {t('Enable 2FA')}</button>
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
      ? t('Full server (/)')
      : (job.domains && job.domains.length > 0)
        ? (job.domains.length === 1 ? job.domains[0] : t('{count} websites', { count: job.domains.length }))
        : (job.scope === 'all' ? t('All websites') : t('Scan job'));
    const scanJobStamp = job => {
      const stamp = job.finished_at || job.updated_at || job.started_at || job.created_at || '';
      if (!stamp) return t('No timestamp');
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
    // A /home scan is 180,000 files or more, so a whole percent takes a minute
    // or two to tick over and the figure looked stuck. While a scan runs it is
    // worked out from the counts, with a decimal below 10%.
    const scanPercent = job => {
      const total = Number(job.total_files) || 0;
      if (job.status !== 'running' || !total) return String(Number(job.progress_percent) || 0);
      const exact = Math.min(99, (Number(job.scanned) || 0) * 100 / total);
      return exact > 0 && exact < 10 ? exact.toFixed(1) : String(Math.floor(exact));
    };
    // The scanner's stage messages are fixed sentences in the dictionary; one
    // that is not (an older job's) shows as it was written.
    const renderThreats = job => <>
      <p className="hint">{t('These are the scanner\'s own family names (php.base64..., for instance), not common virus names — there is nowhere else to look them up.')}</p>
      <div className="scan-threat-list">
        {job.threats.map((threat, i) => <div key={i} className="scan-threat-item">
          <strong>{threat.signature}</strong>
          <span>{threat.domain ? `${threat.domain}: ` : ''}{threat.path}</span>
        </div>)}
      </div>
    </>;

    // A run from the history, as a page of its own inside this one.
    if (malwareDetailJob) {
      const job = malwareDetailJob;
      const started = job.started_at ? new Date(job.started_at) : null;
      const finished = job.finished_at ? new Date(job.finished_at) : null;
      const seconds = started && finished ? Math.max(0, Math.round((finished - started) / 1000)) : null;
      const duration = seconds == null ? '—' : seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m` : seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
      return <section className="section scan-detail">
        <div className="section-title">
          <div className="waf-detail-title">
            <button className="secondary" onClick={() => setMalwareDetailJob(null)}><ArrowLeft size={14}/> {t('Malware scanner')}</button>
            <div><h2>{scanJobTitle(job)}</h2><p className="hint">{scanJobStamp(job)}</p></div>
          </div>
          <span className={scanJobBadgeClass(job)}>{scanStatusLabel(job.status)}</span>
        </div>
        <div className="scan-detail-stats">
          <div><small>{t('Files scanned')}</small><strong>{job.scanned || 0}{job.total_files ? ` / ${job.total_files}` : ''}</strong></div>
          <div><small>{t('Threats found')}</small><strong className={job.infected > 0 ? 'text-danger' : ''}>{job.infected || 0}</strong></div>
          <div><small>{t('Errors')}</small><strong>{job.errors || 0}</strong></div>
          <div><small>{t('Duration')}</small><strong>{duration}</strong></div>
        </div>
        {job.message && <p className="hint">{t(job.message)}</p>}
        {job.error && <p className="hint" style={{ color: 'var(--danger)' }}>{job.error}</p>}
        <h3>{t('Threats')}</h3>
        {job.threats && job.threats.length > 0
          ? renderThreats(job)
          : <div className="quarantine-empty"><CheckCircle size={16}/> {t('No threats in this scan.')}</div>}
        {job.log && job.log.length > 0 && <details className="raw-output" open={job.infected > 0 || job.status === 'error'}>
          <summary>{t('Scan log')}</summary>
          <pre className="malware-scan-log">{job.log.join('\n')}</pre>
        </details>}
      </section>;
    }

    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('Malware Scanner')}</h2>
            <p className="hint badge-row">
              {mwActive ? <span className="badge ok">{t('Active')}</span>
                : mwEnabled && !mwInstalled ? <span className="badge warn">{t('Installing...')}</span>
                : mwInstalled && !mwEnabled ? <span className="badge">{t('Installed — scanning disabled')}</span>
                : <span className="badge">{t('Not installed')}</span>}
              {mwInstalled && <span className="badge">{t('Engine:')} {mw.engine === 'lmd+clamav' ? 'LMD + ClamAV' : mw.engine === 'clamav' ? 'ClamAV' : mw.engine}</span>}
              {mwInstalled && mw.signature_filter === 'on' && mw.signatures_total > 0 && <span className="badge" title={t('clam-juice keeps the signatures a Linux web server needs and drops Windows, macOS and Office malware, so a scan loads far less into memory.')}>{t('Signatures: {kept} of {total} (clam-juice)', { kept: Number(mw.signatures_kept).toLocaleString(), total: Number(mw.signatures_total).toLocaleString() })}</span>}
              {mwInstalled && mw.signature_filter === 'pending' && <span className="badge">{t('Filtering signatures...')}</span>}
              {mwInstalled && mw.signature_filter === 'failed' && <span className="badge warn">{t('Signature filter failed: full databases in use')}</span>}
              {mw.realtime_enabled && <span className={mw.monitor_running ? 'badge ok' : 'badge warn'}>
                {t(mw.monitor_running ? 'Level 2 running' : 'Level 2 not running')}
              </span>}
            </p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={loadMalwareScanStatus}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {mw.memory_warning && <div className="info-box malware-ram-warning">
          <strong><AlertCircle size={15}/>{t('Memory warning')}</strong>
          <p className="hint">{mw.memory_warning}</p>
        </div>}
        <div className="info-box">
          <p className="hint">{mw.detail ? t(mw.detail) : t('Checking status...')}</p>
          {mw.memory_total_mb > 0 && <p className="hint">{t('Server memory:')}{' '}<strong>{mw.memory_total_mb} MB</strong> {t('({n} MB free)', { n: mw.memory_available_mb })}</p>}
          {mw.lmd_installed && <p className="hint">{t('Malware signatures:')}{' '}<strong>{mw.lmd_sig_version || '—'}</strong>{mw.lmd_updated_at ? ` (updated ${mw.lmd_updated_at})` : ''}</p>}
          {mwEnabled
            ? <p className="hint" style={{marginTop:8}}>{t('To turn the scanner off, remove the Malware Scanner addon on the Addons page. The history and the settings are kept.')}</p>
            : <p className="hint" style={{marginTop:8}}>{t('The Malware Scanner is an addon. Install or start it on the Addons page; stopping or removing it there frees the memory ClamAV uses.')}</p>}
          <div className="actions" style={{marginTop:12}}>
            {!mwEnabled && <button disabled={!!loading} onClick={() => navigateToPage('addons')}><PackageOpen size={14}/> {t('Open Addons')}</button>}
            {mw.lmd_installed && <button className="secondary" disabled={!!loading} onClick={updateMalwareSignatures}><RefreshCw size={14}/> {t('Update signatures')}</button>}
          </div>
        </div>

        {!mw.lmd_installed && <div className="info-box">
          <div className="malware-scan-head">
            <div>
              <strong>{t('Linux Malware Detect')} <span className="badge">{t('Not installed')}</span></strong>
              <p className="hint">{mwEnabled && !mwInstalled
                ? t('LMD and ClamAV are installing (1-3 minutes). Press Refresh to see when they are ready.')
                : t('This server has no Linux Malware Detect yet. Install it for its web-focused signatures (PHP shells, injected malware ClamAV misses) and the incremental /home scan.')}</p>
            </div>
            <button disabled={!!loading} onClick={installLmd}><Shield size={14}/> {t('Install the scanner')}</button>
          </div>
        </div>}

        {mwInstalled && <div className="info-box">
          <div className="malware-scan-head">
            <div>
              <strong>{t('Level 2 — Real-time protection')} {mw.realtime_enabled && !mw.monitor_running
                ? <span className="badge danger">{t('Not running')}</span>
                : <span className={mw.realtime_enabled ? 'badge ok' : 'badge'}>{mw.realtime_enabled ? t('On') : t('Off')}</span>}</strong>
              <p className="hint">{t('Watches the website directories continuously and checks new files in short batches (~15 seconds). Catches something arriving over SFTP or through a plugin at once, instead of waiting for the next Level 1 scheduled scan.')}</p>
            </div>
            {mw.realtime_enabled
              ? <button className="danger" disabled={!!loading} onClick={() => toggleMalwareRealtime(false)}>{t('Turn off')}</button>
              : <button disabled={!!loading} onClick={() => toggleMalwareRealtime(true)}><Shield size={14}/> {t('Turn on')}</button>}
          </div>
        </div>}

        {mwInstalled && <div className="info-box">
          <div className="malware-scan-head">
            <div>
              <strong>{t('Scan uploaded files')} <span className={mw.scan_on_upload ? 'badge ok' : 'badge'}>{mw.scan_on_upload ? t('On') : t('Off')}</span></strong>
              <p className="hint">{t('Scans each file uploaded through the file manager, in the background after the upload finishes, so nobody waits on it. Off by default: without a resident clamd, every file reloads the whole signature database (measured at 28 seconds and over 1 GB of RAM for a 20 MB file). The Level 1 scheduled scan covers these files either way.')}</p>
              {mw.signature_filter === 'on' && !mw.clamd_running && <p className="hint">{t('With the filtered signatures a scan loads in about 2 seconds and 200 MB.')}</p>}
              {!mw.scan_on_upload_is_cheap && <p className="hint">{t('This server has no resident clamd — start one first and each scan drops to milliseconds.')}</p>}
            </div>
            {mw.scan_on_upload
              ? <button className="danger" disabled={!!loading} onClick={() => toggleMalwareScanOnUpload(false)}>{t('Turn off')}</button>
              : <button disabled={!!loading} onClick={() => toggleMalwareScanOnUpload(true)}><Shield size={14}/> {t('Turn on')}</button>}
          </div>
        </div>}

        {mwInstalled && <div className="info-box malware-scan-panel">
          <div className="malware-scan-runner">
            <div className="malware-scan-head">
              <div>
                <strong>{t('Run a scan now')}</strong>
                <p className="hint">{t('Scan the website directories (fast), the whole server, or incrementally (only recently changed files — run by hand when you want it, never on the schedule).')}</p>
              </div>
              <button className="secondary" disabled={!!loading} onClick={loadMalwareScanJobs}><RefreshCw size={14}/> {t('History')}</button>
            </div>
            <div className="malware-scan-controls">
              <select value={scanTargetWebsiteId} onChange={e => { setScanTargetWebsiteId(e.target.value); setScanResults(null); setScanJob(null); }}>
                <option value="">{t('-- Select target --')}</option>
                <option value="all">{t('All websites (/home)')}</option>
                <option value="incremental">{t('Incremental scan')}</option>
                <option value="server">{t('Full server (/)')}</option>
                {websites.map(w => <option key={w.id} value={w.id}>{w.domain}</option>)}
              </select>
              {scanTargetWebsiteId === 'incremental' && <select value={incrementalDays} onChange={e => setIncrementalDays(Number(e.target.value))}>
                {[1, 2, 3, 7, 14].map(d => <option key={d} value={d}>{t('{n} days', { n: d })}</option>)}
              </select>}
              <button disabled={!!loading || scanRunning || !scanTargetWebsiteId} onClick={runMalwareScan}>
                {scanRunning || scanLoading ? <><RefreshCw size={14} className="spin"/> {t('Scanning...')}</> : <><Search size={14}/> {t('Scan Now')}</>}
              </button>
            </div>
          </div>
          {scanJobs.length > 0 && <div className="scan-history-wrap">
            <div className="scan-history-head">
              <strong>{t('Scan history')}</strong>
              <span>{scanJobs.length} {t('saved')}</span>
            </div>
            <div className="scan-history-list">
              {scanJobs.slice(0, 8).map(job => <button
                key={job.job_id}
                className={`scan-history-item ${job.status}${activeScanJob.job_id === job.job_id ? ' active' : ''}`}
                onClick={() => openMalwareScanDetail(job)}
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
              read from the history above. */}
          {(scanRunning || scanLoading) && (scanJob || scanResults) && <div className="scan-status-panel">
            <div className="progress-bar">
              <div className="progress-bar-fill" style={{width: `${scanPercent(activeScanJob)}%`}} />
            </div>
            <div className="scan-status-summary">
              <span><strong>{t('Progress')}</strong>{scanPercent(activeScanJob)}%</span>
              <span><strong>{t('Files scanned')}</strong>{activeScanJob.scanned || 0}/{activeScanJob.total_files || activeScanJob.scanned || 0}</span>
              <span><strong>{t('Threats found')}</strong>{activeScanJob.infected > 0
                ? <span className="badge danger">{activeScanJob.infected}</span>
                : <span className="badge ok">0</span>}
              </span>
              <span><strong>{t('Errors')}</strong>{activeScanJob.errors || 0}</span>
            </div>
            {activeScanJob.message && <p className="hint">{t(activeScanJob.message)}</p>}
            {activeScanJob.threats && activeScanJob.threats.length > 0 && renderThreats(activeScanJob)}
            {activeScanJob.log && activeScanJob.log.length > 0 && <pre className="malware-scan-log">{activeScanJob.log.join('\n')}</pre>}
          </div>}
        </div>}
      </section>

      {/* Weekly, and shown in Vietnam time: the API holds weekday and hour in
          UTC, and utcScheduleToVn / vnScheduleToUtc convert at the form. */}
      {mwEnabled && [
        {
          scope: 'server',
          title: t('Full server scan'),
          root: '/',
          intro: t('Walks the whole VPS as root, so malware parked in /tmp, /root or a home folder outside public_html is found too. Heavier than a website scan and hungry for memory: best run weekly, at a quiet hour.'),
        },
        {
          scope: 'websites',
          title: t('Website scan (/home)'),
          root: '/home',
          intro: t('Scans every website’s files under /home. Each run is a full scan; the incremental scan of recently changed files is run by hand above.'),
        },
      ].map(({ scope, title, root, intro }) => {
        const form = malwareSchedulesForm[scope] || {};
        const saved = malwareSchedules[scope] || {};
        // form.weekday/hour are UTC on the wire; show and edit them as VN time.
        const vn = utcScheduleToVn(form.weekday ?? 6, form.hour ?? 3);
        const setField = patch => setMalwareSchedulesForm(prev => ({ ...prev, [scope]: { ...prev[scope], ...patch } }));
        const setVn = patch => setField(vnScheduleToUtc(patch.weekday ?? vn.weekday, patch.hour ?? vn.hour));
        return <section className="section" key={scope}>
          <div className="section-title">
            <div>
              <h2>{title}</h2>
              <p className="hint">{intro}</p>
            </div>
            <button className="secondary" disabled={!!loading} onClick={loadMalwareSchedule}><RefreshCw size={14}/> {t('Refresh')}</button>
          </div>
          <div className="info-box">
            <strong>{t('Scheduled scan')} <code>{root}</code></strong>
            <p className="hint">{t('The panel scans on its own, with nobody pressing anything. Pick an hour when few visitors are around.')}</p>
            <div className="scan-schedule-form">
              <label><span>{t('Enabled')}</span>
                <select value={form.enabled ? 'on' : 'off'} onChange={e => setField({ enabled: e.target.value === 'on' })}>
                  <option value="off">{t('Off')}</option>
                  <option value="on">{t('On')}</option>
                </select>
              </label>
              <label><span>{t('Day of week')}</span>
                <select value={vn.weekday} disabled={!form.enabled} onChange={e => setVn({ weekday: Number(e.target.value) })}>
                  {WEEKDAY_LABELS.map((label, index) => <option key={label} value={index}>{t(label)}</option>)}
                </select>
              </label>
              <label><span>{t('Hour')}</span>
                <input type="number" min="0" max="23" value={vn.hour} disabled={!form.enabled} onChange={e => setVn({ hour: Math.min(23, Math.max(0, Number(e.target.value) || 0)) })} />
              </label>
              <button disabled={!!loading} onClick={() => saveMalwareSchedule(scope)}><Clock size={14}/> {t('Save schedule')}</button>
            </div>
            {saved.enabled && saved.next_run_at && <p className="hint" style={{marginTop:8}}>{t('Next:')} <strong>{fmtStamp(saved.next_run_at)}</strong></p>}
            {saved.last_run_at && <p className="hint" style={{marginTop:8}}>
              {t('Last scheduled run:')} {fmtStamp(saved.last_run_at)} — <span className={saved.last_status === 'infected' ? 'badge danger' : saved.last_status === 'error' ? 'badge bad' : 'badge ok'}>{scanStatusLabel(saved.last_status)}</span> {saved.last_message || ''}
            </p>}
          </div>
        </section>;
      })}
    </>;
  }

  function renderPanelSettings() {
    if (!isAdmin) return <section className="section"><h2>{t('Settings')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const ipv4 = panelSettings.server_ipv4 || [];
    const ipv6 = panelSettings.ipv6 || {};
    // OPanel's tabs, one form at a time (operator, 2026-09-30). The admin's
    // own email and password are in Profile, in the account menu.
    const tabs = [
      ['general', 'General', SettingsIcon],
      ['brand', 'Brand assets', Image],
      ['api', 'API Tokens', KeyRound],
    ];
    const activeTab = tabs.some(([id]) => id === panelSettingsTab) ? panelSettingsTab : 'general';
    return <section className="section panel-settings-page">
      <div className="segmented-control backup-tabs" role="tablist" aria-label={t('Panel settings sections')}>
        {tabs.map(([id, label, Icon]) => <button key={id} type="button" role="tab" aria-selected={activeTab === id}
          className={activeTab === id ? 'active' : ''} onClick={() => setPanelSettingsTab(id)}><Icon size={14}/>{t(label)}</button>)}
      </div>
      {activeTab === 'general' && <div className="backup-tab-panel" role="tabpanel">
        <div className="backup-panel-title">
          <div><h3>{t('General')}</h3><p className="hint">{t("Panel name, hostname and the server's addresses.")}</p></div>
          <button className="secondary" disabled={!!loading} onClick={loadPanelSettings}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="panel-settings-grid panel-settings-compact">
          <label><span>{t('Panel name')}</span><input value={panelSettingsForm.app_name} onChange={e => setPanelSettingsForm(prev => ({ ...prev, app_name: e.target.value }))} placeholder="BPanel" /></label>
          <label><span>{t('Panel hostname')}</span><input value={panelSettingsForm.panel_hostname} onChange={e => setPanelSettingsForm(prev => ({ ...prev, panel_hostname: e.target.value }))} placeholder="panel.domain.com" /></label>
          <label className="check-line panel-ssl-status"><input type="checkbox" checked={!!panelSettingsForm.ssl_enabled} onChange={e => setPanelSettingsForm(prev => ({ ...prev, ssl_enabled: e.target.checked }))} /> {t('Panel SSL')}</label>
          <button disabled={!!loading || !panelSettingsForm.app_name || !panelSettingsForm.panel_hostname} onClick={savePanelSettings}><SettingsIcon size={14}/> {t('Save settings')}</button>
        </div>
        <div className="backup-subtitle">
          <h3>{t('Server network')}</h3>
          <p className="hint">{t('Addresses this server answers on. Detected live, so an IPv6 block added later shows up here.')}</p>
        </div>
        <div className="info-box">
          <div className="network-address-row">
            <strong>IPv4</strong>
            {ipv4.length > 0 ? ipv4.map(address => <code key={address}>{address}</code>) : <span className="hint">{t('None detected')}</span>}
          </div>
          <div className="network-address-row">
            <strong>IPv6</strong>
            {(ipv6.addresses || []).length > 0 ? ipv6.addresses.map(address => <code key={address}>{address}</code>) : <span className="hint">{t('None detected')}</span>}
            {ipv6.available
              ? (ipv6.enabled ? <span className="badge ok">{t('Enabled')}</span> : <span className="badge">{t('Disabled')}</span>)
              : <span className="badge warn">{t('Not available')}</span>}
          </div>
          <div className="actions" style={{marginTop:12}}>
            {ipv6.enabled
              ? <button className="danger" disabled={!!loading} onClick={() => toggleIpv6(false)}>{t('Disable IPv6')}</button>
              : <button className="secondary" disabled={!!loading || !ipv6.available} onClick={() => toggleIpv6(true)}><Network size={14}/> {t('Enable IPv6')}</button>}
          </div>
          <p className="hint" style={{marginTop:8}}>
            {ipv6.available
              ? t('Websites and the panel listen on both protocols while this is on. Point an AAAA record at the address above.')
              : t('No global IPv6 address is configured on this server yet. Add one at your provider, then refresh.')}
          </p>
        </div>
      </div>}
      {activeTab === 'brand' && <div className="backup-tab-panel" role="tabpanel">
        <div className="backup-panel-title">
          <div><h3>{t('Brand assets')}</h3><p className="hint">{t('Upload PNG, JPG, WEBP, or ICO files up to 1 MB.')}</p></div>
        </div>
        <div className="brand-asset-grid">
          <div className="brand-asset-card">
            <div className="brand-preview">{renderBrandMark('settings-brand-mark')}</div>
            <label><span>{t('Logo')}</span><input type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={e => setPanelLogoFile(e.target.files?.[0] || null)} /></label>
            <button className="secondary" disabled={!!loading || !panelLogoFile} onClick={() => uploadPanelAsset('logo')}><Upload size={14}/> {t('Upload logo')}</button>
          </div>
          <div className="brand-asset-card">
            <div className="brand-preview favicon-preview">{panelSettings.favicon_url ? <img src={panelSettings.favicon_url} alt="" /> : <Image size={28}/>}</div>
            <label><span>{t('Favicon')}</span><input type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={e => setPanelFaviconFile(e.target.files?.[0] || null)} /></label>
            <button className="secondary" disabled={!!loading || !panelFaviconFile} onClick={() => uploadPanelAsset('favicon')}><Upload size={14}/> {t('Upload favicon')}</button>
          </div>
        </div>
      </div>}
      {activeTab === 'api' && <div className="backup-tab-panel" role="tabpanel">
        <div className="backup-panel-title">
          <div><h3>{t('API Tokens')}</h3><p className="hint">{t('Provisioning tokens for WHMCS or external billing systems.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={loadApiTokens}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {createdApiToken && <div className="token-created-notice">
          <p><strong>{t('Token created!')}</strong> {t('Copy it now — it will not be shown again.')}</p>
          <div className="token-copy-row">
            <code>{createdApiToken}</code>
            <button className="mini" onClick={copyApiToken}><Copy size={14}/> {t('Copy')}</button>
          </div>
          <button className="mini secondary-light" onClick={() => setCreatedApiToken('')}>{t('Dismiss')}</button>
        </div>}
        <div className="token-create-form">
          <label><span>{t('Name')}</span><input value={newApiToken.name} onChange={e => setNewApiToken(prev => ({ ...prev, name: e.target.value }))} placeholder={t('WHMCS Production')} /></label>
          <label><span>{t('IP allowlist')}</span><input value={newApiToken.allowed_ips} onChange={e => setNewApiToken(prev => ({ ...prev, allowed_ips: e.target.value }))} placeholder={t('Optional, comma-separated')} /></label>
          <button disabled={!!loading || !newApiToken.name.trim()} onClick={createApiToken}><Plus size={14}/> {t('Create token')}</button>
        </div>
        {apiTokens.length === 0 && <p className="hint">{t('No API tokens yet.')}</p>}
        {apiTokens.length > 0 && <div className="table">
          {apiTokens.map(token => <div className="row" key={token.id}>
            <div className="token-info">
              <strong>{token.name}</strong>
              <small>{token.allowed_ips ? t('IP allowlist: {ips}', { ips: token.allowed_ips }) : t('Any IP address')}</small>
              <small>{token.last_used_at ? t('Last used: {when}', { when: new Date(token.last_used_at).toLocaleDateString() }) : t('Never used')}</small>
            </div>
            <span className="badge ok">{t('Active')}</span>
            <button className="mini danger" disabled={!!loading} onClick={() => revokeApiToken(token)}><Trash2 size={14}/> {t('Delete')}</button>
          </div>)}
        </div>}
      </div>}
    </section>;
  }

  // A reseller's share of the server: what is handed out against what it has.
  function renderResellerPool() {
    if (!isReseller || !resellerPool) return null;
    const rows = [
      [t('Customers'), resellerPool.customers, resellerPool.pool_user_limit],
      [t('Websites'), resellerPool.allocated_website_limit, resellerPool.pool_website_limit],
      [t('Disk (MB)'), resellerPool.allocated_storage_limit_mb, resellerPool.pool_storage_limit_mb],
      [t('Mailboxes'), resellerPool.allocated_mail_accounts_limit, resellerPool.pool_mail_accounts_limit],
      [t('Applications'), resellerPool.allocated_app_limit, resellerPool.pool_app_limit],
    ];
    return <section className="section">
      <div className="section-title"><div><h2>{t('Your share')}</h2><p className="hint">{t("Your own limits and every customer's together must fit in the share the administrator gave you.")}</p></div></div>
      <div className="reseller-pool">
        {rows.map(([label, used, total]) => <div className="reseller-pool-item" key={label}>
          <span>{label}</span>
          <strong>{used} / {total ? total : t('unlimited')}</strong>
        </div>)}
      </div>
    </section>;
  }

  function resellerName(id) {
    return users.find(u => u.id === id)?.username || `#${id}`;
  }

  function renderPoolInputs(form, setForm) {
    const fields = [
      ['pool_user_limit', t('Customers')],
      ['pool_website_limit', t('Websites')],
      ['pool_storage_limit_mb', t('Disk (MB)')],
      ['pool_mail_accounts_limit', t('Mailboxes')],
      ['pool_app_limit', t('Applications')],
    ];
    return <>
      <p className="hint wide">{t("Reseller share: its own limits and all its customers' must fit inside these. 0 = unlimited.")}</p>
      {fields.map(([field, label]) => <label key={field}><span>{t('Share')}: {label}</span><input type="number" min="0" value={form[field] ?? 0} onChange={e => setForm(prev => ({ ...prev, [field]: e.target.value }))} /></label>)}
    </>;
  }

  function renderUsers() {
    if (!canManageUsers) return <section className="section"><h2>{t('Users')}</h2><p className="hint">{t('No permission.')}</p></section>;
    const activeUserTab = userTab || 'list';
    return <>
      <section className="section">
        <div className="section-title">
          <div>{isReseller
            ? <><h2>{t('Customers')}</h2><p className="hint">{t("Your customers' accounts, your packages, and new customers.")}</p></>
            : <><h2>{t('Panel Users')}</h2><p className="hint">{t('Manage panel accounts, hosting packages, and create new users.')}</p></>}</div>
          <button className="secondary" disabled={!!loading} onClick={() => { loadUsers(); loadPackages(); if (isReseller) loadResellerPool(); }}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="tab-bar" role="tablist" aria-label={t('Panel user sections')}>
          <button type="button" role="tab" aria-selected={activeUserTab === 'list'} className={activeUserTab === 'list' ? 'tab active' : 'tab'} onClick={() => setUserTab('list')}><Users size={14}/> {t('List Users')}</button>
          <button type="button" role="tab" aria-selected={activeUserTab === 'packages'} className={activeUserTab === 'packages' ? 'tab active' : 'tab'} onClick={() => setUserTab('packages')}><PackageOpen size={14}/> {t('Packages')}</button>
          <button type="button" role="tab" aria-selected={activeUserTab === 'add'} className={activeUserTab === 'add' ? 'tab active' : 'tab'} onClick={() => setUserTab('add')}><Plus size={14}/> {t('Add User')}</button>
        </div>
      </section>
      {renderResellerPool()}
      {activeUserTab === 'list' && renderUsersListTab()}
      {activeUserTab === 'packages' && renderUsersPackagesTab()}
      {activeUserTab === 'add' && renderUsersAddTab()}
    </>;
  }

  // "Starter (5 website(s), 1 GB)": what picking a package fills in.
  function packageOptionLabel(item) {
    return `${item.name} (${t('{n} website(s)', { n: item.website_limit })}, ${formatBytes(Number(item.storage_limit_mb || 0) * 1024 * 1024)})`;
  }

  function renderUsersListTab() {
    // A package decides the limits: the server applies its values over any
    // typed here, so the fields are locked while one is chosen.
    const packaged = !!editingUserForm.package_id;
    return <section className="section">
      {users.length === 0 && <EmptyState icon={Users} message={t('No users found.')} />}
      <div className="table">
        {users.map(user => <div className="row user-row" key={user.id}>
          {/* OPanel's five cells (a sixth pushed the buttons onto a line of
              their own); BPanel's package and 2FA go under the name. */}
          <div className="user-main"><strong>{user.username}</strong>
            <small>{[user.email, user.package_name || t('Custom'), user.totp_enabled ? '2FA' : ''].filter(Boolean).join(' · ')}</small></div>
          <span className="badge" title={isAdmin && user.reseller_id ? t('via {name}', { name: resellerName(user.reseller_id) }) : undefined}>{t(roleLabel(user.role))}</span>
          <span className={`badge ${user.is_active ? 'ok' : 'warn'}`}>{user.is_active ? t('Active') : t('Suspended')}</span>
          <span className={`user-metric${user.storage_used_bytes == null || Number(user.storage_used_bytes) < 0 ? ' pending' : ''}`}><HardDrive size={13}/>{storageUsageText(user)}</span>
          <div className="row-actions">
            {(isAdmin || user.id !== currentUser?.id) && <button className="mini secondary-light" disabled={!!loading} onClick={() => startEditingUser(user)}><Pencil size={14}/> {t('Edit')}</button>}
            {user.id !== currentUser?.id && <button className="mini secondary-light" disabled={!!loading} onClick={() => quickLoginUser(user)}><LogIn size={14}/> {t('Login as')}</button>}
            {user.id !== currentUser?.id && (user.is_active
              ? <button className="mini danger" disabled={!!loading} onClick={() => suspendUser(user)}><Ban size={14}/> {t('Suspend')}</button>
              : <button className="mini secondary-light" disabled={!!loading} onClick={() => unsuspendUser(user)}><CheckCircle size={14}/> {t('Unsuspend')}</button>)}
            {user.totp_enabled && user.id !== currentUser?.id && <button className="mini secondary-light" disabled={!!loading} onClick={() => resetUserTwoFactor(user)}>{t('Reset 2FA')}</button>}
            {user.id !== currentUser?.id && <button className="mini danger" disabled={!!loading} onClick={() => deletePanelUser(user)} aria-label={t('Delete {name}', { name: user.username })} title={t('Delete')}><Trash2 size={14}/></button>}
          </div>
          {editingUser?.id === user.id && <div className="user-edit-panel">
            <div className="user-edit-heading">
              <div><strong>{t('Edit')} {user.username}</strong><small>
                {user.id === currentUser?.id ? t('Role is locked for the active admin session.') : t('Role changes sign the user out of existing sessions.')}
                {editingUserForm.role === 'admin' ? ` ${t('Admin accounts bypass website and storage limits.')}` : ''}
              </small></div>
              <button className="user-edit-close secondary-light" onClick={cancelEditingUser} aria-label={t('Close user editor')} title={t('Close user editor')}><X size={16}/></button>
            </div>
            <div className="user-edit-grid">
              <label><span>{t('Email')}</span><input type="email" value={editingUserForm.email} onChange={e => setEditingUserForm(prev => ({ ...prev, email: e.target.value }))} /></label>
              {isAdmin && <label><span>{t('Role')}</span><select value={editingUserForm.role} disabled={user.id === currentUser?.id} onChange={e => setEditingUserForm(prev => ({ ...prev, role: e.target.value }))}>
                <option value="end_user">{t('End user')}</option><option value="reseller">{t('Reseller')}</option><option value="admin">{t('Admin')}</option>
              </select></label>}
              {isAdmin && editingUserForm.role === 'end_user' && users.some(u => u.role === 'reseller') && <label><span>{t('Reseller')}</span><select value={editingUserForm.reseller_id || ''} onChange={e => setEditingUserForm(prev => ({ ...prev, reseller_id: e.target.value }))}>
                <option value="">{t('None (yours)')}</option>
                {users.filter(u => u.role === 'reseller').map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
              </select></label>}
              <label><span>{t('Package')}</span><select value={editingUserForm.package_id} onChange={e => applyPackageToEditingUser(e.target.value)}>
                <option value="">{t('Custom')}</option>
                {packages.map(item => <option key={item.id} value={item.id}>{packageOptionLabel(item)}</option>)}
              </select></label>
              <label><span>{t('Site limit')}</span><input type="number" min="0" max="1000" disabled={packaged} value={editingUserForm.website_limit} onChange={e => setEditingUserForm(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
              <label><span>{t('Disk limit (MB)')}</span><input type="number" min="0" max="1048576" disabled={packaged} value={editingUserForm.storage_limit_mb} onChange={e => setEditingUserForm(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
              <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" disabled={packaged} value={editingUserForm.sftp_accounts_limit} onChange={e => setEditingUserForm(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
              {mailAddonInstalled && <label><span>{t('Mailbox limit')}</span><input type="number" min="0" max="1000" disabled={packaged} value={editingUserForm.mail_accounts_limit} onChange={e => setEditingUserForm(prev => ({ ...prev, mail_accounts_limit: e.target.value }))} /></label>}
              <label><span>{t('New password')} <small>{t('(leave empty to keep)')}</small></span><input type="password" autoComplete="new-password" value={editingUserForm.new_password} onChange={e => setEditingUserForm(prev => ({ ...prev, new_password: e.target.value }))} placeholder={t('Min 12 characters')} /></label>
              {!!editingUserForm.new_password && <label><span>{t('Confirm password')}</span><input type="password" autoComplete="new-password" value={editingUserForm.confirm_password} onChange={e => setEditingUserForm(prev => ({ ...prev, confirm_password: e.target.value }))} placeholder={t('Repeat password')} /></label>}
              {isAdmin && editingUserForm.role === 'reseller' && renderPoolInputs(editingUserForm, setEditingUserForm)}
            </div>
            <div className="user-edit-actions">
              <button className="secondary-light" onClick={cancelEditingUser}>{t('Cancel')}</button>
              <button disabled={!!loading || !editingUserForm.email.trim()} onClick={updatePanelUser}><Save size={14}/> {t('Save changes')}</button>
            </div>
          </div>}
        </div>)}
      </div>
      {isAdmin && <div className="section" style={{marginTop:16}}>
        <h2>{t('Assign domain to user')}</h2>
        <div className="assign-row">
          <select value={assignWebsiteId} onChange={e => setAssignWebsiteId(e.target.value)}>
            <option value="">{t('Select domain')}</option>
            {websites.map(site => <option key={site.id} value={site.id}>{site.domain}</option>)}
          </select>
          <select value={assignUserId} onChange={e => setAssignUserId(e.target.value)}>
            <option value="">{t('Select user')}</option>
            {users.map(user => <option key={user.id} value={user.id}>{user.username} ({t(roleLabel(user.role))})</option>)}
          </select>
          <button disabled={!assignWebsiteId || !assignUserId || !!loading} onClick={assignDomainToUser}>{t('Assign')}</button>
        </div>
        {(() => {
          // The app and the databases behind the website move with it: the
          // app's code sits in its owner's home, out of anyone else's reach.
          const moving = [
            ...(assignPreview?.application ? [t('application {name}', { name: assignPreview.application })] : []),
            ...(assignPreview?.databases || []).map(name => t('database {name}', { name })),
          ];
          return moving.length > 0 && <p className="hint">{t('Moves with this website:')} <strong>{moving.join(', ')}</strong>.
            {assignPreview?.application ? ` ${t('The application restarts once.')}` : ''}</p>;
        })()}
      </div>}
    </section>;
  }

  function renderUsersPackagesTab() {
    const packageInUse = item => users.some(user => user.package_id === item.id);
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>{t('Hosting Packages')}</h2><p className="hint">{isReseller ? t("Your own packages: only you see them, to fill in your customers' limits.") : t('Manage provisioning plans for WHMCS and billing systems.')}</p></div>
          <button className="secondary" disabled={!!loading} onClick={loadPackages}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        <div className="token-create-form package-form" style={{ '--package-limit-cols': mailAddonInstalled ? 4 : 3 }}>
          <label><span>{t('Name')}</span><input value={newPackage.name} onChange={e => setNewPackage(prev => ({ ...prev, name: e.target.value }))} placeholder={t('Starter')} /></label>
          <label><span>{t('Sites')}</span><input type="number" min="0" max="1000" value={newPackage.website_limit} onChange={e => setNewPackage(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
          <label><span>{t('Disk (MB)')}</span><input type="number" min="0" max="1048576" value={newPackage.storage_limit_mb} onChange={e => setNewPackage(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
          <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" value={newPackage.sftp_accounts_limit} onChange={e => setNewPackage(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
          {mailAddonInstalled && <label><span>{t('Mailboxes')}</span><input type="number" min="0" max="1000" value={newPackage.mail_accounts_limit} onChange={e => setNewPackage(prev => ({ ...prev, mail_accounts_limit: e.target.value }))} /></label>}
          <button disabled={!!loading || !newPackage.name.trim()} onClick={createPackage}><Plus size={14}/> {t('Add')}</button>
        </div>
        {packages.length === 0 && <p className="hint">{t('No packages yet. Create one above.')}</p>}
        {packages.length > 0 && <div className="table">
          {packages.map(item => <div className="row" key={item.id}>
            <div className="token-info">
              <strong>{item.name}</strong>
              <small>{t('{n} website(s)', { n: item.website_limit })} | {formatBytes(Number(item.storage_limit_mb || 0) * 1024 * 1024)} | {t('{n} SFTP account(s)', { n: item.sftp_accounts_limit ?? 0 })}{mailAddonInstalled ? ` | ${t('{n} mailboxes', { n: item.mail_accounts_limit ?? 10 })}` : ''}</small>
            </div>
            <div className="row-actions">
              <button className="mini secondary-light" disabled={!!loading} onClick={() => startEditingPackage(item)}><Pencil size={14}/> {t('Edit')}</button>
              <button className="mini danger" disabled={!!loading || packageInUse(item)} onClick={() => deletePackage(item)}
                aria-label={t('Delete {name}', { name: item.name })} title={packageInUse(item) ? t('Package is in use') : t('Delete')}><Trash2 size={14}/></button>
            </div>
            {String(editingPackageId) === String(item.id) && <div className="user-edit-panel">
              <div className="user-edit-heading">
                <strong>{t('Edit')} {item.name}</strong>
                <button className="user-edit-close secondary-light" onClick={cancelEditingPackage} aria-label={t('Close')} title={t('Close')}><X size={16}/></button>
              </div>
              <div className="user-edit-grid">
                <label><span>{t('Name')}</span><input value={editingPackageForm.name} onChange={e => setEditingPackageForm(prev => ({ ...prev, name: e.target.value }))} /></label>
                <label><span>{t('Sites')}</span><input type="number" min="0" max="1000" value={editingPackageForm.website_limit} onChange={e => setEditingPackageForm(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
                <label><span>{t('Disk (MB)')}</span><input type="number" min="0" max="1048576" value={editingPackageForm.storage_limit_mb} onChange={e => setEditingPackageForm(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
                <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" value={editingPackageForm.sftp_accounts_limit} onChange={e => setEditingPackageForm(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
                {mailAddonInstalled && <label><span>{t('Mailboxes')}</span><input type="number" min="0" max="1000" value={editingPackageForm.mail_accounts_limit} onChange={e => setEditingPackageForm(prev => ({ ...prev, mail_accounts_limit: e.target.value }))} /></label>}
              </div>
              <div className="user-edit-actions">
                <button className="secondary-light" onClick={cancelEditingPackage}>{t('Cancel')}</button>
                <button disabled={!!loading || !editingPackageForm.name.trim()} onClick={() => updatePackage(item.id)}><Save size={14}/> {t('Save')}</button>
              </div>
            </div>}
          </div>)}
        </div>}
      </section>
    </>;
  }

  function renderUsersAddTab() {
    const packaged = !!newUser.package_id;
    return <>
      <section className="section">
        <div className="section-title">
          <div><h2>{isReseller ? t('Add customer') : t('Add panel user')}</h2><p className="hint">{t('Panel username is also the Linux user. Select a package to auto-fill limits.')}</p></div>
        </div>
        <div className="user-create-card">
          <label><span>{t('Username')}</span><input value={newUser.username} onChange={e => setNewUser(prev => ({ ...prev, username: e.target.value.toLowerCase() }))} placeholder="johndoe" /></label>
          <label><span>{t('Email')}</span><input value={newUser.email} onChange={e => setNewUser(prev => ({ ...prev, email: e.target.value }))} placeholder="user@domain.com" /></label>
          <label><span>{t('Password')}</span><input value={newUser.password} onChange={e => setNewUser(prev => ({ ...prev, password: e.target.value }))} placeholder={t('Min 12 characters')} type="password" /></label>
          {isAdmin && <label><span>{t('Role')}</span><select value={newUser.role} onChange={e => setNewUser(prev => ({ ...prev, role: e.target.value }))}>
            <option value="end_user">{t('End user')}</option><option value="reseller">{t('Reseller')}</option><option value="admin">{t('Admin')}</option>
          </select></label>}
          {isAdmin && newUser.role === 'end_user' && users.some(u => u.role === 'reseller') && <label><span>{t('Reseller')}</span><select value={newUser.reseller_id || ''} onChange={e => setNewUser(prev => ({ ...prev, reseller_id: e.target.value }))}>
            <option value="">{t('None (yours)')}</option>
            {users.filter(u => u.role === 'reseller').map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
          </select></label>}
          <label><span>{t('Package')}</span><select value={newUser.package_id} onChange={e => applyPackageToNewUser(e.target.value)}>
            <option value="">{t('Custom')}</option>
            {packages.map(item => <option key={item.id} value={item.id}>{packageOptionLabel(item)}</option>)}
          </select></label>
          <label><span>{t('Site limit')}</span><input type="number" min="0" max="1000" disabled={packaged} value={newUser.website_limit} onChange={e => setNewUser(prev => ({ ...prev, website_limit: e.target.value }))} /></label>
          <label><span>{t('Disk (MB)')}</span><input type="number" min="0" max="1048576" disabled={packaged} value={newUser.storage_limit_mb} onChange={e => setNewUser(prev => ({ ...prev, storage_limit_mb: e.target.value }))} /></label>
          <label><span>{t('SFTP accounts')}</span><input type="number" min="0" max="100" disabled={packaged} value={newUser.sftp_accounts_limit} onChange={e => setNewUser(prev => ({ ...prev, sftp_accounts_limit: e.target.value }))} /></label>
          {mailAddonInstalled && <label><span>{t('Mailbox limit')}</span><input type="number" min="0" max="1000" disabled={packaged} value={newUser.mail_accounts_limit} onChange={e => setNewUser(prev => ({ ...prev, mail_accounts_limit: e.target.value }))} /></label>}
          {isAdmin && newUser.role === 'reseller' && renderPoolInputs(newUser, setNewUser)}
          <button disabled={!!loading || !newUser.username || !newUser.password} onClick={createUser}><Plus size={14}/> {isReseller ? t('Create customer') : t('Create user')}</button>
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
          <span className="editor-chip">{t('{n} line(s)', { n: editorLineCount })}</span>
          <span className="editor-chip">Ln {editorCursor.line}, Col {editorCursor.column}</span>
          <button className="secondary" disabled={!selectedWebsiteId || !!loading} onClick={() => readFile(filePath)}><RefreshCw size={14}/>{t('Reload')}</button>
          <button disabled={!selectedWebsiteId || !!loading} onClick={writeFile}>{t('Save')}</button>
          <button disabled={!selectedWebsiteId || !filePath || !!loading} onClick={() => downloadFile(filePath)}><Download size={14}/></button>
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
    const owner = token.username && token.username !== currentUser?.username ? ` (${token.username})` : '';
    if (!window.confirm(t('Revoke MCP token "{name}"{owner}? Anything using it stops working at once.', { name: token.name, owner }))) return;
    const data = await request(`/mcp/tokens/${token.id}`, { method: 'DELETE' }, t('Revoking...'));
    if (data) {
      setNotice(t('Token revoked.'));
      await loadMcpTokens();
    }
  }

  // Each client's setup, ready to paste. While a token that was just created
  // is still on screen it is filled in: the server keeps only a hash, so that
  // is the one moment a finished command can be offered.
  function mcpClientSnippets(token) {
    const endpoint = `${window.location.origin}/api/mcp`;
    const bearer = `Bearer ${token || '<your-token>'}`;
    return [
      ['Claude Code', `claude mcp add --transport http bpanel ${endpoint} --header "Authorization: ${bearer}"`],
      ['Cursor (~/.cursor/mcp.json)', JSON.stringify({ mcpServers: { bpanel: { url: endpoint, headers: { Authorization: bearer } } } }, null, 2)],
      ['VS Code (.vscode/mcp.json)', JSON.stringify({ servers: { bpanel: { type: 'http', url: endpoint, headers: { Authorization: bearer } } } }, null, 2)],
    ];
  }

  function renderMcp() {
    const enabled = mcpAddonInstalled;
    const endpoint = `${window.location.origin}/api/mcp`;
    const mine = mcpTokens.filter(token => token.user_id === currentUser?.id);
    const others = mcpTokens.filter(token => token.user_id !== currentUser?.id);
    return <>
      <section className="section">
        <div className="section-title">
          <div>
            <h2>{t('AI assistants (MCP)')}</h2>
            <p className="hint">{t('Connect Claude Code, Cursor, VS Code or another MCP client to this panel. A token acts as your account: it sees your websites, databases and backups')}{isAdmin ? t(' (as an administrator, every account’s)') : ''} {t('and nothing else. With actions allowed it can also edit your websites’ files, so an assistant can build and fix your sites; deleting a file always asks you first in the client.')}</p>
          </div>
          <button className="secondary" disabled={!!loading} onClick={loadMcpTokens}><RefreshCw size={14}/> {t('Refresh')}</button>
        </div>
        {/* An administrator reaches the page while the addon is off; nothing
            answers on the endpoint until it is installed. */}
        {!enabled && <div className="info-box"><AlertCircle size={14}/> {t('MCP is not running on this panel. Install or start the')} <strong>{t('AI assistants (MCP)')}</strong> {t('addon on the Addons page first.')}
          {' '}<button className="mini" onClick={() => navigateToPage('addons')}><PackageOpen size={13}/> {t('Open Addons')}</button></div>}
        {enabled && !window.location.protocol.startsWith('https') && <div className="info-box"><AlertCircle size={14}/> {t('MCP clients refuse a self-signed certificate, so no assistant will connect until the panel has one. Install it under Panel settings → SSL.')}</div>}
        {enabled && renderCopyBlock(t('Endpoint'), endpoint)}
      </section>

      {enabled && mcpNewToken && <section className="section token-created-notice">
        <div className="section-title">
          <div><h2>{t('Token created.')}</h2><p className="hint">{t('Copy it now — it is shown only once.')}</p></div>
          <button className="secondary" onClick={() => setMcpNewToken('')}>{t('Dismiss')}</button>
        </div>
        {renderCopyBlock(t('Token'), mcpNewToken)}
        {mcpClientSnippets(mcpNewToken).map(([label, text]) => <React.Fragment key={label}>
          {renderCopyBlock(label, text, { multiline: true, copiedMessage: t('{name} setup copied.', { name: label }) })}
        </React.Fragment>)}
      </section>}

      {enabled && <section className="section">
        <h2>{t('New token')}</h2>
        <div className="token-create-form mcp-token-form">
          <label><span>{t('Name')}</span><input value={mcpDraft.name} maxLength={100} placeholder={t('Claude Code on my laptop')}
            onChange={e => setMcpDraft(prev => ({ ...prev, name: e.target.value }))} /></label>
          <label><span>{t('Expires')}</span><select value={mcpDraft.expires_in_days}
            onChange={e => setMcpDraft(prev => ({ ...prev, expires_in_days: Number(e.target.value) }))}>
            {[30, 90, 180, 365].map(days => <option key={days} value={days}>{days} {t('days')}</option>)}
          </select></label>
          <button disabled={!!loading || !mcpDraft.name.trim()} onClick={createMcpToken}><Plus size={14}/> {t('Create token')}</button>
        </div>
        <label className="option-card">
          <input type="checkbox" checked={!!mcpDraft.can_write}
            onChange={e => setMcpDraft(prev => ({ ...prev, can_write: e.target.checked }))} />
          <span>
            <strong>{t('Allow actions')}</strong>
            <small>{t('Write and delete files, run backups, issue certificates, switch the WAF')}{isAdmin ? t(', restart services, block and unblock IPs, add WAF rules') : ''}. {t('Without it the token can only read.')}</small>
          </span>
        </label>
        {/* The server's limit, MAX_TOKENS_PER_USER in services/mcp.py. */}
        <p className="hint">{t('Up to')} 10 {t('tokens per account.')}</p>
      </section>}

      {enabled && <section className="section">
        <h2>{t('Your tokens')}</h2>
        {mine.length === 0 ? <p className="hint">{t('No MCP tokens yet.')}</p> : renderMcpTokenRows(mine)}
      </section>}

      {enabled && isAdmin && others.length > 0 && <section className="section">
        <div className="section-title"><div><h2>{t('Everyone else\'s tokens')}</h2><p className="hint">{t('Every key to this server, and who holds it. You can revoke any of them.')}</p></div></div>
        {renderMcpTokenRows(others, { showOwner: true })}
      </section>}

      {enabled && !mcpNewToken && <section className="section">
        <div><h2>{t('Connecting a client')}</h2>
          <p className="hint">{t('Replace <your-token> with a token from above. The client must trust this panel’s HTTPS certificate; a self-signed one is refused.')}</p></div>
        {mcpClientSnippets('').map(([label, text]) => <React.Fragment key={label}>
          {renderCopyBlock(label, text, { multiline: true, copiedMessage: t('{name} setup copied.', { name: label }) })}
        </React.Fragment>)}
      </section>}
    </>;
  }

  function renderMcpTokenRows(tokens, { showOwner = false } = {}) {
    return <div className="table">
      {tokens.map(token => {
        return <div className="row" key={token.id}>
          <div className="token-info">
            <strong>{token.name}{showOwner && token.username ? ` — ${token.username}` : ''}</strong>
            <small>{t('Prefix:')} {token.prefix}{t('… | Created:')} {token.created_at ? new Date(token.created_at).toLocaleDateString() : '—'}
              {' | '}{t('Expires:')} {token.expires_at ? new Date(token.expires_at).toLocaleDateString() : t('never')}
              {' | '}{t('Last used:')} {token.last_used_at ? new Date(token.last_used_at).toLocaleString() : t('never')}</small>
          </div>
          {token.expired
            ? <span className="badge warn">{t('Expired')}</span>
            : <span className={token.can_write ? 'badge warn' : 'badge ok'}>{token.can_write ? t('Read + actions') : t('Read-only')}</span>}
          <button className="mini danger" disabled={!!loading} onClick={() => revokeMcpToken(token)}><Trash2 size={14}/> {t('Revoke')}</button>
        </div>;
      })}
    </div>;
  }

  function renderPage() {
    if (page === 'websites') return renderWebsites();
    if (page === 'addons') return renderAddons();
    // DNS Manager (2026-09-29): administrators and customers, once installed.
    if (page === 'dns') return dnsAddonInstalled ? renderDns() : renderAddonMissing('dns');
    if (page === 'mail') return mailAddonInstalled ? renderMail() : renderAddonMissing('mail');
    // Reachable by URL after the addon is removed, so it answers for itself
    // rather than rendering a page whose every request would be refused.
    if (page === 'applications') return appsFeatureEnabled ? renderApplications() : renderAddonMissing('application');
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
    // An addon since 2026-09-27: the page is there once it is installed.
    if (page === 'malware' || page === 'malware-scan') return malwareAddonInstalled ? renderMalware() : renderAddonMissing('malware');
    if (page === 'access-logs') return renderWafAccessLogs();
    if (page === 'updates') return renderUpdates();
    // Reachable by URL, so it answers for itself rather than firing a
    // page full of requests that will every one be refused.
    if (page === 'services') return isAdmin ? renderServices() : renderAdminOnly();
    if (page === 'mcp') return (mcpAddonInstalled || isAdmin) ? renderMcp() : renderAddonMissing('mcp');
    // Administrators only (operator, 2026-09-27): customers get no notifications.
    if (page === 'notifications') return !isAdmin ? renderAdminOnly() : notificationsAddonInstalled ? renderNotificationsPage() : renderAddonMissing('notifications');
    if (page === 'settings') return renderSettingsHub();
    if (page === 'panel-settings') return renderPanelSettings();
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
      <ThemeToggle theme={theme} onToggle={toggleTheme} className="theme-toggle-btn"/>
      <LanguageToggle language={language} onChange={changeLanguage} className="lang-toggle-btn"/>
      <section className="login-card">
        <div className="login-brand">
          {renderBrandMark('login-brand-mark')}
          <div>
            <p className="eyebrow">{t('Server Management Panel')}</p>
            <h1>{panelSettings.app_name || 'BPanel'}</h1>
          </div>
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
        {demoAccess.enabled && <div className="demo-login">
          <div className="demo-login-head"><Eye size={15}/><strong>{t('Demo')}</strong></div>
          <p className="hint">{t('Read-only: look around freely, nothing you change is saved.')}</p>
          {demoAccess.accounts.map(account => <div className="demo-login-row" key={account.slot}>
            <span className="demo-login-cred">
              <small>{account.slot === 'admin' ? t('Administrator') : t('Hosting customer')}</small>
              <code>{account.username}</code><span aria-hidden="true">/</span><code>{account.password}</code>
            </span>
            <button type="button" className="secondary" disabled={!!loading} onClick={() => login('', { username: account.username, password: account.password })}>
              <LogIn size={14}/> {t('Sign in')}</button>
          </div>)}
        </div>}
      </section>
      {renderNotifications()}
    </main>;
  }

  if (standaloneEditor) return renderStandaloneEditor();

  const ActiveIcon = pageItem?.[2] || Home;

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
            <Menu size={20}/><span><ActiveIcon size={17}/>{t(pageItem?.[1] || 'Menu')}</span>
          </button>
          <div className="page-title">
            {settingsPageItem
              ? <h1 className="page-crumbs"><button type="button" onClick={() => navigateToPage('settings')}>{t('Settings')}</button><span aria-hidden="true">›</span>{t(settingsPageItem[1])}</h1>
              : <h1>{pageItem?.[1] ? t(pageItem[1]) : (panelSettings.app_name || 'BPanel')}</h1>}
          </div>
          {/* The page title, then one account menu - profile, account security
              and sign out live in it, as they do in OPanel. */}
          <div className="top-actions">
            <LanguageToggle language={language} onChange={changeLanguage} className="secondary compact-btn top-lang"/>
            <ThemeToggle theme={theme} onToggle={toggleTheme} className="secondary compact-btn icon-only" size={15}/>
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
                <button type="button" role="menuitem" onClick={() => { setUserMenuOpen(false); openProfileModal(); }}><KeyRound size={15}/>{t('Profile')}</button>
                <button type="button" role="menuitem" onClick={() => { setUserMenuOpen(false); navigateToPage('security'); }}><LockKeyhole size={15}/>{t('Account security')}</button>
                {currentUser?.impersonator && <button type="button" role="menuitem" onClick={() => { setUserMenuOpen(false); returnToImpersonator(); }}><ArrowLeft size={15}/>{t('Back to {name}', { name: currentUser.impersonator })}</button>}
                <button type="button" role="menuitem" className="user-menu-logout" onClick={() => { setUserMenuOpen(false); logout(); }}><LogOut size={15}/>{t('Logout')}</button>
              </div>}
            </div>
          </div>
        </section>
        <div className="content-body">
          {currentUser?.demo && <div className="demo-banner" role="status"><Eye size={15}/> <span>{t('You are viewing a read-only demo: you can open every page, and nothing you change is saved.')}</span></div>}
          {currentUser?.impersonator && <div className="impersonation-banner" role="status">
            <LogIn size={15}/> <span>{t('You are logged in as {name}.', { name: currentUser.username })}</span>
            <button type="button" className="mini" disabled={!!loading} onClick={returnToImpersonator}><ArrowLeft size={14}/> {t('Back to {name}', { name: currentUser.impersonator })}</button>
          </div>}
          {renderPage()}
          {loading && <div className="loading"><span></span>{t(loading)}</div>}
        </div>
      </div>
    </section>
    {showProfileModal && <div className="modal-overlay" onClick={() => setShowProfileModal(false)}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{t('Profile Settings')}</h3>
          <button className="secondary-light" onClick={() => setShowProfileModal(false)} aria-label={t('Close')}><X size={16}/></button>
        </div>
        <div className="modal-body">
          {isAdmin && <div className="modal-section">
            <h4>{t('Email')}</h4>
            <div className="profile-email-row">
              <input type="email" value={adminAccountForm.email} onChange={e => setAdminAccountForm(prev => ({ ...prev, email: e.target.value }))} placeholder="admin@domain.com" />
              <button disabled={!!loading || !adminAccountForm.email.trim() || adminAccountForm.email === currentUser?.email} onClick={saveProfileEmail}><Save size={14}/> {t('Save')}</button>
            </div>
            <p className="hint">{t("Used for Let's Encrypt SSL notifications and panel communication.")}</p>
          </div>}
          <div className="modal-section">
            <h4>{t('Change Password')}</h4>
            <label><span>{t('New password')}</span><input type="password" value={adminAccountForm.password} onChange={e => setAdminAccountForm(prev => ({ ...prev, password: e.target.value }))} placeholder={t('Min 12 characters')} autoComplete="new-password" /></label>
            <label><span>{t('Current password')}</span><input type="password" value={adminAccountForm.current_password} onChange={e => setAdminAccountForm(prev => ({ ...prev, current_password: e.target.value }))} placeholder={t('Required to confirm')} autoComplete="current-password" /></label>
            {currentUser?.totp_enabled && <label><span>{t('2FA code')}</span><input value={adminAccountForm.code} onChange={e => setAdminAccountForm(prev => ({ ...prev, code: e.target.value }))} placeholder={t('6-digit code')} maxLength={6} inputMode="numeric" autoComplete="one-time-code" /></label>}
            <button disabled={!!loading || !adminAccountForm.password || adminAccountForm.password.length < 12 || !adminAccountForm.current_password} onClick={changeMyPassword}><KeyRound size={14}/> {t('Change password')}</button>
          </div>
        </div>
      </div>
    </div>}
    {renderNotifications()}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
