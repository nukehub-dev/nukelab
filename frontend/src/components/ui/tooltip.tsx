import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../lib/utils';

type TooltipPosition = 'top' | 'bottom' | 'left' | 'right';

interface TooltipProps {
  content: string;
  children: ReactNode;
  position?: TooltipPosition;
  delay?: number;
  className?: string;
}

export function Tooltip({
  content,
  children,
  position = 'top',
  delay = 300,
  className,
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const [coords, setCoords] = useState({ x: 0, y: 0 });
  const childRef = useRef<HTMLSpanElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      const el = childRef.current;
      if (!el) return;

      const rect = el.getBoundingClientRect();
      let x = rect.left + rect.width / 2;
      let y = rect.top;

      switch (position) {
        case 'top':
          y = rect.top - 8;
          break;
        case 'bottom':
          y = rect.bottom + 8;
          break;
        case 'left':
          x = rect.left - 8;
          y = rect.top + rect.height / 2;
          break;
        case 'right':
          x = rect.right + 8;
          y = rect.top + rect.height / 2;
          break;
      }

      setCoords({ x, y });
      setVisible(true);
    }, delay);
  }, [delay, position]);

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setVisible(false);
  }, []);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  const tooltipStyle: React.CSSProperties = {
    position: 'fixed',
    left: coords.x,
    top: coords.y,
    zIndex: 99999,
  };

  if (position === 'top' || position === 'bottom') {
    tooltipStyle.transform = 'translate(-50%, -100%)';
  } else if (position === 'left') {
    tooltipStyle.transform = 'translate(-100%, -50%)';
  } else {
    tooltipStyle.transform = 'translate(0, -50%)';
  }

  return (
    <>
      <span
        ref={childRef}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        className="inline-flex"
      >
        {children}
      </span>
      {visible && createPortal(
        <div
          className={cn(
            'px-2.5 py-1.5 rounded-md text-xs font-medium shadow-lg',
            'bg-popover text-popover-foreground border border-border',
            'pointer-events-none whitespace-nowrap',
            className
          )}
          style={tooltipStyle}
        >
          {content}
        </div>,
        document.body
      )}
    </>
  );
}

export function IconButtonTooltip({ content, children, position = 'top' }: { content: string; children: ReactNode; position?: TooltipPosition }) {
  return (
    <Tooltip content={content} position={position}>
      {children}
    </Tooltip>
  );
}
