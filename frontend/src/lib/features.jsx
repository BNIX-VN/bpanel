// The Dashboard's tiles, as SNPanel and OPanel's own current Dashboard have
// them (operator, 2026-10-18: continuing the SNPanel redesign onto BPanel's
// Dashboard): one per feature, each with its picture (icons/feature), its
// label, where it goes and who sees it - on BPanel's own pages, in the
// grouping its dashboardToolGroups() already used.
const msg = (text) => text;

// A tile: label, icon (a feature icon's name), page, and maybe
//   before   - name of an App action run before navigating (opens a tab/form)
//   after    - name of an App action run after navigating (focuses a field)
//   roles    - who sees it (default: everyone the page lets in)
//   addon    - shown only while this addon is installed
//   when     - one more condition, on the navigation's facts
//   labels   - { reseller } a label of its own for that role
export const TILES = {
  // Accounts
  users: { label: msg('Panel users'), labels: { reseller: msg('Customers') }, icon: 'users', page: 'users', before: 'usersList', roles: ['admin', 'reseller'] },
  'user-add': { label: msg('Add User'), labels: { reseller: msg('Add customer') }, icon: 'user-add', page: 'users', before: 'usersAdd', roles: ['admin', 'reseller'] },
  packages: { label: msg('Packages'), icon: 'packages', page: 'users', before: 'usersPackages', roles: ['admin', 'reseller'] },
  // Websites and domains
  websites: { label: msg('Websites'), icon: 'websites', page: 'websites' },
  'website-add': { label: msg('New website'), icon: 'website-add', page: 'websites', before: 'newWebsite' },
  applications: { label: msg('Applications'), icon: 'applications', page: 'applications', when: (c) => c.appsFeatureEnabled },
  ssl: { label: 'SSL', icon: 'ssl', page: 'ssl' },
  waf: { label: 'WAF', icon: 'waf', page: 'waf' },
  'access-logs': { label: msg('Access logs'), icon: 'access-logs', page: 'access-logs', roles: ['admin'] },
  php: { label: msg('PHP config'), icon: 'php', page: 'php', roles: ['admin'] },
  // Files and backups
  files: { label: msg('File manager'), icon: 'files', page: 'files' },
  sftp: { label: msg('SFTP accounts'), icon: 'sftp', page: 'sftp' },
  'sftp-add': { label: msg('New SFTP account'), icon: 'sftp', page: 'sftp', after: 'focusSftpForm' },
  git: { label: 'Git', icon: 'git', page: 'git', addon: 'git' },
  terminal: { label: msg('Terminal'), icon: 'terminal', page: 'terminal', when: (c) => c.canOpenTerminal },
  backups: { label: msg('Backups'), icon: 'backups', page: 'backups' },
  // Databases
  databases: { label: msg('Databases'), icon: 'databases', page: 'databases' },
  'database-add': { label: msg('New database'), icon: 'database-add', page: 'databases', before: 'newDatabase' },
  phpmyadmin: { label: 'phpMyAdmin', icon: 'phpmyadmin', page: 'databases' },
  // Email
  mailboxes: { label: msg('Mailboxes'), icon: 'mail', page: 'mail', before: 'mailMailboxes', addon: 'mail' },
  forwarders: { label: msg('Forwarders'), icon: 'forwarders', page: 'mail', before: 'mailForwarders', addon: 'mail' },
  'mail-domains': { label: msg('Mail domains'), icon: 'domains', page: 'mail', before: 'mailDomains', addon: 'mail' },
  'mail-relay': { label: msg('SMTP relay'), icon: 'mail-relay', page: 'mail', before: 'mailRelay', addon: 'mail', roles: ['admin'] },
  dns: { label: msg('DNS Manager'), icon: 'dns', page: 'dns', addon: 'dns' },
  // Security
  'account-security': { label: msg('Account security'), icon: 'account-security', page: 'security' },
  firewall: { label: msg('Firewall'), icon: 'firewall', page: 'firewall', roles: ['admin'] },
  malware: { label: msg('Malware Scanner'), icon: 'malware', page: 'malware', addon: 'malware', roles: ['admin'] },
  // Advanced
  cron: { label: msg('Cron'), icon: 'cron', page: 'cron' },
  usage: { label: msg('Resource usage'), icon: 'resource-usage', page: 'usage', roles: ['reseller', 'customer'], when: (c) => c.limitsOn },
  mcp: { label: msg('AI assistants (MCP)'), icon: 'mcp', page: 'mcp', addon: 'mcp' },
  services: { label: msg('Services'), icon: 'services', page: 'services', roles: ['admin'] },
  processes: { label: msg('Processes'), icon: 'processes', page: 'processes', roles: ['admin'] },
  ram: { label: 'RAM', icon: 'ram', page: 'ram-usage', roles: ['admin'] },
  disk: { label: msg('Disk'), icon: 'disk', page: 'disk-usage', roles: ['admin'] },
  traffic: { label: msg('Network traffic'), icon: 'traffic', page: 'traffic', roles: ['admin'] },
  'account-resources': { label: msg('Account resources'), icon: 'resource-usage', page: 'account-resources', roles: ['admin'], when: (c) => c.limitsOn },
  'api-tokens': { label: msg('API tokens'), icon: 'api-tokens', page: 'panel-settings', before: 'apiTokens', roles: ['admin'] },
  notifications: { label: msg('Notifications'), icon: 'notifications', page: 'notifications', addon: 'notifications', roles: ['admin'] },
  updates: { label: msg('Updates'), icon: 'updates', page: 'updates', roles: ['admin'] },
  addons: { label: msg('Addons'), icon: 'addons', page: 'addons', roles: ['admin'] },
  'panel-settings': { label: msg('Panel settings'), icon: 'panel-settings', page: 'panel-settings', roles: ['admin'] },
};

