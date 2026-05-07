import { createFileRoute } from '@tanstack/react-router';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Mail, 
  Shield, 
  Zap, 
  Calendar,
  Clock,
  Pencil,
  X,
  Check,
  Globe,
  ToggleLeft,
  ToggleRight,
  UserCircle
} from 'lucide-react';
import { useState } from 'react';
import { useAuthStore } from '../stores/auth-store';
import { useToast } from '../stores/toast-store';
import { cn } from '../lib/utils';

export const Route = createFileRoute('/profile')({
  component: ProfilePage,
});

const API_BASE = import.meta.env.VITE_API_URL || '/api';

function ProfilePage() {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const { success: toastSuccess, error: toastError } = useToast();
  
  const [showEditModal, setShowEditModal] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  
  const [editForm, setEditForm] = useState({
    first_name: user?.first_name || '',
    last_name: user?.last_name || '',
    email: user?.email || '',
  });

  if (!user) return null;

  const useGravatar = user.preferences?.use_gravatar !== false;
  
  const handleSave = async () => {
    setIsSaving(true);
    try {
      const token = localStorage.getItem('nukelab-token');
      const res = await fetch(`${API_BASE}/users/me/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify(editForm),
      });
      
      if (!res.ok) throw new Error('Failed to update profile');
      
      const updated = await res.json();
      setUser({ ...user, ...updated });
      toastSuccess('Profile updated', 'Your profile has been updated successfully');
      setShowEditModal(false);
    } catch {
      toastError('Update failed', 'Failed to update your profile');
    } finally {
      setIsSaving(false);
    }
  };

  const toggleGravatar = async () => {
    try {
      const token = localStorage.getItem('nukelab-token');
      const newPrefs = { ...user.preferences, use_gravatar: !useGravatar };
      
      const res = await fetch(`${API_BASE}/preferences/`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify(newPrefs),
      });
      
      if (!res.ok) throw new Error('Failed to update preferences');
      
      const userRes = await fetch(`${API_BASE}/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (userRes.ok) {
        const fresh = await userRes.json();
        setUser(fresh);
      }
      
      toastSuccess(
        !useGravatar ? 'Gravatar enabled' : 'Custom avatar enabled',
        !useGravatar ? 'Your Gravatar is now being used' : 'Using default avatar'
      );
    } catch {
      toastError('Update failed', 'Failed to update preferences');
    }
  };

  const openEdit = () => {
    setEditForm({
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      email: user.email || '',
    });
    setShowEditModal(true);
  };

  const formatDate = (date?: string) => {
    if (!date) return 'Never';
    return new Date(date).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  };

  const displayName = user.first_name && user.last_name 
    ? `${user.first_name} ${user.last_name}`
    : user.display_name || user.username;

  const initials = displayName.charAt(0).toUpperCase();

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-10 pt-6 lg:pt-8">
      {/* Edit Modal */}
      <AnimatePresence>
        {showEditModal && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
              onClick={() => setShowEditModal(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none"
            >
              <div className="w-full max-w-md bg-card/80 backdrop-blur-2xl border border-border/50 rounded-2xl shadow-2xl pointer-events-auto"
              >
                <div className="p-6 space-y-6">
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl font-bold">Edit Profile</h2>
                    <button 
                      onClick={() => setShowEditModal(false)}
                      className="p-2 rounded-lg hover:bg-muted transition-colors"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </div>

                  <div className="space-y-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-muted-foreground">First Name</label>
                      <input
                        type="text"
                        value={editForm.first_name}
                        onChange={(e) => setEditForm({ ...editForm, first_name: e.target.value })}
                        className="w-full px-4 py-3 rounded-xl bg-input/60 border border-border/60 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
                        placeholder="Enter first name"
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-muted-foreground">Last Name</label>
                      <input
                        type="text"
                        value={editForm.last_name}
                        onChange={(e) => setEditForm({ ...editForm, last_name: e.target.value })}
                        className="w-full px-4 py-3 rounded-xl bg-input/60 border border-border/60 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
                        placeholder="Enter last name"
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-muted-foreground">Email</label>
                      <input
                        type="email"
                        value={editForm.email}
                        onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                        className="w-full px-4 py-3 rounded-xl bg-input/60 border border-border/60 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
                        placeholder="Enter email"
                      />
                    </div>
                  </div>

                  <div className="flex gap-3 pt-2">
                    <button
                      onClick={() => setShowEditModal(false)}
                      className="flex-1 px-4 py-3 rounded-xl bg-muted text-muted-foreground hover:bg-muted/80 transition-colors text-sm font-medium"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={isSaving}
                      className="flex-1 px-4 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors text-sm font-medium disabled:opacity-50 shadow-lg shadow-primary/20"
                    >
                      {isSaving ? 'Saving...' : 'Save Changes'}
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Profile Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-card/40 backdrop-blur-2xl border border-border/40 rounded-2xl p-8 relative overflow-hidden"
      >
        <div className="absolute top-0 right-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />
        <div className="relative flex items-center gap-6">
          {/* Avatar */}
          <div className="relative">
            {user.avatar_url && useGravatar ? (
              <img 
                src={user.avatar_url} 
                alt={displayName}
                className="w-24 h-24 rounded-2xl object-cover ring-2 ring-border/50"
              />
            ) : (
              <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-primary/30 to-primary/10 ring-2 ring-primary/30 flex items-center justify-center text-3xl font-bold text-primary">
                {initials}
              </div>
            )}
            <div className={cn(
              "absolute -bottom-1.5 -right-1.5 w-6 h-6 rounded-full border-2 border-card flex items-center justify-center",
              user.is_active ? "bg-green-500" : "bg-red-500"
            )}>
              <div className="w-2 h-2 rounded-full bg-white" />
            </div>
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold">{displayName}</h1>
            <p className="text-muted-foreground mt-0.5">@{user.username}</p>
            
            <div className="flex items-center gap-3 mt-3">
              <span className={cn(
                "px-2.5 py-0.5 rounded-full text-xs font-medium border capitalize",
                user.role === 'admin' && "bg-orange-500/10 text-orange-400 border-orange-500/20",
                user.role === 'super_admin' && "bg-red-500/10 text-red-400 border-red-500/20",
                user.role === 'moderator' && "bg-blue-500/10 text-blue-400 border-blue-500/20",
                user.role === 'user' && "bg-primary/10 text-primary border-primary/20"
              )}>
                {user.role.replace('_', ' ')}
              </span>
              <span className="text-sm text-muted-foreground">{user.email}</span>
            </div>
          </div>

          <button
            onClick={openEdit}
            className="px-5 py-2.5 rounded-xl bg-primary/10 text-primary hover:bg-primary/20 transition-all text-sm font-medium flex items-center gap-2 backdrop-blur-sm"
          >
            <Pencil className="w-4 h-4" />
            Edit Profile
          </button>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Account Details */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-card/40 backdrop-blur-2xl border border-border/40 rounded-2xl p-6 relative overflow-hidden"
        >
          <div className="absolute bottom-0 left-0 w-48 h-48 bg-chart-2/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2" />
          
          <div className="relative">
            <h3 className="text-lg font-semibold mb-5">Account Details</h3>
            <div className="space-y-0">
              <InfoRow icon={UserCircle} label="Username" value={user.username} />
              <InfoRow icon={Mail} label="Email" value={user.email} />
              <InfoRow icon={Shield} label="Role" value={user.role.replace('_', ' ')} />
              <InfoRow 
                icon={user.is_active ? Check : X} 
                label="Status" 
                value={user.is_active ? 'Active' : 'Inactive'} 
                valueClass={user.is_active ? 'text-green-400' : 'text-red-400'}
              />
              <InfoRow icon={Calendar} label="Member Since" value={formatDate(user.created_at)} />
              <InfoRow icon={Clock} label="Last Login" value={formatDate(user.last_login)} />
            </div>
          </div>
        </motion.div>

        <div className="space-y-6">
          {/* Credits */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-card/40 backdrop-blur-2xl border border-border/40 rounded-2xl p-6 relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />
            
            <div className="relative">
              <h3 className="text-lg font-semibold mb-4">Credits</h3>
              <div className="p-5 rounded-xl bg-gradient-to-br from-primary/10 to-primary/5 border border-primary/20">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-primary/20 flex items-center justify-center">
                    <Zap className="w-6 h-6 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Available Balance</p>
                    <p className="text-3xl font-bold">{user.nuke_balance.toLocaleString()} NUKE</p>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Preferences */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="bg-card/40 backdrop-blur-2xl border border-border/40 rounded-2xl p-6 relative overflow-hidden"
          >
            <div className="relative">
              <h3 className="text-lg font-semibold mb-4">Preferences</h3>
              <div className="space-y-4">
                <div className="flex items-center justify-between py-2">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Globe className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Use Gravatar</p>
                      <p className="text-xs text-muted-foreground">Fetch avatar from Gravatar</p>
                    </div>
                  </div>
                  <button
                    onClick={toggleGravatar}
                    className="text-primary hover:text-primary/80 transition-colors"
                  >
                    {useGravatar ? (
                      <ToggleRight className="w-10 h-6" />
                    ) : (
                      <ToggleLeft className="w-10 h-6 text-muted-foreground" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ 
  icon: Icon, 
  label, 
  value, 
  valueClass 
}: { 
  icon: React.ElementType; 
  label: string; 
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between py-3.5 border-b border-border/20 last:border-0">
      <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <span className={cn("text-sm font-medium", valueClass)}>{value}</span>
    </div>
  );
}
