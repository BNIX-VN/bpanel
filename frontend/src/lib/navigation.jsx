// Where everything is, as OPanel's own SNPanel-style redesign lays it out
// (operator, 2026-10-18: "Xong tiến hành làm cho bpanel" - the same shell,
// ported here next): a place with several pages - a hub - shows them as tabs
// under one header instead of being buried in the old Settings tile grid.
//
// This first pass is deliberately conservative: nothing an existing customer
// could already reach stops being reachable. Mail, DNS, Git, AI assistants
// and Applications are addons, opened from their Dashboard tiles rather
// than the sidebar (see sidebarItems). Only pages that already lived inside the Settings tile grid
// (Server status, Security, System) move into hubs, and Files/SFTP/Terminal
// - three always-present pages with nothing addon-gated about the grouping
// itself - fold into one Files hub.
//
// A page key is App's (PAGE_ROUTES there); a hub's key is either its first
// page (files) or an address of its own (server, security-center, config)
// that opens its first tab.
import { Archive, Clock, Database, FolderOpen, Globe, Home, Lock, Server, Settings, ShieldCheck, Users } from 'lucide-react';
import WordPressGlyph from '../icons/WordPressGlyph.jsx';

const msg = (text) => text;

// Every page's title; translated where it is shown.
export const PAGE_TITLES = {
  dashboard: msg('Dashboard'),
  websites: msg('Websites'),
  website: msg('Websites'),
  applications: msg('Applications'),
  ssl: 'SSL',
  databases: msg('Databases'),
  cron: msg('Cron'),
  files: msg('File manager'),
  sftp: msg('SFTP accounts'),
  terminal: msg('Terminal'),
  backups: msg('Backups'),
  users: msg('Panel users'),
  'panel-settings': msg('Panel settings'),
  security: msg('Account security'),
  malware: msg('Malware Scanner'),
  php: msg('PHP config'),
  firewall: msg('Firewall'),
  waf: 'WAF',
  'waf-site': 'WAF',
  'malware-scan': msg('Malware Scanner'),
  'access-logs': msg('Access logs'),
  wordpress: msg('WordPress Manager'),
  updates: msg('Updates'),
  addons: msg('Addons'),
  mcp: msg('AI assistants (MCP)'),
  mail: msg('Email'),
  dns: msg('DNS Manager'),
  notifications: msg('Notifications'),
  services: msg('Services'),
  usage: msg('Resource usage'),
  git: 'Git',
  processes: msg('Process monitor'),
  'ram-usage': msg('RAM usage'),
  'disk-usage': msg('Disk usage'),
  traffic: msg('Traffic'),
  'account-resources': msg('Account resources'),
};

// The facts a role's navigation depends on, from App:
// { isAdmin, isReseller, canManageUsers, canOpenTerminal, appsFeatureEnabled,
//   mailAddonInstalled, dnsAddonInstalled, gitAddonInstalled,
//   mcpAddonInstalled, notificationsAddonInstalled, malwareAddonInstalled }

// The hubs: one header, the pages as its tabs.
export const HUBS = [
  { key: 'server', title: msg('Server'), roles: ['admin'], tabs: [
    { page: 'processes', label: msg('Processes') },
    { page: 'ram-usage', label: 'RAM' },
    { page: 'disk-usage', label: msg('Disk') },
    { page: 'traffic', label: msg('Traffic') },
    { page: 'account-resources', label: msg('Account resources'), when: (c) => c.limitsOn },
    { page: 'php', label: msg('PHP config') },
    { page: 'services', label: msg('Services') },
    { page: 'updates', label: msg('Updates') },
  ] },
  { key: 'security-center', title: msg('Security'), roles: ['admin'], tabs: [
    { page: 'firewall', label: msg('Firewall') },
    { page: 'waf', label: 'WAF', also: ['waf-site'] },
    { page: 'access-logs', label: msg('Access logs') },
    { page: 'malware', label: msg('Malware Scanner'), also: ['malware-scan'], when: (c) => c.malwareAddonInstalled },
  ] },
  { key: 'config', title: msg('Settings'), roles: ['admin'], tabs: [
    { page: 'panel-settings', label: msg('Panel settings') },
    { page: 'addons', label: msg('Addons') },
    { page: 'notifications', label: msg('Notifications'), when: (c) => c.notificationsAddonInstalled },
  ] },
  // No Files hub (operator, 2026-10-26): the File manager opens in a browser
  // tab of its own; SFTP accounts and the terminal are opened from the
  // Dashboard's tools (see PARENTS below).
];

