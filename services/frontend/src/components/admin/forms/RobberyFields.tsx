import React from 'react';
import { DraftRewardParams } from '../../../types';

interface Props {
  params: DraftRewardParams;
  onChange: (key: keyof DraftRewardParams, value: any) => void;
  labelClass: string;
}

export const RobberyFields: React.FC<Props> = ({ params, onChange, labelClass }) => (
  <div className="animate-in fade-in slide-in-from-top-2 duration-200 py-2">
    <div className="flex justify-between items-end mb-2">
      <label className={labelClass}>Steal Percentage</label>
      <span className="text-sm font-mono font-bold text-indigo-600 dark:text-indigo-400">
        {Math.round(params.percentage * 100)}%
      </span>
    </div>
    
    <div className="flex items-center gap-4">
      {/* Слайдер настраивается отдельно, так как inputClass здесь не подходит */}
      <input 
        type="range" min="0" max="1" step="0.05"
        value={params.percentage} 
        onChange={e => onChange('percentage', parseFloat(e.target.value))} 
        className="flex-1 h-2 rounded-lg appearance-none cursor-pointer accent-indigo-600
          bg-slate-200 hover:bg-slate-300
          dark:bg-slate-800 dark:hover:bg-slate-700"
      />
      
      <div className="w-20">
        <input 
           type="number" min="0" max="1" step="0.01"
           value={params.percentage}
           onChange={e => onChange('percentage', parseFloat(e.target.value))}
           className="w-full text-center text-xs p-1.5 rounded border outline-none focus:border-indigo-500
             bg-slate-50 border-slate-200 text-slate-900
             dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200"
        />
      </div>
    </div>
    
    <p className="text-[10px] mt-2 text-slate-500 dark:text-slate-500">
      Target will lose this % of their current mass.
    </p>
  </div>
);