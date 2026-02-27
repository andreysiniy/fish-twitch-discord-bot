import React, { useEffect, useRef, useState } from 'react';
import {
  ChevronDown,
  CircleUserRound,
  LogIn,
  LogOut,
  Settings,
  User,
  Wrench,
  MapPin,
  CalendarDays,
  Package,
} from 'lucide-react';

type ViewMode = 'player' | 'editor';

interface UserProfileMenuProps {
  username: string;
  userAvatarUrl: string;
  isLoggedIn: boolean;
  viewMode: ViewMode;
  onOpenProfile: () => void;
  onToggleAuth: () => void;
  onToggleViewMode: () => void;
  onOpenGlobalConfig: () => void;
  onOpenLocationsSettings: () => void;
  onOpenEventsSettings: () => void;
  onOpenItemsSettings: () => void;
}

interface MenuButtonProps {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}

const MenuButton: React.FC<MenuButtonProps> = ({ label, icon, onClick }) => (
  <button
    onClick={onClick}
    className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors
      text-slate-700 hover:bg-slate-100
      dark:text-slate-200 dark:hover:bg-slate-800"
  >
    {icon}
    {label}
  </button>
);

export const UserProfileMenu: React.FC<UserProfileMenuProps> = ({
  username,
  userAvatarUrl,
  isLoggedIn,
  viewMode,
  onOpenProfile,
  onToggleAuth,
  onToggleViewMode,
  onOpenGlobalConfig,
  onOpenLocationsSettings,
  onOpenEventsSettings,
  onOpenItemsSettings,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const runAction = (action: () => void) => {
    action();
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={wrapperRef}>
      <button
        onClick={() => setIsOpen(prev => !prev)}
        className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 border transition-colors
          bg-white border-slate-200 text-slate-700 hover:bg-slate-50
          dark:bg-slate-900 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        <img
          src={userAvatarUrl}
          alt={username}
          className="w-7 h-7 rounded-full object-cover border border-slate-300 dark:border-slate-600"
        />
        <span className="hidden md:inline text-sm font-medium">{username}</span>
        <ChevronDown className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-72 rounded-xl border shadow-xl p-2 z-50
          bg-white border-slate-200
          dark:bg-slate-900 dark:border-slate-700"
        >
          <div className="px-3 py-2 border-b border-slate-200 dark:border-slate-700">
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Signed in as
            </div>
            <div className="font-semibold text-slate-900 dark:text-slate-100">{username}</div>
          </div>

          <div className="pt-2 space-y-1">
            <MenuButton
              label="Profile"
              icon={<CircleUserRound className="w-4 h-4" />}
              onClick={() => runAction(onOpenProfile)}
            />
            <MenuButton
              label={isLoggedIn ? 'Log out' : 'Log in'}
              icon={isLoggedIn ? <LogOut className="w-4 h-4" /> : <LogIn className="w-4 h-4" />}
              onClick={() => runAction(onToggleAuth)}
            />
            <MenuButton
              label={viewMode === 'player' ? 'View as editor' : 'View as player'}
              icon={viewMode === 'player' ? <Settings className="w-4 h-4" /> : <User className="w-4 h-4" />}
              onClick={() => runAction(onToggleViewMode)}
            />
          </div>

          <div className="my-2 border-t border-slate-200 dark:border-slate-700" />

          <div className="space-y-1">
            <MenuButton
              label="Global config settings"
              icon={<Wrench className="w-4 h-4" />}
              onClick={() => runAction(onOpenGlobalConfig)}
            />
            <MenuButton
              label="Locations settings"
              icon={<MapPin className="w-4 h-4" />}
              onClick={() => runAction(onOpenLocationsSettings)}
            />
            <MenuButton
              label="Events settings"
              icon={<CalendarDays className="w-4 h-4" />}
              onClick={() => runAction(onOpenEventsSettings)}
            />
            <MenuButton
              label="Items settings"
              icon={<Package className="w-4 h-4" />}
              onClick={() => runAction(onOpenItemsSettings)}
            />
          </div>
        </div>
      )}
    </div>
  );
};
