import React from 'react';
import { DraftRewardParams } from '../../../types';

interface Props {
  params: DraftRewardParams;
  onChange: (
    key: keyof DraftRewardParams,
    value: DraftRewardParams[keyof DraftRewardParams],
  ) => void;
  inputClass: string;
  labelClass: string;
}

export const RobberyFields: React.FC<Props> = ({ params, onChange, inputClass, labelClass }) => (
  <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
    <div>
      <div className="flex justify-between items-end mb-2">
        <label className={labelClass}>Steal Percentage</label>
        <span className="text-sm font-mono font-bold text-indigo-600 dark:text-indigo-400">
          {Math.round((params.robbery_percentage ?? 0) * 100)}%
        </span>
      </div>

      <div className="flex items-center gap-4">
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={params.robbery_percentage ?? 0}
          onChange={e => onChange('robbery_percentage', parseFloat(e.target.value))}
          className="flex-1 h-2 rounded-lg appearance-none cursor-pointer accent-indigo-600
            bg-slate-200 hover:bg-slate-300
            dark:bg-slate-800 dark:hover:bg-slate-700"
        />

        <div className="w-20">
          <input
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={params.robbery_percentage ?? ''}
            onChange={e =>
              onChange('robbery_percentage', e.target.value === '' ? null : parseFloat(e.target.value))
            }
            className="w-full text-center text-xs p-1.5 rounded border outline-none focus:border-indigo-500
              bg-slate-50 border-slate-200 text-slate-900
              dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200"
          />
        </div>
      </div>
    </div>

    <div>
      <label className={labelClass}>Fixed Mass</label>
      <input
        type="number"
        step="0.1"
        value={params.robbery_mass ?? ''}
        onChange={e => onChange('robbery_mass', e.target.value === '' ? null : parseFloat(e.target.value))}
        className={inputClass}
      />
    </div>

    <p className="text-[10px] text-slate-500 dark:text-slate-500">
      Set `percentage` or `mass` based on server-side behavior for this reward.
    </p>
  </div>
);
