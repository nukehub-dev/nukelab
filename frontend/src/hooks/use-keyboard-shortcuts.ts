import { useEffect, useCallback } from 'react';
import { useNavigate } from '@tanstack/react-router';

interface Shortcut {
  key: string;
  modifiers?: ('ctrl' | 'alt' | 'shift' | 'meta')[];
  description: string;
  action: () => void;
  preventDefault?: boolean;
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = event.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        // Allow Escape even in inputs
        if (event.key !== 'Escape') return;
      }

      for (const shortcut of shortcuts) {
        const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase();
        
        const modifiersMatch = (shortcut.modifiers ?? []).every((mod) => {
          switch (mod) {
            case 'ctrl':
              return event.ctrlKey;
            case 'alt':
              return event.altKey;
            case 'shift':
              return event.shiftKey;
            case 'meta':
              return event.metaKey;
            default:
              return false;
          }
        });

        if (keyMatch && modifiersMatch) {
          if (shortcut.preventDefault !== false) {
            event.preventDefault();
          }
          shortcut.action();
          break;
        }
      }
    },
    [shortcuts]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}

// Global shortcuts for the app
export function useGlobalShortcuts() {
  const navigate = useNavigate();

  useKeyboardShortcuts([
    {
      key: '?',
      description: 'Show keyboard shortcuts help',
      action: () => {
        // Dispatch custom event to show shortcuts modal
        window.dispatchEvent(new CustomEvent('show-shortcuts'));
      },
    },
    {
      key: '/',
      description: 'Focus search',
      action: () => {
        const searchInput = document.querySelector('[data-search-input]') as HTMLInputElement;
        searchInput?.focus();
      },
    },
    {
      key: 'Escape',
      description: 'Close modal/drawer',
      action: () => {
        // Close any open modals/drawers
        const closeButtons = document.querySelectorAll('[data-modal-close], [data-drawer-close]');
        closeButtons.forEach((btn) => (btn as HTMLButtonElement).click());
      },
    },
    {
      key: 'd',
      modifiers: ['ctrl'],
      description: 'Go to Dashboard',
      action: () => navigate({ to: '/' }),
    },
    {
      key: 's',
      modifiers: ['ctrl'],
      description: 'Go to Servers',
      action: () => navigate({ to: '/servers' }),
    },
    {
      key: 'e',
      modifiers: ['ctrl'],
      description: 'Go to Environments',
      action: () => navigate({ to: '/environments' }),
    },
    {
      key: 'u',
      modifiers: ['ctrl'],
      description: 'Go to Users',
      action: () => navigate({ to: '/users' }),
    },
    {
      key: 'n',
      modifiers: ['ctrl'],
      description: 'New Server',
      action: () => {
        window.dispatchEvent(new CustomEvent('new-server'));
      },
    },
  ]);
}

// Hook to get all available shortcuts
export function useShortcutsList(): Shortcut[] {
  const navigate = useNavigate();

  return [
    {
      key: '?',
      description: 'Show keyboard shortcuts help',
      action: () => {},
    },
    {
      key: '/',
      description: 'Focus search',
      action: () => {},
    },
    {
      key: 'Escape',
      description: 'Close modal/drawer',
      action: () => {},
    },
    {
      key: 'd',
      modifiers: ['ctrl'],
      description: 'Go to Dashboard',
      action: () => navigate({ to: '/' }),
    },
    {
      key: 's',
      modifiers: ['ctrl'],
      description: 'Go to Servers',
      action: () => navigate({ to: '/servers' }),
    },
    {
      key: 'e',
      modifiers: ['ctrl'],
      description: 'Go to Environments',
      action: () => navigate({ to: '/environments' }),
    },
    {
      key: 'u',
      modifiers: ['ctrl'],
      description: 'Go to Users',
      action: () => navigate({ to: '/users' }),
    },
    {
      key: 'n',
      modifiers: ['ctrl'],
      description: 'New Server',
      action: () => {},
    },
  ];
}
