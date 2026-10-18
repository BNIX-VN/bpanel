// What needs attention, worst first: the header's bell (operator,
// 2026-10-18: continuing OPanel's own "Needs attention" -> bell move onto
// BPanel). Each item says what is wrong and names the page that fixes it.
//
//   attentionItems({ summary, isAdmin, currentUser, t })
//
// `summary` is /dashboard/summary.

export const TONE_RANK = { bad: 0, warn: 1, info: 2 };

export function attentionItems({ summary, isAdmin, currentUser, t }) {
  if (!summary) return [];
  const items = [];
  const need = (tone, key, text, target, action) => items.push({ tone, key, text, target, action });
  const sites = summary.websites || {};
  const ssl = summary.ssl || {};
  if (isAdmin) {
    const stopped = summary.services?.stopped || [];
    if (stopped.length) need('bad', 'services', t('Stopped: {names}', { names: stopped.join(', ') }), 'services', t('Open'));
    if (summary.firewall?.enabled === false) need('bad', 'firewall', t('The firewall is off.'), 'firewall', t('Open'));
    const infected = summary.malware?.last_scan?.infected;
    if (infected) need('bad', 'malware', t('The last malware scan found {n} threat(s).', { n: infected }), 'malware', t('Open'));
    if (summary.backups?.failed) need('bad', 'backups', t('{n} scheduled backup(s) failed on their last run.', { n: summary.backups.failed }), 'backups', t('Open'));
    if (summary.waf?.engine === 'off') need('warn', 'waf', t('The WAF engine is not installed.'), 'waf', t('Open'));
    // An addon that is off is not a fault: only the scanner's addon being on
    // while LMD and ClamAV are missing wants a look.
    if (summary.malware?.addon && !summary.malware.installed) need('warn', 'scanner', t('The malware scanner is not installed.'), 'malware', t('Open'));
    if (summary.updates?.update_available) need('info', 'updates', t('Panel update {version} is available.', { version: summary.updates.latest_version }), 'updates', t('Open'));
  }
  if (ssl.unsecured_count) {
    need('warn', 'ssl', t('{n} website(s) without SSL: {domains}', {
      n: ssl.unsecured_count, domains: (ssl.unsecured || []).join(', ') + (ssl.unsecured_count > (ssl.unsecured || []).length ? '…' : ''),
    }), 'ssl', t('Set up SSL'));
  }
  if (sites.suspended) need('warn', 'suspended', t('{n} website(s) suspended.', { n: sites.suspended }), 'websites', t('Open'));
  if (!isAdmin && currentUser && !currentUser.totp_enabled) need('info', 'twofactor', t('Two-factor sign-in is off for your account.'), 'security', t('Turn on'));
  return items.sort((a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone]);
}
