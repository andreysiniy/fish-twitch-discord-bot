import React, { useState } from 'react';
import { X } from 'lucide-react';
import { REWARD_TYPES, DEFAULT_PARAMS } from './constants';
import { FishFields } from './forms/FishFields';
import { TimeoutFields } from './forms/TimeoutFields';
import { RouletteFields } from './forms/RouletteFields';
import { RobberyFields } from './forms/RobberyFields';
import { Reward, RewardType, DraftRewardParams } from '../../types';

interface AddRewardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAdd: (reward: Omit<Reward, 'id'>) => void;
}

export const AddRewardModal: React.FC<AddRewardModalProps> = ({ isOpen, onClose, onAdd }) => {
  const [type, setType] = useState<RewardType>('fish');
  const [weight, setWeight] = useState<string>("1000");
  const [message, setMessage] = useState<string>('');
  
  const [params, setParams] = useState<DraftRewardParams>(DEFAULT_PARAMS);

  const handleParamChange = (key: keyof DraftRewardParams, value: any) => {
    setParams(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    const base = { 
        type, 
        weight: parseInt(weight) || 0, 
        message 
    };

    let newReward: any = { ...base };

    switch (type) {
        case 'fish':
            newReward = { ...newReward, min_mass: params.min_mass, max_mass: params.max_mass };
            break;
        case 'timeout':
            newReward = { ...newReward, duration: params.duration, reason: params.reason };
            break;
        case 'russian_roulette':
            newReward = { ...newReward, bullets: params.bullets, chambers: params.chambers };
            break;
        case 'robbery':
            newReward = { ...newReward, percentage: params.percentage };
            break;
        case 'nothing':
            break;
    }

    onAdd(newReward as Omit<Reward, 'id'>);
  };

  if (!isOpen) return null;

  const inputClass = `w-full rounded p-2 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 border transition-all
    bg-slate-50 border-slate-200 text-slate-900 
    dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200`;

  const labelClass = "block text-xs font-bold uppercase mb-1 text-slate-500 dark:text-slate-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-lg rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden transition-colors
        bg-white border border-slate-200 
        dark:bg-slate-900 dark:border-slate-700"
      >
        
        {/* Header */}
        <div className="p-5 border-b flex justify-between items-center transition-colors
          bg-white border-slate-200 
          dark:bg-slate-900 dark:border-slate-800"
        >
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">Add New Event</h2>
          <button 
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto">
          <form id="rewardForm" onSubmit={handleSubmit} className="space-y-6">
            
            {/* Type Selector */}
            <div className="grid grid-cols-5 gap-2">
              {REWARD_TYPES.map(t => {
                const Icon = t.icon;
                const isSelected = type === t.id;
                
                let btnClass = "border transition-all flex flex-col items-center justify-center p-2 rounded-lg ";
                if (isSelected) {
                   btnClass += "bg-indigo-50 border-indigo-500 text-indigo-700 dark:bg-indigo-600/20 dark:border-indigo-500 dark:text-indigo-300";
                } else {
                   btnClass += "bg-slate-50 border-slate-200 text-slate-500 hover:bg-slate-100 dark:bg-slate-950 dark:border-slate-800 dark:text-slate-500 dark:hover:bg-slate-800";
                }

                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setType(t.id)}
                    className={btnClass}
                  >
                    <Icon className="w-5 h-5 mb-1" />
                    <span className="text-[9px] font-bold uppercase">{t.label}</span>
                  </button>
                )
              })}
            </div>

            {/* Base Fields */}
            <div className="grid grid-cols-3 gap-4">
              <div className="col-span-1">
                <label className={labelClass}>Weight</label>
                <input 
                  type="number" required 
                  value={weight} 
                  onChange={e => setWeight(e.target.value)} 
                  className={inputClass}
                />
              </div>
              <div className="col-span-2">
                <label className={labelClass}>Chat Message</label>
                <input 
                  type="text" placeholder="{username} got lucky!" 
                  value={message} onChange={e => setMessage(e.target.value)} 
                  className={inputClass}
                />
              </div>
            </div>

            {/* Dynamic Config Area */}
            <div className="p-4 rounded-lg border min-h-[100px] transition-colors
              bg-slate-50 border-slate-200 
              dark:bg-slate-950/50 dark:border-slate-800/50"
            >
              <h3 className="text-xs font-bold uppercase mb-3 flex items-center gap-2
                text-indigo-600 dark:text-indigo-400"
              >
                 Config: {REWARD_TYPES.find(t => t.id === type)?.label}
              </h3>
              {type === 'fish' && <FishFields params={params} onChange={handleParamChange} inputClass={inputClass} labelClass={labelClass} />}
              {type === 'timeout' && <TimeoutFields params={params} onChange={handleParamChange} inputClass={inputClass} labelClass={labelClass} />}
              {type === 'russian_roulette' && <RouletteFields params={params} onChange={handleParamChange} inputClass={inputClass} labelClass={labelClass} />}
              {type === 'robbery' && <RobberyFields params={params} onChange={handleParamChange} labelClass={labelClass} />}
              {type === 'nothing' && <p className="text-sm text-slate-500 italic">No extra settings.</p>}
            </div>

          </form>
        </div>

        {/* Footer */}
        <div className="p-4 border-t flex justify-end gap-3 rounded-b-xl transition-colors
          bg-slate-50 border-slate-200
          dark:bg-slate-900 dark:border-slate-800"
        >
          <button 
            type="button" 
            onClick={onClose} 
            className="px-4 py-2 font-medium transition-colors rounded-lg
              text-slate-600 hover:bg-slate-200 
              dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800"
          >
            Cancel
          </button>
          <button 
            form="rewardForm" 
            type="submit" 
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-bold shadow-lg shadow-indigo-500/20 transition-all active:scale-95"
          >
            Save Event
          </button>
        </div>
      </div>
    </div>
  );
};