// The Dashboard's sections, in order, for each role - SNPanel's own
// (lib/features.jsx there): Accounts, Websites and domains, Email,
// Databases, Files and backups, Security, Server, Advanced, Extensions.
// Addons are reached from here, not from the sidebar.
const ADMIN = [
  ['accounts', msg('Accounts'), ['users', 'user-add', 'packages']],
  ['websites', msg('Websites and domains'), ['websites', 'website-add', 'ssl', 'dns', 'applications']],
  ['email', msg('Email'), ['mailboxes', 'forwarders', 'mail-domains', 'mail-relay']],
  ['databases', msg('Databases'), ['databases', 'database-add', 'phpmyadmin']],
  ['files', msg('Files and backups'), ['files', 'sftp', 'sftp-add', 'backups', 'git', 'terminal']],
  ['security', msg('Security'), ['firewall', 'waf', 'access-logs', 'malware', 'account-security']],
  ['server', msg('Server'), ['php', 'services', 'processes', 'ram', 'disk', 'traffic', 'account-resources', 'updates']],
  ['advanced', msg('Advanced'), ['cron', 'mcp', 'api-tokens', 'notifications', 'panel-settings']],
  ['extensions', msg('Extensions'), ['addons']],
];
const CUSTOMER = [
  ['websites', msg('Websites and domains'), ['websites', 'website-add', 'ssl', 'dns', 'applications']],
  ['email', msg('Email'), ['mailboxes', 'forwarders', 'mail-domains']],
  ['databases', msg('Databases'), ['databases', 'database-add', 'phpmyadmin']],
  ['files', msg('Files and backups'), ['files', 'sftp', 'sftp-add', 'backups', 'git', 'terminal']],
  ['security', msg('Security'), ['account-security', 'waf']],
  ['advanced', msg('Advanced'), ['cron', 'mcp', 'usage']],
];
const RESELLER = [
  ['accounts', msg('Customers'), ['users', 'user-add', 'packages']],
  ...CUSTOMER,
];

export function dashboardSections(ctx) {
  return ctx.isAdmin ? ADMIN : ctx.isReseller ? RESELLER : CUSTOMER;
}

// Whether a tile is shown to this role, with this server's addons.
export function tileVisible(key, ctx) {
  const tile = TILES[key];
  if (!tile) return false;
  const role = ctx.isAdmin ? 'admin' : ctx.isReseller ? 'reseller' : 'customer';
  if (tile.roles && !tile.roles.includes(role)) return false;
  if (tile.addon && !ctx.installed(tile.addon)) return false;
  if (tile.when && !tile.when(ctx)) return false;
  return true;
}

export const tileLabel = (tile, ctx) => (ctx.isReseller && tile.labels?.reseller) || tile.label;
