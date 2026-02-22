import React, { useState } from 'react';
import ProfilePage from './ProfilePage';
import AdminPanel from './AdminPanel';
import { User, Settings, Sun, Moon } from 'lucide-react';
import { useTheme } from './hooks/useTheme';

type PageType = 'profile' | 'admin';

const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<PageType>('profile');
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors duration-300">
      
      {/* Navbar */}
      <nav className="fixed top-0 left-0 right-0 h-14 border-b z-50 px-6 flex items-center justify-between
        bg-white/65 border-slate-200/70 backdrop-blur-md 
        dark:bg-slate-950/70 dark:border-slate-800/70 transition-colors duration-300"
      >
        
        {/* Logo */}
        <div className="font-bold text-lg tracking-tight text-slate-900 dark:text-white">
            🎣 Fisher<span className="text-indigo-600 dark:text-indigo-500">Bot</span>
        </div>

        <div className="flex items-center gap-4">
          
          {/* Page Switcher */}
          <div className="flex rounded-lg p-1 border 
            bg-slate-100 border-slate-200 
            dark:bg-slate-900 dark:border-slate-800"
          >
              <button 
                  onClick={() => setCurrentPage('profile')}
                  className={`px-3 py-1.5 rounded flex items-center gap-2 text-sm transition-all font-medium
                    ${currentPage === 'profile' 
                      ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white' 
                      : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
              >
                  <User className="w-4 h-4" /> Profile
              </button>
              <button 
                  onClick={() => setCurrentPage('admin')}
                  className={`px-3 py-1.5 rounded flex items-center gap-2 text-sm transition-all font-medium
                    ${currentPage === 'admin' 
                      ? 'bg-indigo-600 text-white shadow-sm' 
                      : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
              >
                  <Settings className="w-4 h-4" /> Admin
              </button>
          </div>

          {/* Theme Toggle */}
          <button 
            onClick={toggleTheme}
            className="p-2 rounded-lg border transition-all
              bg-white border-slate-200 text-slate-600 hover:bg-slate-50
              dark:bg-slate-900 dark:border-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            title="Toggle Theme"
          >
            {theme === 'light' ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />}
          </button>
        </div>
      </nav>

      {/* Main Content Area */}
      <div className="pt-14">
        {currentPage === 'profile' ? <ProfilePage /> : <AdminPanel />}
      </div>
    </div>
  );
}

export default App;


