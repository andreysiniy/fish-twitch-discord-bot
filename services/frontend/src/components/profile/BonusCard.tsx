import React from 'react';

interface BonusCardProps {
  label: string;
  value: string;
  color: string;
}

export const BonusCard: React.FC<BonusCardProps> = ({ label, value, color }) => (
  <div
    className="p-3 rounded-lg border flex flex-col items-center justify-center
      bg-white/45 border-white/25
      dark:bg-slate-900/45 dark:border-slate-700/50"
  >
    <span className="text-[10px] uppercase tracking-wide mb-1 text-slate-500 dark:text-slate-500">{label}</span>
    <span className={`text-lg font-bold ${color}`}>{value}</span>
  </div>
);
