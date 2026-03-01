import React, { useEffect, useMemo, useState } from 'react';
import { Play, X } from 'lucide-react';

const MIN_EVENT_DURATION_SECONDS = 1;
const MAX_EVENT_DURATION_SECONDS = 14 * 24 * 60 * 60;

interface EventLaunchModalProps {
  isOpen: boolean;
  eventTitle: string;
  onClose: () => void;
  onLaunch: (durationSeconds: number) => void;
}

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

export const EventLaunchModal: React.FC<EventLaunchModalProps> = ({
  isOpen,
  eventTitle,
  onClose,
  onLaunch,
}) => {
  const [duration, setDuration] = useState<string>('3600');

  useEffect(() => {
    if (isOpen) {
      setDuration('3600');
    }
  }, [isOpen]);

  const parsedDuration = useMemo(() => Number(duration), [duration]);
  const isValidDuration = useMemo(
    () =>
      Number.isFinite(parsedDuration) &&
      parsedDuration >= MIN_EVENT_DURATION_SECONDS &&
      parsedDuration <= MAX_EVENT_DURATION_SECONDS,
    [parsedDuration],
  );

  if (!isOpen) {
    return null;
  }

  const inputClass = `w-full rounded p-2 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 border transition-all
    bg-slate-50 border-slate-200 text-slate-900 
    dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200`;
  const labelClass = 'block text-xs font-bold uppercase mb-1 text-slate-500 dark:text-slate-500';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidDuration) {
      return;
    }
    onLaunch(Math.floor(parsedDuration));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-lg rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden transition-colors
        bg-white border border-slate-200 
        dark:bg-slate-900 dark:border-slate-700"
      >
        <div
          className="p-5 border-b flex justify-between items-center transition-colors
          bg-white border-slate-200 
          dark:bg-slate-900 dark:border-slate-800"
        >
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">Launch Event</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto">
          <form id="eventLaunchForm" onSubmit={handleSubmit} noValidate className="space-y-4">
            <div className="text-sm text-slate-600 dark:text-slate-300">
              Selected event: <span className="font-semibold">{eventTitle}</span>
            </div>

            <div>
              <label className={labelClass}>Duration (seconds)</label>
              <input
                type="number"
                min={MIN_EVENT_DURATION_SECONDS}
                max={MAX_EVENT_DURATION_SECONDS}
                value={duration}
                onChange={e => setDuration(e.target.value)}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Allowed range: {MIN_EVENT_DURATION_SECONDS}..{MAX_EVENT_DURATION_SECONDS}
              </p>
              {isValidDuration && (
                <p className="mt-1 text-xs text-indigo-600 dark:text-indigo-400">
                  Formatted: {formatDuration(parsedDuration)}
                </p>
              )}
              {!isValidDuration && (
                <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                  Duration must be between {MIN_EVENT_DURATION_SECONDS} and {MAX_EVENT_DURATION_SECONDS}.
                </p>
              )}
            </div>
          </form>
        </div>

        <div
          className="p-4 border-t flex justify-end gap-3 rounded-b-xl transition-colors
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
            form="eventLaunchForm"
            type="submit"
            disabled={!isValidDuration}
            className={`px-4 py-2 rounded-lg font-bold shadow-lg transition-all active:scale-95 flex items-center gap-2 ${
              isValidDuration
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-500/20'
                : 'bg-slate-300 text-slate-500 cursor-not-allowed dark:bg-slate-700 dark:text-slate-400 shadow-none'
            }`}
          >
            <Play className="w-4 h-4" /> Launch Timed
          </button>
        </div>
      </div>
    </div>
  );
};
