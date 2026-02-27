import React from 'react';

interface ChannelContextBadgeProps {
  channelName: string;
  channelAvatarUrl: string;
}

export const ChannelContextBadge: React.FC<ChannelContextBadgeProps> = ({
  channelName,
  channelAvatarUrl,
}) => {
  return (
    <div
      className="hidden sm:flex items-center gap-2 rounded-xl px-3 py-1.5 border
      bg-slate-100/80 border-slate-200 text-slate-700
      dark:bg-slate-900/80 dark:border-slate-700 dark:text-slate-300"
      title={`Currently viewing channel ${channelName}`}
    >
      <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Currently viewing channel
      </div>
      <div className="font-semibold text-sm text-slate-900 dark:text-slate-100">{channelName}</div>
      <img
        src={channelAvatarUrl}
        alt={channelName}
        className="w-7 h-7 rounded-full object-cover border border-slate-300 dark:border-slate-600"
      />
    </div>
  );
};
