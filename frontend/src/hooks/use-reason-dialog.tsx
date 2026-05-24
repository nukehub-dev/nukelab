import { useState, useCallback } from 'react';
import { Modal } from '../components/ui/modal';
import { Button } from '../components/ui/button';

interface PromptOptions {
  title?: string;
  description?: string;
  actionLabel?: string;
  cancelLabel?: string;
}

interface PromptState extends PromptOptions {
  isOpen: boolean;
  resolve: ((value: string | null) => void) | null;
}

export function useReasonDialog() {
  const [state, setState] = useState<PromptState>({
    isOpen: false,
    title: 'Reason Required',
    resolve: null,
  });
  const [reason, setReason] = useState('');

  const prompt = useCallback((options: PromptOptions): Promise<string | null> => {
    return new Promise((resolve) => {
      setReason('');
      setState({
        ...options,
        title: options.title ?? 'Reason Required',
        isOpen: true,
        resolve,
      });
    });
  }, []);

  const handleClose = useCallback(
    (value: string | null) => {
      state.resolve?.(value);
      setState((prev) => ({ ...prev, isOpen: false, resolve: null }));
      setReason('');
    },
    [state.resolve]
  );

  const dialog = (
    <Modal
      open={state.isOpen}
      onOpenChange={(v) => !v && handleClose(null)}
      showClose={false}
      className="max-w-lg"
    >
      <div className="p-6 space-y-4">
        <div>
          <h3 className="text-lg font-semibold">{state.title}</h3>
          {state.description && (
            <p className="text-sm text-muted-foreground mt-1">{state.description}</p>
          )}
        </div>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Enter reason..."
          className="w-full min-h-[80px] rounded-lg border border-border/60 bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground/50 focus:border-primary/60 focus:ring-1 focus:ring-primary/30 focus:outline-none resize-y transition-colors"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && reason.trim()) {
              e.preventDefault();
              handleClose(reason.trim());
            }
          }}
        />
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 pt-2 border-t border-border/50">
          <Button
            variant="outline"
            onClick={() => handleClose(null)}
            className="w-full sm:w-auto"
          >
            {state.cancelLabel ?? 'Cancel'}
          </Button>
          <Button
            onClick={() => handleClose(reason.trim() || null)}
            disabled={!reason.trim()}
            className="w-full sm:w-auto"
          >
            {state.actionLabel ?? 'Confirm'}
          </Button>
        </div>
      </div>
    </Modal>
  );

  return { prompt, dialog };
}
