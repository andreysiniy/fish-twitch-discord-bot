import React, { useEffect, useMemo, useState } from 'react';
import { RotateCcw, X } from 'lucide-react';
import { GameParamsConfig } from '../../types';
import { GAME_PARAM_LABELS } from './gameParamLabels';

interface GlobalSettingsModalProps {
  isOpen: boolean;
  initialValues: GameParamsConfig;
  onClose: () => void;
  onSave: (values: GameParamsConfig) => void;
}

const MIN_COOLDOWN_SECONDS = 0;
const MAX_COOLDOWN_SECONDS = 24 * 60 * 60;

export const DEFAULT_GAME_PARAMS: GameParamsConfig = {
  xp_base: 100,
  xp_exponent: 1.5,
  sell_max_bonus: 2.0,
  sell_mid_level: 50,
  sell_rate: 100,
  buy_rate: 120,
  rob_min_chance: 0.05,
  rob_max_chance: 0.95,
  rob_resist_divisor: 100,
  rob_loss_divisor: 50,
  rob_base_chance: 0.8,
  fishing_cooldown: 600,
  subs_fishing_cooldown: 300,
};

const formatDuration = (rawSeconds: number): string => {
  const totalSeconds = Math.max(0, Math.floor(rawSeconds));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const parts: string[] = [];
  if (days > 0) {
    parts.push(`${days}d`);
  }
  if (hours > 0) {
    parts.push(`${hours}h`);
  }
  if (minutes > 0) {
    parts.push(`${minutes}m`);
  }
  if (seconds > 0 || parts.length === 0) {
    parts.push(`${seconds}s`);
  }

  return parts.join(' ');
};

const validateForm = (form: GameParamsConfig): string[] => {
  const errors: string[] = [];

  if (form.xp_base < 0) {
    errors.push(`${GAME_PARAM_LABELS.xp_base} must be >= 0`);
  }
  if (form.xp_base > 10000) {
    errors.push(`${GAME_PARAM_LABELS.xp_base} must be <= 10000`);
  }
  if (form.xp_exponent < 1) {
    errors.push(`${GAME_PARAM_LABELS.xp_exponent} must be >= 1`);
  }
  if (form.xp_exponent > 5) {
    errors.push(`${GAME_PARAM_LABELS.xp_exponent} must be <= 5`);
  }

  if (form.sell_rate < 1) {
    errors.push(`${GAME_PARAM_LABELS.sell_rate} must be >= 1`);
  }
  if (form.sell_rate > 100000) {
    errors.push(`${GAME_PARAM_LABELS.sell_rate} must be <= 100000`);
  }
  if (form.buy_rate < 1) {
    errors.push(`${GAME_PARAM_LABELS.buy_rate} must be >= 1`);
  }
  if (form.buy_rate > 100000) {
    errors.push(`${GAME_PARAM_LABELS.buy_rate} must be <= 100000`);
  }

  if (form.rob_resist_divisor <= 0) {
    errors.push(`${GAME_PARAM_LABELS.rob_resist_divisor} must be > 0`);
  }
  if (form.rob_loss_divisor <= 0) {
    errors.push(`${GAME_PARAM_LABELS.rob_loss_divisor} must be > 0`);
  }

  if (form.rob_min_chance < 0 || form.rob_min_chance > 1) {
    errors.push(`${GAME_PARAM_LABELS.rob_min_chance} must be between 0 and 1`);
  }
  if (form.rob_max_chance < 0 || form.rob_max_chance > 1) {
    errors.push(`${GAME_PARAM_LABELS.rob_max_chance} must be between 0 and 1`);
  }
  if (form.rob_base_chance < 0 || form.rob_base_chance > 1) {
    errors.push(`${GAME_PARAM_LABELS.rob_base_chance} must be between 0 and 1`);
  }
  if (form.rob_min_chance > form.rob_max_chance) {
    errors.push(`${GAME_PARAM_LABELS.rob_min_chance} must be <= ${GAME_PARAM_LABELS.rob_max_chance}`);
  }

  if (
    form.fishing_cooldown < MIN_COOLDOWN_SECONDS ||
    form.fishing_cooldown > MAX_COOLDOWN_SECONDS
  ) {
    errors.push(
      `${GAME_PARAM_LABELS.fishing_cooldown} must be between ${MIN_COOLDOWN_SECONDS} and ${MAX_COOLDOWN_SECONDS}`,
    );
  }
  if (
    form.subs_fishing_cooldown < MIN_COOLDOWN_SECONDS ||
    form.subs_fishing_cooldown > MAX_COOLDOWN_SECONDS
  ) {
    errors.push(
      `${GAME_PARAM_LABELS.subs_fishing_cooldown} must be between ${MIN_COOLDOWN_SECONDS} and ${MAX_COOLDOWN_SECONDS}`,
    );
  }

  return errors;
};

