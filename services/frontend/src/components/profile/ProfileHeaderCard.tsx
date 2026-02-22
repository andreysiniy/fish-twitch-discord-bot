import React from 'react';
import { Anchor } from 'lucide-react';
import type { UserProfile } from './types';

interface ProfileHeaderCardProps {
  profile: UserProfile;
  xpPercentage: number;
}

export const ProfileHeaderCard: React.FC<ProfileHeaderCardProps> = ({ profile, xpPercentage }) => (
  <div
    className="rounded-2xl p-6 shadow-xl relative overflow-hidden transition-colors backdrop-blur-md
      bg-white/60 border border-white/25
      dark:bg-slate-900/80 dark:border-slate-700/50"
  >
    <div className="absolute top-0 right-0 w-64 h-64 bg-indigo-500/20 rounded-full blur-3xl -mr-16 -mt-16 pointer-events-none" />

    <div className="flex flex-col md:flex-row items-center gap-6 relative z-10">
      <div className="w-24 h-24 rounded-full bg-gradient-to-br from-indigo-500 to-emerald-500 p-1 shadow-lg">
        <img
          src={`https://ui-avatars.com/api/?name=${profile.username}&background=0f172a&color=fff`}
          alt="Avatar"
          className="w-full h-full rounded-full object-cover border-2 border-white dark:border-slate-800"
        />
      </div>

      <div className="flex-1 w-full text-center md:text-left">
        <div className="flex items-center justify-center md:justify-start gap-3 mb-1">
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white drop-shadow-sm">{profile.username}</h1>
          <span
            className="text-xs px-2 py-0.5 rounded border
              bg-indigo-50/80 border-indigo-200 text-indigo-700
              dark:bg-indigo-500/20 dark:border-indigo-500/30 dark:text-indigo-300"
          >
            Rank #{profile.rank}
          </span>
        </div>
        <p className="text-sm mb-3 flex items-center justify-center md:justify-start gap-2 text-slate-600 dark:text-slate-400">
          <Anchor className="w-4 h-4" /> Fishing at{' '}
          <span className="text-indigo-600 dark:text-indigo-300 font-medium">{profile.location}</span>
        </p>

        <div
          className="relative w-full h-6 rounded-full overflow-hidden border
            bg-slate-200/50 border-slate-300/50
            dark:bg-slate-950/50 dark:border-slate-700"
        >
          <div
            className="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all duration-500 ease-out"
            style={{ width: `${xpPercentage}%` }}
          />
          <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-slate-800 dark:text-white drop-shadow-sm">
            Lvl {profile.level} - {xpPercentage}% ({profile.current_xp} / {profile.xp_to_next_level} XP)
          </div>
        </div>
      </div>

      <div
        className="p-4 rounded-xl border min-w-[140px] text-center backdrop-blur-sm
          bg-white/45 border-slate-200/40
          dark:bg-slate-900/60 dark:border-slate-700/50"
      >
        <div className="text-xs uppercase tracking-wider mb-1 text-slate-500 dark:text-slate-400">Balance</div>
        <div className="text-xl font-mono font-bold text-emerald-600 dark:text-green-400">
          {profile.balance_se.toLocaleString()} <span className="text-sm">pts</span>
        </div>
      </div>
    </div>
  </div>
);
