import React, { useState } from 'react';
import { LOCATION_BG, MOCK_PROFILE, ProfileHeaderCard, ProfileInventory, ProfileSidebar } from './components/profile';
import type { UserProfile } from './components/profile';

const ProfilePage: React.FC = () => {
  const [profile] = useState<UserProfile>(MOCK_PROFILE);
  const xpPercentage = Math.min(100, Math.round((profile.current_xp / profile.xp_to_next_level) * 100));
  const currentBgImage = LOCATION_BG[profile.location_id] || LOCATION_BG.default;

  return (
    <div className="relative min-h-screen font-sans">
      <div
        className="fixed inset-0 z-0 transition-all duration-1000 ease-in-out"
        style={{
          backgroundImage: `url(${currentBgImage})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      />

      <div
        className="fixed inset-0 z-0 transition-colors duration-300
          bg-slate-50/20
          dark:bg-slate-950/85
          backdrop-blur-[1px] dark:backdrop-blur-[2px]"
      />

      <div className="relative z-10 p-4 md:p-8">
        <div className="max-w-5xl mx-auto space-y-6">
          <ProfileHeaderCard profile={profile} xpPercentage={xpPercentage} />
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <ProfileSidebar profile={profile} />
            <ProfileInventory inventory={profile.inventory} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProfilePage;
