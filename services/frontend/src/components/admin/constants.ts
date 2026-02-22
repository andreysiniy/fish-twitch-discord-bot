import { Fish, Skull, Swords, Clock, Ban, LucideIcon } from 'lucide-react';
import { RewardType, DraftRewardParams } from '../../types';

interface RewardTypeConfig {
  id: RewardType;
  label: string;
  icon: LucideIcon;
  color: string;
  bg: string;
}

export const REWARD_TYPES: RewardTypeConfig[] = [
  { 
    id: 'fish', label: 'Fish / Item', icon: Fish, 
    color: 'text-blue-600 dark:text-blue-400', 
    bg: 'bg-blue-50 dark:bg-blue-500/10' 
  },
  { 
    id: 'russian_roulette', label: 'Roulette', icon: Skull, 
    color: 'text-red-600 dark:text-red-400', 
    bg: 'bg-red-50 dark:bg-red-500/10' 
  },
  { 
    id: 'robbery', label: 'Robbery', icon: Swords, 
    color: 'text-purple-600 dark:text-purple-400', 
    bg: 'bg-purple-50 dark:bg-purple-500/10' 
  },
  { 
    id: 'timeout', label: 'Timeout', icon: Clock, 
    color: 'text-orange-600 dark:text-orange-400', 
    bg: 'bg-orange-50 dark:bg-orange-500/10' 
  },
  { 
    id: 'nothing', label: 'Nothing', icon: Ban, 
    color: 'text-slate-500 dark:text-slate-400', 
    bg: 'bg-slate-100 dark:bg-slate-500/10' 
  },
];

export const DEFAULT_PARAMS: DraftRewardParams = {
  min_mass: 0.1,
  max_mass: 1.0,
  duration: 60,
  reason: '',
  bullets: 1,
  chambers: 6,
  percentage: 0.1,
};