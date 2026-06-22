import { useEffect } from 'react';
import type { ReactNode } from 'react';

export function Drawer({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="drawer-overlay" onMouseDown={onClose}>
      <aside className="drawer-panel card rise" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="drawer-panel-header">
          <span className="eyebrow">{title}</span>
          <button type="button" className="btn-ghost drawer-panel-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="drawer-panel-body">{children}</div>
      </aside>
    </div>
  );
}
