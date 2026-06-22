import type { KeyboardEvent } from 'react';

export interface TabItem<T extends string = string> {
  id: T;
  label: string;
  description?: string;
  badge?: string | number;
}

export function TabBar<T extends string>({
  ariaLabel,
  items,
  value,
  onChange,
  compact = false,
}: {
  ariaLabel: string;
  items: readonly TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  compact?: boolean;
}) {
  const tabSetId = ariaLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-');

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();

    let nextIndex = index;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = items.length - 1;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + items.length) % items.length;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % items.length;

    const next = items[nextIndex];
    if (!next) return;
    onChange(next.id);
    requestAnimationFrame(() => {
      document.getElementById(`${tabSetId}-${next.id}-tab`)?.focus();
    });
  }

  return (
    <div className={`tab-bar ${compact ? 'tab-bar-compact' : ''}`} role="tablist" aria-label={ariaLabel}>
      {items.map((item, index) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            id={`${tabSetId}-${item.id}-tab`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`${tabSetId}-${item.id}-panel`}
            tabIndex={active ? 0 : -1}
            className={`tab-bar-item ${active ? 'active' : ''}`}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            <span className="tab-bar-copy">
              <strong>{item.label}</strong>
              {item.description ? <small>{item.description}</small> : null}
            </span>
            {item.badge != null ? <span className="tab-bar-badge">{item.badge}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
