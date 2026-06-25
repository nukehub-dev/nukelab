export function ReactorCore404({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 360 360"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Unstable reactor core"
    >
      <style>{`
        .rc-vessel {
          transform-origin: center;
          animation: rc-vessel-breathe 6s ease-in-out infinite;
        }
        @keyframes rc-vessel-breathe {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50% { opacity: 0.8; transform: scale(1.01); }
        }

        .rc-ring {
          transform-origin: center;
        }
        .rc-ring--outer { animation: rc-ring-rotate 16s linear infinite; }
        .rc-ring--middle { animation: rc-ring-rotate 12s linear infinite reverse; }
        .rc-ring--inner { animation: rc-ring-rotate 8s linear infinite; }
        @keyframes rc-ring-rotate {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        .rc-breach-ring {
          transform-origin: center;
          animation: rc-breach-pulse 2.6s ease-in-out infinite;
        }
        @keyframes rc-breach-pulse {
          0%, 100% { opacity: 0.6; stroke-width: 4; }
          50% { opacity: 1; stroke-width: 5; }
        }

        .rc-core-pulse {
          transform-origin: center;
          animation: rc-core-flicker 2.4s ease-in-out infinite;
        }
        @keyframes rc-core-flicker {
          0%, 100% { opacity: 0.7; transform: scale(0.95); }
          50% { opacity: 1; transform: scale(1.2); }
        }

        .rc-core-shell {
          transform-origin: center;
          animation: rc-core-breathe 5s ease-in-out infinite;
        }
        @keyframes rc-core-breathe {
          0%, 100% { transform: scale(1); opacity: 0.85; }
          50% { transform: scale(1.04); opacity: 1; }
        }

        .rc-plasma-bloom {
          transform-origin: center;
          animation: rc-plasma-expand 6s ease-in-out infinite;
        }
        @keyframes rc-plasma-expand {
          0%, 100% { transform: scale(0.94); opacity: 0.75; }
          50% { transform: scale(1.1); opacity: 1; }
        }

        .rc-spark {
          opacity: 0;
          transform-origin: center;
        }
        .rc-spark--1 { animation: rc-spark-vent 2.6s ease-out infinite; }
        .rc-spark--2 { animation: rc-spark-vent 2.6s ease-out infinite; animation-delay: 0.65s; }
        .rc-spark--3 { animation: rc-spark-vent 2.6s ease-out infinite; animation-delay: 1.3s; }
        .rc-spark--4 { animation: rc-spark-vent 2.6s ease-out infinite; animation-delay: 1.95s; }
        @keyframes rc-spark-vent {
          0% { opacity: 0; transform: translate(0, 0) scale(0.5); }
          12% { opacity: 1; }
          100% { opacity: 0; transform: translate(var(--spark-x, 0), var(--spark-y, 0)) scale(0.15); }
        }
        .rc-spark--1 { --spark-x: -20px; --spark-y: -20px; }
        .rc-spark--2 { --spark-x: -26px; --spark-y: -10px; }
        .rc-spark--3 { --spark-x: -12px; --spark-y: -24px; }
        .rc-spark--4 { --spark-x: -22px; --spark-y: -16px; }

        @media (prefers-reduced-motion: reduce) {
          .rc-vessel, .rc-ring, .rc-breach-ring, .rc-core-pulse, .rc-core-shell, .rc-plasma-bloom, .rc-spark {
            animation: none;
          }
        }
      `}</style>

      <defs>
        <filter id="rc-glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="10" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>

        <radialGradient id="rc-plasma-gradient" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="1" />
          <stop offset="50%" stopColor="var(--primary)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
        </radialGradient>

        <linearGradient id="rc-ring-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.8" />
          <stop offset="50%" stopColor="var(--primary)" stopOpacity="0.1" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0.8" />
        </linearGradient>

        <radialGradient id="rc-vessel-gradient" cx="50%" cy="50%" r="50%">
          <stop offset="70%" stopColor="var(--primary)" stopOpacity="0" />
          <stop offset="92%" stopColor="var(--primary)" stopOpacity="0.08" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0.25" />
        </radialGradient>
      </defs>

      <circle
        cx="180"
        cy="180"
        r="150"
        fill="url(#rc-vessel-gradient)"
        stroke="var(--primary)"
        strokeWidth="1"
        strokeOpacity="0.12"
        className="rc-vessel"
      />

      <g fill="none" stroke="url(#rc-ring-gradient)" strokeWidth="2.5">
        <circle cx="180" cy="180" r="124" strokeOpacity="0.22" className="rc-ring rc-ring--outer" />
        <circle cx="180" cy="180" r="96" strokeOpacity="0.32" className="rc-ring rc-ring--middle" />
        <circle cx="180" cy="180" r="68" strokeOpacity="0.42" className="rc-ring rc-ring--inner" />
      </g>

      <path
        d="M 180 84 A 96 96 0 1 1 95 138"
        fill="none"
        stroke="var(--primary)"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.9"
        className="rc-breach-ring"
      />

      <circle
        cx="180"
        cy="180"
        r="48"
        fill="url(#rc-plasma-gradient)"
        className="rc-plasma-bloom"
      />

      <circle
        cx="180"
        cy="180"
        r="30"
        fill="var(--primary)"
        fillOpacity="0.15"
        stroke="var(--primary)"
        strokeWidth="2"
        className="rc-core-shell"
      />

      <circle
        cx="180"
        cy="180"
        r="14"
        fill="var(--primary)"
        className="rc-core-pulse"
        filter="url(#rc-glow)"
      />

      <g fill="var(--primary)">
        <circle cx="110" cy="110" r="2.5" className="rc-spark rc-spark--1" />
        <circle cx="88" cy="128" r="2" className="rc-spark rc-spark--2" />
        <circle cx="128" cy="92" r="2" className="rc-spark rc-spark--3" />
        <circle cx="94" cy="98" r="1.5" className="rc-spark rc-spark--4" />
      </g>
    </svg>
  )
}
