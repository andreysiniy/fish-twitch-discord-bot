import React, { useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import ProfilePage from './ProfilePage';
import AdminPanel from './AdminPanel';
import { useTheme } from './hooks/useTheme';
import { ChannelContextBadge } from './components/navbar/ChannelContextBadge';
import { UserProfileMenu } from './components/navbar/UserProfileMenu';

type ViewMode = 'player' | 'editor';
type SettingsSection = 'global' | 'locations' | 'events' | 'items' | null;

const CHANNEL_CONTEXT = {
  name: 'sunowi',
  avatarUrl:
    'https://static-cdn.jtvnw.net/jtv_user_pictures/6dea5372-0b86-4b96-b442-101350301221-profile_image-70x70.png',
};

const USER_CONTEXT = {
  username: 'Guest',
  avatarUrl: 'https://ui-avatars.com/api/?name=Guest&background=334155&color=fff',
};

const App: React.FC = () => {
  const [viewMode, setViewMode] = useState<ViewMode>('player');
  const [isLoggedIn, setIsLoggedIn] = useState(true);
  const [activeSettingsSection, setActiveSettingsSection] = useState<SettingsSection>(null);
  const { theme, toggleTheme } = useTheme();

  const handleOpenProfile = () => {
    setViewMode('player');
    setActiveSettingsSection(null);
  };

  const handleToggleAuth = () => {
    setIsLoggedIn(prev => !prev);
  };

  const handleToggleViewMode = () => {
    setViewMode(prev => (prev === 'player' ? 'editor' : 'player'));
  };

  const openEditorSection = (section: Exclude<SettingsSection, null>) => {
    setViewMode('editor');
    setActiveSettingsSection(section);
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors duration-300">
      <nav
        className="fixed top-0 left-0 right-0 h-14 border-b z-50 px-4 md:px-6 flex items-center justify-between
        bg-white/65 border-slate-200/70 backdrop-blur-md 
        dark:bg-slate-950/70 dark:border-slate-800/70 transition-colors duration-300"
      >
        <div className="font-bold text-lg tracking-tight text-slate-900 dark:text-white">
          Fisher<span className="text-indigo-600 dark:text-indigo-500">Bot</span>
        </div>

        <div className="flex items-center gap-3">
          <ChannelContextBadge
            channelName={CHANNEL_CONTEXT.name}
            channelAvatarUrl={CHANNEL_CONTEXT.avatarUrl}
          />

          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg border transition-all
              bg-white border-slate-200 text-slate-600 hover:bg-slate-50
              dark:bg-slate-900 dark:border-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            title="Toggle Theme"
          >
            {theme === 'light' ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />}
          </button>

          <UserProfileMenu
            username={USER_CONTEXT.username}
            userAvatarUrl={USER_CONTEXT.avatarUrl}
            isLoggedIn={isLoggedIn}
            viewMode={viewMode}
            onOpenProfile={handleOpenProfile}
            onToggleAuth={handleToggleAuth}
            onToggleViewMode={handleToggleViewMode}
            onOpenGlobalConfig={() => openEditorSection('global')}
            onOpenLocationsSettings={() => openEditorSection('locations')}
            onOpenEventsSettings={() => openEditorSection('events')}
            onOpenItemsSettings={() => openEditorSection('items')}
          />
        </div>
      </nav>

      <div className="pt-14">
        {viewMode === 'editor' && activeSettingsSection && (
          <div
            className="px-4 md:px-8 py-2 border-b text-sm
            bg-indigo-50 border-indigo-100 text-indigo-700
            dark:bg-indigo-900/20 dark:border-indigo-900/40 dark:text-indigo-300"
          >
            Opened settings section: <span className="font-semibold">{activeSettingsSection}</span>
          </div>
        )}
        {viewMode === 'player' ? <ProfilePage /> : <AdminPanel />}
      </div>
    </div>
  );
};

export default App;