export const GlobalSettingsModal: React.FC<GlobalSettingsModalProps> = ({
  isOpen,
  initialValues,
  onClose,
  onSave,
}) => {
  const [form, setForm] = useState<GameParamsConfig>(initialValues);

  useEffect(() => {
    if (isOpen) {
      setForm(initialValues);
    }
  }, [isOpen, initialValues]);

  const errors = useMemo(() => validateForm(form), [form]);
  const hasErrors = errors.length > 0;

  if (!isOpen) {
    return null;
  }

  const inputClass = `w-full rounded p-2 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 border transition-all
    bg-slate-50 border-slate-200 text-slate-900 
    dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200`;
  const labelClass = 'block text-xs font-bold uppercase mb-1 text-slate-500 dark:text-slate-500';

  const setNumber = (key: keyof GameParamsConfig, value: string) => {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      setForm(prev => ({ ...prev, [key]: parsed }));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (hasErrors) {
      return;
    }
    onSave(form);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-4xl rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden transition-colors
        bg-white border border-slate-200 
        dark:bg-slate-900 dark:border-slate-700"
      >
        <div
          className="p-5 border-b flex justify-between items-center transition-colors
          bg-white border-slate-200 
          dark:bg-slate-900 dark:border-slate-800"
        >
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">Global Config Settings</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto">
          <form id="globalSettingsForm" onSubmit={handleSubmit} className="space-y-5">
            {hasErrors && (
              <div className="rounded-lg border p-3 text-sm bg-red-50 border-red-200 text-red-700 dark:bg-red-900/20 dark:border-red-900/50 dark:text-red-300">
                <div className="font-semibold mb-1">Validation errors:</div>
                <ul className="list-disc list-inside">
                  {errors.map(err => (
                    <li key={err}>{err}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 rounded-lg border bg-slate-50 border-slate-200 dark:bg-slate-950/50 dark:border-slate-800/50">
                <h3 className="text-xs font-bold uppercase mb-3 text-indigo-600 dark:text-indigo-400">XP</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.xp_base}</label>
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      value={form.xp_base}
                      onChange={e => setNumber('xp_base', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.xp_exponent}</label>
                    <input
                      type="number"
                      step="0.01"
                      min={1}
                      max={5}
                      value={form.xp_exponent}
                      onChange={e => setNumber('xp_exponent', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-lg border bg-slate-50 border-slate-200 dark:bg-slate-950/50 dark:border-slate-800/50">
                <h3 className="text-xs font-bold uppercase mb-3 text-indigo-600 dark:text-indigo-400">Sell / Buy</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.sell_max_bonus}</label>
                    <input
                      type="number"
                      step="0.01"
                      value={form.sell_max_bonus}
                      onChange={e => setNumber('sell_max_bonus', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.sell_mid_level}</label>
                    <input
                      type="number"
                      min={0}
                      value={form.sell_mid_level}
                      onChange={e => setNumber('sell_mid_level', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.sell_rate}</label>
                    <input
                      type="number"
                      min={1}
                      max={100000}
                      value={form.sell_rate}
                      onChange={e => setNumber('sell_rate', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.buy_rate}</label>
                    <input
                      type="number"
                      min={1}
                      max={100000}
                      value={form.buy_rate}
                      onChange={e => setNumber('buy_rate', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-lg border bg-slate-50 border-slate-200 dark:bg-slate-950/50 dark:border-slate-800/50">
                <h3 className="text-xs font-bold uppercase mb-3 text-indigo-600 dark:text-indigo-400">Robbery</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.rob_min_chance}</label>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      value={form.rob_min_chance}
                      onChange={e => setNumber('rob_min_chance', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.rob_max_chance}</label>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      value={form.rob_max_chance}
                      onChange={e => setNumber('rob_max_chance', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.rob_resist_divisor}</label>
                    <input
                      type="number"
                      step="1"
                      min={1}
                      value={form.rob_resist_divisor}
                      onChange={e => setNumber('rob_resist_divisor', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.rob_loss_divisor}</label>
                    <input
                      type="number"
                      step="1"
                      min={1}
                      value={form.rob_loss_divisor}
                      onChange={e => setNumber('rob_loss_divisor', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div className="col-span-2">
                    <label className={labelClass}>{GAME_PARAM_LABELS.rob_base_chance}</label>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      value={form.rob_base_chance}
                      onChange={e => setNumber('rob_base_chance', e.target.value)}
                      className={inputClass}
                    />
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-lg border bg-slate-50 border-slate-200 dark:bg-slate-950/50 dark:border-slate-800/50">
                <h3 className="text-xs font-bold uppercase mb-3 text-indigo-600 dark:text-indigo-400">Cooldown</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.fishing_cooldown}</label>
                    <input
                      type="number"
                      min={MIN_COOLDOWN_SECONDS}
                      max={MAX_COOLDOWN_SECONDS}
                      value={form.fishing_cooldown}
                      onChange={e => setNumber('fishing_cooldown', e.target.value)}
                      className={inputClass}
                    />
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {form.fishing_cooldown}s = {formatDuration(form.fishing_cooldown)}
                    </p>
                  </div>
                  <div>
                    <label className={labelClass}>{GAME_PARAM_LABELS.subs_fishing_cooldown}</label>
                    <input
                      type="number"
                      min={MIN_COOLDOWN_SECONDS}
                      max={MAX_COOLDOWN_SECONDS}
                      value={form.subs_fishing_cooldown}
                      onChange={e => setNumber('subs_fishing_cooldown', e.target.value)}
                      className={inputClass}
                    />
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {form.subs_fishing_cooldown}s = {formatDuration(form.subs_fishing_cooldown)}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </form>
        </div>

        <div
          className="p-4 border-t flex items-center justify-between gap-3 rounded-b-xl transition-colors
          bg-slate-50 border-slate-200
          dark:bg-slate-900 dark:border-slate-800"
        >
          <button
            type="button"
            onClick={() => setForm(DEFAULT_GAME_PARAMS)}
            className="px-4 py-2 font-medium rounded-lg transition-colors flex items-center gap-2
              text-slate-700 bg-slate-200 hover:bg-slate-300
              dark:text-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700"
          >
            <RotateCcw className="w-4 h-4" /> Reset Defaults
          </button>

          <div className="flex items-center gap-3">
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
              form="globalSettingsForm"
              type="submit"
              disabled={hasErrors}
              className={`px-4 py-2 rounded-lg font-bold shadow-lg transition-all active:scale-95 ${
                hasErrors
                  ? 'bg-slate-300 text-slate-500 cursor-not-allowed dark:bg-slate-700 dark:text-slate-400 shadow-none'
                  : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-500/20'
              }`}
            >
              Save Global Settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
