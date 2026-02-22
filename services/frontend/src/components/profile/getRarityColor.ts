import type { Rarity } from './types';

export const getRarityColor = (rarity: Rarity | undefined): string => {
  switch (rarity) {
    case 'rare':
      return 'border-indigo-500 bg-indigo-500/10 text-indigo-600 dark:text-indigo-300';
    case 'epic':
      return 'border-violet-500 bg-violet-500/10 text-violet-600 dark:text-violet-300';
    case 'legendary':
      return 'border-emerald-500 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-600 dark:bg-slate-700/50 dark:text-slate-300';
  }
};
