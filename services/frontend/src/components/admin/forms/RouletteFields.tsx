import React from 'react';
import { DraftRewardParams } from '../../../types';

interface Props {
  params: DraftRewardParams;
  onChange: (key: keyof DraftRewardParams, value: any) => void;
  inputClass: string;
  labelClass: string;
}

export const RouletteFields: React.FC<Props> = ({ params, onChange, inputClass, labelClass }) => (
  <div className="grid grid-cols-2 gap-4 animate-in fade-in slide-in-from-top-2 duration-200">
    <div>
      <label className={labelClass}>Bullets</label>
      <input 
        type="number" min="1" max="6"
        value={params.bullets} 
        onChange={e => onChange('bullets', parseInt(e.target.value))} 
        className={inputClass}
      />
    </div>
    <div>
      <label className={labelClass}>Chambers</label>
      <input 
        type="number" min="1" max="100"
        value={params.chambers} 
        onChange={e => onChange('chambers', parseInt(e.target.value))} 
        className={inputClass}
      />
    </div>
  </div>
);