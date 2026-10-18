import { useEffect, useRef, useState } from 'react';
import { Bell, CircleAlert, CircleCheck, OctagonAlert, RefreshCw } from 'lucide-react';
import { attentionItems } from '../lib/attention.js';
import { t } from '../i18n.js';
import './NotificationBell.css';

// The header's bell (operator, 2026-10-18): what needs attention, on every
// page - the Dashboard's "Needs attention" card moved here, as OPanel's own
// did. A count on the bell in the worst item's colour; the list opens under
// it, each item with the way to the page that fixes it.
export default function NotificationBell({ summary, checking, isAdmin, currentUser, navigateToPage, onRefresh }) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event) => { if (!boxRef.current?.contains(event.target)) setOpen(false); };
    const onKey = (event) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const items = attentionItems({ summary, isAdmin, currentUser, t });
  const worst = items[0]?.tone || '';
  const label = items.length ? t('{count} thing(s) need attention', { count: items.length }) : t('Notifications');

  return <div className="notify-bell" ref={boxRef}>
    <button type="button" className={`top-tool notify-bell-trigger${worst ? ` tone-${worst}` : ''}`}
      onClick={() => setOpen((value) => !value)} aria-haspopup="dialog" aria-expanded={open} aria-label={label} title={label}>
      <Bell size={16} aria-hidden="true"/>
      {items.length > 0 && <span className="notify-bell-count" aria-hidden="true">{items.length > 9 ? '9+' : items.length}</span>}
    </button>
    {open && <div className="notify-panel" role="dialog" aria-label={t('Needs attention')}>
      <div className="notify-panel-head">
        <strong>{t('Needs attention')}</strong>
        <button type="button" className="secondary icon-only mini" onClick={onRefresh} disabled={checking}
          aria-label={t('Check again')} title={t('Check again')}><RefreshCw size={14} className={checking ? 'spin' : ''} aria-hidden="true"/></button>
      </div>
      {!summary
        ? <div className="attention-ok is-pending" aria-busy="true"><RefreshCw size={16} className="spin" aria-hidden="true"/> {t('Checking…')}</div>
        : items.length === 0
          ? <div className="attention-ok"><CircleCheck size={16} aria-hidden="true"/> {t('Everything is fine.')}</div>
          : <div className="attention-list notify-list">
            {items.map((item) => <div key={item.key} className={`attention-item tone-${item.tone}`}>
              {item.tone === 'bad' ? <OctagonAlert size={15} aria-hidden="true"/> : item.tone === 'info' ? <RefreshCw size={15} aria-hidden="true"/> : <CircleAlert size={15} aria-hidden="true"/>}
              <span>{item.text}</span>
              <button type="button" className="mini secondary" onClick={() => { setOpen(false); navigateToPage(item.target); }}>{item.action}</button>
            </div>)}
          </div>}
    </div>}
  </div>;
}
