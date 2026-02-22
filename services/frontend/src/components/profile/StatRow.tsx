import React from 'react';

interface StatRowProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  highlight?: boolean;
}

export const StatRow: React.FC<StatRowProps> = ({ icon, label, value, highlight }) => (
  <div className="flex items-center justify-between p-2 rounded transition-colors hover:bg-slate-100/50 dark:hover:bg-slate-800/40">
    <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
      <span className="text-slate-400 dark:text-slate-500">{icon}</span>
      {label}
    </div>
    <span
      className={`font-mono font-bold ${
        highlight ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-900 dark:text-white'
      }`}
    >
      {value}
    </span>
  </div>
);
