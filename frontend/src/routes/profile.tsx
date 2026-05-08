import { createFileRoute } from '@tanstack/react-router';
import { motion } from 'framer-motion';
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
  UserCircle
} from 'lucide-react';
import { useState } from 'react';
import { useAuthStore } from '../stores/auth-store';
import { useToast } from '../stores/toast-store';
import { cn } from '../lib/utils';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Switch } from '../components/ui/switch';

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
  const [avatarKey, setAvatarKey] = useState(Date.now());
  
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
        setAvatarKey(Date.now());
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
    <>
      {/* Edit Modal */}
      <Dialog open={showEditModal} onOpenChange={setShowEditModal}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Profile</DialogTitle>
            <DialogDescription>Update your profile information.</DialogDescription>
          </DialogHeader>
          <form id="profile-form" onSubmit={(e) => { e.preventDefault(); handleSave(); }} className="space-y-4 mt-4" noValidate>
            <div className="space-y-2">
              <label className="text-sm font-medium">First Name</label>
              <Input
                type="text"
                value={editForm.first_name}
                onChange={(e) => setEditForm({ ...editForm, first_name: e.target.value })}
                placeholder="Enter first name"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Last Name</label>
              <Input
                type="text"
                value={editForm.last_name}
                onChange={(e) => setEditForm({ ...editForm, last_name: e.target.value })}
                placeholder="Enter last name"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Email</label>
              <Input
                type="email"
                value={editForm.email}
                onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                placeholder="Enter email"
              />
            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setShowEditModal(false)}>Cancel</Button>
            <Button type="submit" form="profile-form" loading={isSaving}>Save Changes</Button>
          </DialogFooter>
          <DialogClose onClick={() => setShowEditModal(false)} />
        </DialogContent>
      </Dialog>

      <div className="max-w-4xl mx-auto space-y-6 pb-10 pt-6 lg:pt-8">
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
                src={`${user.avatar_url}${user.avatar_url.includes('?') ? '&' : '?'}_t=${avatarKey}`} 
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
                  <Switch
                    checked={useGravatar}
                    onCheckedChange={toggleGravatar}
                  />
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
    </>
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