const roleOf = (ctx) => (ctx.isAdmin ? 'admin' : ctx.isReseller ? 'reseller' : 'customer');
export const visibleTabs = (hub, ctx) => (hub.roles.includes(roleOf(ctx)) ? hub.tabs.filter((tab) => !tab.when || tab.when(ctx)) : []);
// A hub's own address, as opposed to one of its pages.
export const isHubKey = (page) => HUBS.some((hub) => hub.key === page && !hub.tabs.some((tab) => tab.page === page));

// The hub a page is a tab of, for this role, with its visible tabs; null
// when it is in none.
export function hubOf(page, ctx) {
  for (const hub of HUBS) {
    const tabs = visibleTabs(hub, ctx);
    const tab = tabs.find((item) => item.page === page || item.also?.includes(page));
    if (tab) return { hub, tabs, tab };
  }
  return null;
}

// The page a hub's address opens: its first tab this role may see.
export function hubLanding(key, ctx) {
  const hub = HUBS.find((item) => item.key === key);
  return hub ? visibleTabs(hub, ctx)[0]?.page || null : null;
}

// The sidebar of each role: [key, label, icon]. Everyday pages only: an
// addon (Applications, Email, DNS, Git, AI assistants) is opened from its
// Dashboard tile, never from here (operator, 2026-10-18: "Các addon mới cài
// vào không cần hiện trên left sidebar, chỉ cần hiển thị ở Dashboard") -
// except the WordPress Manager, last, while installed (operator,
// 2026-10-19: "Đem Wordpress manager ra menu bên trái (cuối cùng)"), as
// SNPanel has it.
export function sidebarItems(ctx) {
  const wordpress = ctx.wordpressAddonInstalled ? [['wordpress', msg('WordPress Manager'), WordPressGlyph]] : [];
  const common = [
    ['dashboard', msg('Dashboard'), Home],
    ['websites', msg('Websites'), Globe],
    ['ssl', 'SSL', Lock],
    ['databases', msg('Databases'), Database],
    ['cron', msg('Cron'), Clock],
    ['files', msg('Files'), FolderOpen],
    ['backups', msg('Backups'), Archive],
  ];
  if (ctx.isAdmin) {
    return [
      ...common,
      ['users', msg('Panel users'), Users],
      ['server', msg('Server'), Server],
      ['security-center', msg('Security'), ShieldCheck],
      ['config', msg('Settings'), Settings],
      ...wordpress,
    ];
  }
  if (ctx.isReseller) {
    return [...common, ['users', msg('Customers'), Users], ...wordpress];
  }
  return [...common, ...wordpress];
}

// Pages that belong under a sidebar entry without being a tab of it.
const PARENTS = { 'malware-scan': 'security-center', 'waf-site': 'security-center', website: 'websites', sftp: 'files', terminal: 'files' };

// The sidebar entry lit on a page: its hub's, its parent's, or the
// Dashboard's - every other page is reached from there.
export function sidebarKeyOf(page, ctx, items) {
  const keys = new Set(items.map(([key]) => key));
  const found = hubOf(page, ctx);
  if (found && keys.has(found.hub.key)) return found.hub.key;
  if (keys.has(page)) return page;
  if (PARENTS[page] && keys.has(PARENTS[page])) return PARENTS[page];
  return 'dashboard';
}
