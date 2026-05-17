import { useState, useEffect, useRef } from 'react';
import { motion, useInView, useMotionValue, useTransform, animate } from 'framer-motion';
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
  UserCircle,
  Eye,
  BadgeCheck,
  LogIn,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react';
import { useAuthStore } from '../../stores/auth-store';
import { useToast } from '../../stores/toast-store';
import { cn } from '../../lib/utils';
import { api } from '../../lib/api';
import { Card } from '../ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../ui/dialog';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Button } from '../ui/button';
import { Switch } from '../ui/switch';

/* ------------------------------------------------------------------ */
/*  Animation helpers                                                  */
/* ------------------------------------------------------------------ */

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.05 },
  },
};

const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring', stiffness: 350, damping: 28 },
  },
};

const fadeIn = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.4 } },
};

function AnimatedNumber({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const isInView = useInView(ref, { once: true });
  const count = useMotionValue(0);
  const rounded = useTransform(count, (v) => Math.round(v).toLocaleString());

  useEffect(() => {
    if (isInView) {
      const controls = animate(count, value, { duration: 1.2, ease: 'easeOut' });
      return controls.stop;
    }
  }, [isInView, value, count]);

  return <motion.span ref={ref}>{rounded}</motion.span>;
}

/* ------------------------------------------------------------------ */
/*  Small components                                                   */
/* ------------------------------------------------------------------ */

function Orb({ className }: { className?: string }) {
  return (
    <div className={cn('absolute rounded-full blur-3xl pointer-events-none opacity-50', className)} />
  );
}

function SectionCard({
  children,
  className,
  orb,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  orb?: string;
  delay?: number;
}) {
  return (
    <motion.div variants={fadeUp} transition={{ delay }} className="h-full">
      <Card variant="default" className={cn('relative overflow-hidden h-full', className)}>
        {orb && <Orb className={orb} />}
        <div className="relative">{children}</div>
      </Card>
    </motion.div>
  );
}

function DetailRow({
  icon: Icon,
  label,
  value,
  valueClass,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between py-2.5">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <Icon className="w-4 h-4 shrink-0" />
        <span>{label}</span>
      </div>
      <span className={cn('text-sm font-medium text-right', valueClass)}>{value}</span>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const map: Record<string, string> = {
    super_admin: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20',
    admin: 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20',
    moderator: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20',
    support: 'bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20',
    user: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
  };
  return (
    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium border capitalize', map[role] || map.user)}>
      {role.replace('_', ' ')}
    </span>
  );
}

function PrefToggle({
  icon: Icon,
  title,
  desc,
  checked,
  onChange,
  disabled,
}: {
  icon: LucideIcon;
  title: string;
  desc: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-1">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{desc}</p>
        </div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Edit Dialog                                                        */
/* ------------------------------------------------------------------ */

function EditDialog({
  open,
  onOpenChange,
  user,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user: NonNullable<ReturnType<typeof useAuthStore.getState>['user']>;
  onSaved: (u: Record<string, unknown>) => void;
}) {
  const { success, error } = useToast();
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    first_name: user.first_name || '',
    last_name: user.last_name || '',
    email: user.email || '',
    bio: user.profile?.bio || '',
  });

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.put<Record<string, unknown>>('/users/me/profile', {
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email,
        profile: { ...user.profile, bio: form.bio },
      });
      onSaved(updated);
      success('Profile updated', 'Your profile has been updated successfully');
      onOpenChange(false);
    } catch {
      error('Update failed', 'Failed to update your profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit Profile</DialogTitle>
          <DialogDescription>Update your profile information.</DialogDescription>
        </DialogHeader>
        <form id="pf" onSubmit={(e) => { e.preventDefault(); save(); }} className="space-y-4 mt-4" noValidate>
          <div className="space-y-2">
            <label className="text-sm font-medium">First Name</label>
            <Input value={form.first_name} onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))} placeholder="First name" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Last Name</label>
            <Input value={form.last_name} onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))} placeholder="Last name" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Email</label>
            <Input type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} placeholder="Email" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Bio</label>
            <Textarea
              value={form.bio}
              onChange={(e) => setForm((f) => ({ ...f, bio: e.target.value }))}
              placeholder="Tell us about yourself..."
              rows={3}
              className="resize-none"
            />
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="pf" loading={saving}>Save Changes</Button>
        </DialogFooter>
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const { success, error } = useToast();

  const [editOpen, setEditOpen] = useState(false);
  const [avatarKey, setAvatarKey] = useState(Date.now());
  const [togglingVis, setTogglingVis] = useState(false);

  if (!user) return null;

  const useGravatar = user.preferences?.use_gravatar !== false;
  const displayName = user.first_name && user.last_name ? `${user.first_name} ${user.last_name}` : user.display_name || user.username;
  const initials = displayName.charAt(0).toUpperCase();

  const fmtDate = (d?: string) =>
    d ? new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }) : 'Never';

  const handleSaved = (updated: Record<string, unknown>) => setUser({ ...user, ...updated });

  const toggleGravatar = async () => {
    try {
      const newPrefs = { ...user.preferences, use_gravatar: !useGravatar };
      await api.put('/preferences/', newPrefs);
      setUser({ ...user, preferences: newPrefs });
      setAvatarKey(Date.now());
      success(!useGravatar ? 'Gravatar enabled' : 'Custom avatar enabled', !useGravatar ? 'Gravatar is now active' : 'Using default avatar');
    } catch {
      error('Update failed', 'Failed to update preferences');
    }
  };

  const toggleVisibility = async () => {
    setTogglingVis(true);
    try {
      const next = user.profile_visibility === 'public' ? 'private' : 'public';
      const updated = await api.put<Record<string, unknown>>('/users/me/profile', { profile_visibility: next });
      setUser({ ...user, ...updated });
      success(next === 'public' ? 'Profile is now public' : 'Profile is now private', next === 'public' ? 'Others can find you in search' : 'Hidden from discovery');
    } catch {
      error('Update failed', 'Failed to update visibility');
    } finally {
      setTogglingVis(false);
    }
  };

  return (
    <>
      <EditDialog open={editOpen} onOpenChange={setEditOpen} user={user} onSaved={handleSaved} />

      <motion.div className="space-y-6 max-w-5xl mx-auto" variants={containerVariants} initial="hidden" animate="visible">
        {/* Page title */}
        <motion.div variants={fadeUp}>
          <h2 className="text-2xl font-bold">Profile</h2>
          <p className="text-muted-foreground mt-1">Manage your account settings and preferences</p>
        </motion.div>

        {/* ── Header ── */}
        <SectionCard className="p-6 sm:p-8" orb="top-0 right-0 w-72 h-72 bg-primary/5 -translate-y-1/2 translate-x-1/3">
          <div className="flex flex-col sm:flex-row items-center sm:items-start gap-5 sm:gap-6">
            {/* Avatar */}
            <motion.div
              initial={{ scale: 0.85, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 250, damping: 18, delay: 0.1 }}
              className="relative shrink-0"
            >
              {user.avatar_url && useGravatar ? (
                <img
                  src={`${user.avatar_url}${user.avatar_url.includes('?') ? '&' : '?'}_t=${avatarKey}`}
                  alt={displayName}
                  className="w-24 h-24 sm:w-28 sm:h-28 rounded-2xl object-cover ring-2 ring-border/60"
                />
              ) : (
                <div className="w-24 h-24 sm:w-28 sm:h-28 rounded-2xl bg-gradient-to-br from-primary/40 to-primary/10 ring-2 ring-primary/30 flex items-center justify-center text-4xl font-bold text-primary">
                  {initials}
                </div>
              )}
              <div className={cn('absolute -bottom-1.5 -right-1.5 w-6 h-6 rounded-full border-2 border-background flex items-center justify-center', user.is_active ? 'bg-emerald-500' : 'bg-red-500')}>
                <div className="w-2 h-2 rounded-full bg-white" />
              </div>
            </motion.div>

            {/* Text */}
            <div className="flex-1 min-w-0 text-center sm:text-left">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">{displayName}</h1>
              <p className="text-muted-foreground mt-0.5">@{user.username}</p>

              <div className="flex items-center justify-center sm:justify-start gap-2.5 mt-3 flex-wrap">
                <RoleBadge role={user.role} />
                <span className="text-sm text-muted-foreground">{user.email}</span>
              </div>

              {user.profile?.bio && (
                <motion.p variants={fadeIn} className="text-sm text-muted-foreground mt-3 max-w-lg leading-relaxed">
                  {user.profile.bio}
                </motion.p>
              )}
            </div>

            <Button variant="outline" className="shrink-0" onClick={() => setEditOpen(true)}>
              <Pencil className="w-4 h-4 mr-2" />
              Edit Profile
            </Button>
          </div>
        </SectionCard>

        {/* ── Equal 2-column grid ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Left: Account Details */}
          <SectionCard className="p-6" delay={0.1}>
            <h3 className="text-lg font-semibold mb-1">Account Details</h3>
            <p className="text-xs text-muted-foreground mb-4">Your account information and activity</p>

            <div className="divide-y divide-border/30">
              <DetailRow icon={UserCircle} label="Username" value={user.username} />
              <DetailRow icon={Mail} label="Email" value={user.email} />
              <DetailRow icon={Shield} label="Role" value={user.role.replace('_', ' ')} />
              <DetailRow
                icon={user.is_active ? Check : X}
                label="Status"
                value={user.is_active ? 'Active' : 'Inactive'}
                valueClass={user.is_active ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}
              />
              <DetailRow
                icon={BadgeCheck}
                label="Email Verified"
                value={user.is_verified ? 'Verified' : 'Not Verified'}
                valueClass={user.is_verified ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}
              />
              <DetailRow icon={LogIn} label="Total Logins" value={user.login_count.toLocaleString()} />
              <DetailRow icon={Calendar} label="Member Since" value={fmtDate(user.created_at)} />
              <DetailRow icon={Clock} label="Last Login" value={fmtDate(user.last_login)} />
              <DetailRow icon={RefreshCw} label="Profile Updated" value={fmtDate(user.updated_at)} />
            </div>
          </SectionCard>

          {/* Right: Credits + Preferences stacked */}
          <div className="flex flex-col gap-6 h-full">
            {/* Credits — prominent */}
            <SectionCard className="p-6" delay={0.15}>
              <h3 className="text-lg font-semibold mb-1">Credits</h3>
              <p className="text-xs text-muted-foreground mb-4">Your current NUKE balance</p>

              <div className="flex items-center gap-5 p-5 rounded-xl bg-gradient-to-br from-primary/10 via-primary/5 to-transparent border border-primary/15">
                <div className="w-14 h-14 rounded-2xl bg-primary/20 flex items-center justify-center shrink-0">
                  <Zap className="w-7 h-7 text-primary" />
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Available Balance</p>
                  <p className="text-3xl sm:text-4xl font-bold tracking-tight">
                    <AnimatedNumber value={user.nuke_balance} /> <span className="text-lg text-muted-foreground font-semibold">NUKE</span>
                  </p>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between py-2 px-1">
                <span className="text-sm text-muted-foreground">Daily Allowance</span>
                <span className="text-sm font-medium">{user.daily_allowance.toLocaleString()} NUKE</span>
              </div>
            </SectionCard>

            {/* Preferences */}
            <SectionCard className="p-6 flex-1" delay={0.2}>
              <h3 className="text-lg font-semibold mb-1">Preferences</h3>
              <p className="text-xs text-muted-foreground mb-4">Manage your profile settings</p>

              <div className="space-y-3">
                <PrefToggle
                  icon={Globe}
                  title="Use Gravatar"
                  desc="Fetch avatar from Gravatar"
                  checked={useGravatar}
                  onChange={toggleGravatar}
                />
                <PrefToggle
                  icon={Eye}
                  title="Public Profile"
                  desc="Let others find you in search"
                  checked={user.profile_visibility === 'public'}
                  onChange={toggleVisibility}
                  disabled={togglingVis}
                />
              </div>
            </SectionCard>
          </div>
        </div>
      </motion.div>
    </>
  );
}
