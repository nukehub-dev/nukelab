import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, useInView, useMotionValue, useTransform, animate } from 'framer-motion';
import {
  Mail,
  Zap,
  Calendar,
  Clock,
  Pencil,
  Globe,
  UserCircle,
  Eye,
  LogIn,
  RefreshCw,
  Loader2,
  ExternalLink,
  Building2,
  Users,
  Briefcase,
  type LucideIcon,
} from 'lucide-react';

import { AvatarEditDialog } from './avatar-edit-dialog';
import { useAuthStore } from '../../stores/auth-store';
import { useToast } from '../../stores/toast-store';
import { cn } from '../../lib/utils';
import { api } from '../../lib/api';
import type { User } from '../../types/api';
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
    <div className="flex items-center gap-4 py-2.5">
      <div className="flex items-center gap-3 text-sm text-muted-foreground shrink-0">
        <Icon className="w-4 h-4 shrink-0" />
        <span className="whitespace-nowrap">{label}</span>
      </div>
      <span className={cn('text-sm font-medium text-right ml-auto break-words', valueClass)}>{value}</span>
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
/*  Avatar Image with loading spinner                                  */
/* ------------------------------------------------------------------ */

function AvatarImage({ src, alt, fallback }: { src: string; alt: string; fallback: string }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  return (
    <div className="relative w-24 h-24 sm:w-28 sm:h-28">
      {(loading || error) && (
        <div className="absolute inset-0 rounded-2xl bg-muted ring-2 ring-border/60 group-hover:ring-primary/50 transition-all duration-200 flex items-center justify-center">
          {loading && !error ? (
            <Loader2 className="w-6 h-6 text-muted-foreground animate-spin" />
          ) : (
            <span className="text-4xl font-bold text-primary">{fallback}</span>
          )}
        </div>
      )}
      <img
        src={src}
        alt={alt}
        onLoad={() => { setLoading(false); setError(false); }}
        onError={() => { setLoading(false); setError(true); }}
        className={cn(
          'w-full h-full rounded-2xl object-cover ring-2 ring-border/60 group-hover:ring-primary/50 transition-all duration-200',
          loading && 'opacity-0',
          !loading && 'opacity-100'
        )}
      />
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
  oauthProfileUrl,
  providerName,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user: NonNullable<ReturnType<typeof useAuthStore.getState>['user']>;
  onSaved: (u: Partial<User>) => void;
  oauthProfileUrl?: string | null;
  providerName?: string | null;
}) {
  const { success, error } = useToast();
  const [saving, setSaving] = useState(false);
  const isOAuthManaged = !!user.oauth_provider && !!oauthProfileUrl;
  const [form, setForm] = useState({
    first_name: user.first_name || '',
    last_name: user.last_name || '',
    email: user.email || '',
    about: (user.profile?.about as string | undefined) || '',
    organization: (user.profile?.organization as string | undefined) || '',
    department: (user.profile?.department as string | undefined) || '',
    occupation: (user.profile?.occupation as string | undefined) || '',
  });

  const save = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        profile: {
          ...user.profile,
          about: form.about,
          organization: form.organization,
          department: form.department,
          occupation: form.occupation,
        },
      };
      if (!isOAuthManaged) {
        payload.first_name = form.first_name;
        payload.last_name = form.last_name;
        payload.email = form.email;
      }
      const updated = await api.put<Partial<User>>('/users/me/profile', payload);
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
          {isOAuthManaged && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-900/20 p-4 space-y-3">
              <p className="text-sm text-amber-800 dark:text-amber-200">
                Your name and email are managed by <span className="font-semibold">{providerName || 'your identity provider'}</span>.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => oauthProfileUrl && window.open(oauthProfileUrl, '_blank', 'noopener,noreferrer')}
              >
                <ExternalLink className="w-4 h-4 mr-2" />
                Open {providerName || 'Provider'} Account
              </Button>
            </div>
          )}
          {!isOAuthManaged && (
            <>
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
            </>
          )}
          <div className="space-y-2">
            <label className="text-sm font-medium">About</label>
            <Textarea
              value={form.about}
              onChange={(e) => setForm((f) => ({ ...f, about: e.target.value }))}
              placeholder="Tell us about yourself..."
              rows={3}
              className="resize-none"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Organization</label>
              <Input
                value={form.organization}
                onChange={(e) => setForm((f) => ({ ...f, organization: e.target.value }))}
                placeholder="Organization"
                disabled={isOAuthManaged}
                className={isOAuthManaged ? 'bg-muted' : ''}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Department</label>
              <Input
                value={form.department}
                onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
                placeholder="Department"
                disabled={isOAuthManaged}
                className={isOAuthManaged ? 'bg-muted' : ''}
              />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Occupation</label>
            <Input
              value={form.occupation}
              onChange={(e) => setForm((f) => ({ ...f, occupation: e.target.value }))}
              placeholder="Occupation / Job title"
              disabled={isOAuthManaged}
              className={isOAuthManaged ? 'bg-muted' : ''}
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
  const [avatarDialogOpen, setAvatarDialogOpen] = useState(false);
  const [avatarDialogKey, setAvatarDialogKey] = useState(0);
  const [avatarKey, setAvatarKey] = useState(() => Date.now());
  const [togglingVis, setTogglingVis] = useState(false);
  const [authConfig, setAuthConfig] = useState<{ oauth_profile_url?: string | null; oauth_provider_name?: string | null } | null>(null);
  const [syncing, setSyncing] = useState(false);

  // Derived values (must be before useEffect hooks that depend on them)
  const isOAuthUser = !!user?.oauth_provider;
  const oauthProfileUrl = authConfig?.oauth_profile_url;
  const providerName = authConfig?.oauth_provider_name || 'OAuth Provider';

  useEffect(() => {
    api.get<{ oauth_profile_url?: string | null; oauth_provider_name?: string | null }>('/auth/methods')
      .then((data) => setAuthConfig(data))
      .catch(() => setAuthConfig(null));
  }, []);

  // Reset syncing state on mount (in case we returned from a redirect)
  useEffect(() => {
    queueMicrotask(() => setSyncing(false));
  }, []);

  const startSync = useCallback(async () => {
    setSyncing(true);
    try {
      const updated = await api.post<User>('/auth/oauth/sync', {});
      setUser({ ...user, ...updated });
      success('Profile synced', 'Your profile has been updated from ' + (providerName || 'provider'));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not sync profile';
      error('Sync failed', message);
    } finally {
      setSyncing(false);
    }
  }, [user, providerName, setUser, success, error]);

  if (!user) return null;

  const useGravatar = user.preferences?.use_gravatar === true;
  const displayName = user.first_name && user.last_name ? `${user.first_name} ${user.last_name}` : user.display_name || user.username;
  const initials = displayName.charAt(0).toUpperCase();

  const fmtDate = (d?: string) =>
    d ? new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }) : 'Never';

  const handleSaved = (updated: Partial<User>) => setUser({ ...user, ...updated });

  const toggleGravatar = async () => {
    try {
      const newPrefs = { ...user.preferences, use_gravatar: !useGravatar };
      await api.put('/preferences/', newPrefs);
      const fresh = await api.get<User>('/users/me/profile');
      setUser(fresh);
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
      const updated = await api.put<Partial<User>>('/users/me/profile', { profile_visibility: next });
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
      <EditDialog open={editOpen} onOpenChange={setEditOpen} user={user} onSaved={handleSaved} oauthProfileUrl={oauthProfileUrl} providerName={providerName} />
      <AvatarEditDialog
        key={avatarDialogKey}
        open={avatarDialogOpen}
        onOpenChange={setAvatarDialogOpen}
        currentAvatarUrl={user.avatar_url}
        fallbackInitial={initials}
        useGravatar={useGravatar}
        onSaved={(updated) => {
          handleSaved(updated);
          setAvatarKey(Date.now());
        }}
        onToggleGravatar={toggleGravatar}
      />

      <div className="space-y-10 pb-10">
        <motion.div className="space-y-6" variants={containerVariants} initial="hidden" animate="visible">

        {/* ── Header ── */}
        <SectionCard className="p-6 sm:p-8" orb="top-0 right-0 w-72 h-72 bg-primary/5 -translate-y-1/2 translate-x-1/3">
          <div className="flex flex-col xl:flex-row flex-wrap items-center xl:items-start gap-5 xl:gap-6">
            {/* Avatar */}
            <div
              className="relative shrink-0 cursor-pointer group"
              onClick={() => {
                setAvatarDialogKey((k) => k + 1);
                setAvatarDialogOpen(true);
              }}
            >
              <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: 'spring', stiffness: 300, damping: 24, delay: 0.1 }}
                className="relative"
              >
                {user.avatar_url ? (
                  <AvatarImage
                    src={`${user.avatar_url}${user.avatar_url.includes('?') ? '&' : '?'}_t=${avatarKey}`}
                    alt={displayName}
                    fallback={initials}
                  />
                ) : (
                  <div className="w-24 h-24 sm:w-28 sm:h-28 rounded-2xl bg-gradient-to-br from-primary/40 to-primary/10 ring-2 ring-primary/30 group-hover:ring-primary/60 flex items-center justify-center text-4xl font-bold text-primary transition-all duration-200">
                    {initials}
                  </div>
                )}
              </motion.div>

              {/* Hover overlay (desktop) */}
              <div className="hidden sm:flex absolute inset-0 rounded-2xl bg-black/0 group-hover:bg-black/40 transition-all duration-200 items-center justify-center">
                <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col items-center gap-1">
                  <Pencil className="w-5 h-5 text-white" />
                  <span className="text-[10px] font-medium text-white/90">Edit</span>
                </div>
              </div>

              {/* Mobile: subtle edit indicator */}
              <div className="sm:hidden absolute -bottom-1 -right-1 w-7 h-7 rounded-full bg-primary border-2 border-background flex items-center justify-center shadow-sm">
                <Pencil className="w-3 h-3 text-primary-foreground" />
              </div>
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0 text-center xl:text-left">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">{displayName}</h1>
              <div className="flex items-center justify-center xl:justify-start gap-2 mt-1.5 flex-wrap">
                <p className="text-muted-foreground">@{user.username}</p>
                <RoleBadge role={user.role} />
              </div>
              <p className="text-sm text-muted-foreground mt-1">{user.email}</p>
            </div>

            {/* Actions */}
            <div className="shrink-0 flex flex-row gap-2 xl:flex-col order-4 xl:order-none">
              {isOAuthUser && oauthProfileUrl ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => window.open(oauthProfileUrl, '_blank', 'noopener,noreferrer')}
                  >
                    <ExternalLink className="w-4 h-4 mr-2" />
                    Manage at {providerName}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={startSync}
                    disabled={syncing}
                    loading={syncing}
                  >
                    <RefreshCw className="w-4 h-4 mr-2" />
                    Sync Profile
                  </Button>
                </>
              ) : (
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                  <Pencil className="w-4 h-4 mr-2" />
                  Edit Profile
                </Button>
              )}
            </div>

            {/* About */}
            {(user.profile?.about as string | undefined) && (
              <div className="w-full order-3 xl:order-last xl:mt-4 rounded-xl bg-muted/40 border border-border/50 p-4">
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {user.profile?.about as string | undefined}
                </p>
              </div>
            )}
          </div>
        </SectionCard>

        {/* ── 2-column grid (only on wide screens where sidebar + content fit) ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* Left: Account Details */}
          <SectionCard className="p-6" delay={0.1}>
            <h3 className="text-lg font-semibold mb-1">Account Details</h3>
            <p className="text-xs text-muted-foreground mb-4">Your account information and activity</p>

            <div className="divide-y divide-border/30">
              <DetailRow icon={UserCircle} label="Username" value={user.username} />
              <DetailRow icon={Mail} label="Email" value={user.email} />
              <DetailRow icon={Building2} label="Organization" value={(user.profile?.organization as string | undefined) || '—'} />
              <DetailRow icon={Users} label="Department" value={(user.profile?.department as string | undefined) || '—'} />
              <DetailRow icon={Briefcase} label="Occupation" value={(user.profile?.occupation as string | undefined) || '—'} />
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

              <div className="flex items-center gap-4 p-4 sm:p-5 rounded-xl bg-gradient-to-br from-primary/10 via-primary/5 to-transparent border border-primary/15">
                <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-primary/20 flex items-center justify-center shrink-0">
                  <Zap className="w-6 h-6 sm:w-7 sm:h-7 text-primary" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-muted-foreground whitespace-nowrap">Available Balance</p>
                  <p className="text-2xl sm:text-3xl font-bold tracking-tight">
                    <AnimatedNumber value={user.nuke_balance} />
                    <span className="text-base sm:text-lg text-muted-foreground font-semibold ml-1">NUKE</span>
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
      </div>
    </>
  );
}
