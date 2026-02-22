import React from 'react';
import { Anchor, Fish, Star, TrendingUp, Trophy } from 'lucide-react';
import { BonusCard } from './BonusCard';
import { StatRow } from './StatRow';
import type { UserProfile } from './types';

interface ProfileSidebarProps {
  profile: UserProfile;
}

export const ProfileSidebar: React.FC<ProfileSidebarProps> = ({ profile }) => (
  <div className="space-y-6 lg:col-span-1">
    <div
      className="rounded-xl p-5 border shadow-lg transition-colors backdrop-blur-md
        bg-white/60 border-white/25
        dark:bg-slate-900/80 dark:border-slate-700/50"
    >
      <h2 className="text-lg font-bold mb-4 flex items-center gap-2 text-slate-900 dark:text-white">
        <TrendingUp className="w-5 h-5 text-indigo-600 dark:text-indigo-400" /> Statistics
      </h2>
      <div className="space-y-3">
        <StatRow icon={<Fish className="w-4 h-4" />} label="Total Catches" value={profile.total_fish_stat} />
        <StatRow icon={<Anchor className="w-4 h-4" />} label="Total Mass" value={`${profile.total_mass_stat.toFixed(1)} kg`} />
        <StatRow icon={<Trophy className="w-4 h-4" />} label="Global Rank" value={`#${profile.rank}`} highlight />
      </div>
    </div>

    <div
      className="rounded-xl p-5 border shadow-lg transition-colors backdrop-blur-md
        bg-white/60 border-white/25
        dark:bg-slate-900/80 dark:border-slate-700/50"
    >
      <h2 className="text-lg font-bold mb-4 flex items-center gap-2 text-slate-900 dark:text-white">
        <Star className="w-5 h-5 text-emerald-500 dark:text-emerald-400" /> Active Bonuses
      </h2>
      <div className="grid grid-cols-2 gap-3">
        <BonusCard label="Luck" value={`+${(profile.stats.luck_bonus * 100).toFixed(0)}%`} color="text-emerald-600 dark:text-emerald-400" />
        <BonusCard label="Resist" value={`+${(profile.stats.resist_bonus * 100).toFixed(0)}%`} color="text-red-600 dark:text-red-400" />
        <BonusCard label="XP Gain" value={`+${(profile.stats.xp_bonus_pct * 100).toFixed(0)}%`} color="text-indigo-600 dark:text-indigo-400" />
        <BonusCard label="Bag Wgt" value={`${profile.current_mass.toFixed(1)} kg`} color="text-slate-700 dark:text-slate-300" />
      </div>
    </div>
  </div>
);
