import { useState, useEffect, useMemo } from 'react';
import { HardDrive, Plus, X, AlertTriangle } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { Select, SelectItem } from '../ui/select';
import { formatBytes, formatPlanResource, parseMemoryString } from '../../lib/utils';
import type { Environment, Plan } from '../../types/api';
import type { Volume } from '../../hooks/use-volumes';

interface VolumeMountForm {
  volume_id: string;
  mount_path: string;
  mode: 'read_write' | 'read_only';
  max_size_gb: number;
}

export interface DeployServerData {
  name: string;
  plan_id: string;
  environment_id: string;
  volume_mounts?: Array<{
    volume_id: string;
    mount_path: string;
    mode: 'read_write' | 'read_only';
    max_size_bytes?: number;
  }>;
}

interface DeployServerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plans: Plan[];
  environments: Environment[];
  volumes: Volume[];
  defaultUsername?: string;
  defaultPlanId?: string;
  defaultEnvironmentId?: string;
  isPending: boolean;
  error?: Error | null;
  onDeploy: (data: DeployServerData) => void;
}

export function DeployServerDialog({
  open,
  onOpenChange,
  plans,
  environments,
  volumes,
  defaultUsername = 'user',
  defaultPlanId,
  defaultEnvironmentId,
  isPending,
  error,
  onDeploy,
}: DeployServerDialogProps) {
  const [deployForm, setDeployForm] = useState({
    name: '',
    plan_id: '',
    environment_id: '',
  });
  const [volumeMounts, setVolumeMounts] = useState<VolumeMountForm[]>([
    { volume_id: '', mount_path: '', mode: 'read_write', max_size_gb: 10 },
  ]);
  const [visibleError, setVisibleError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      const planId = defaultPlanId && plans.some((p) => p.id === defaultPlanId) ? defaultPlanId : '';
      const envId = defaultEnvironmentId && environments.some((e) => e.id === defaultEnvironmentId) ? defaultEnvironmentId : '';
      setDeployForm({ name: '', plan_id: planId, environment_id: envId });
      setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write', max_size_gb: 10 }]);
      setVisibleError(null);
    }
  }, [open, defaultPlanId, defaultEnvironmentId, plans, environments]);

  useEffect(() => {
    if (error) {
      setVisibleError(error.message);
    }
  }, [error]);

  const selectedPlan = plans.find((p) => p.id === deployForm.plan_id);
  const planDiskBytes = selectedPlan ? parseMemoryString(selectedPlan.disk_limit) : 0;

  const totalAllocatedBytes = useMemo(() => {
    return volumeMounts.reduce((sum, mount) => {
      if (!mount.volume_id) {
        // New volume: use specified size
        return sum + mount.max_size_gb * 1024 * 1024 * 1024;
      }
      // Existing volume: use its max_size_bytes or size_bytes
      const vol = volumes.find((v) => v.id === mount.volume_id);
      return sum + (vol?.max_size_bytes || vol?.size_bytes || 0);
    }, 0);
  }, [volumeMounts, volumes]);

  const isOverCapacity = planDiskBytes > 0 && totalAllocatedBytes > planDiskBytes;
  const capacityPercent = planDiskBytes > 0 ? Math.min(100, (totalAllocatedBytes / planDiskBytes) * 100) : 0;

  const isValid = deployForm.name.trim() && deployForm.plan_id && deployForm.environment_id && !isOverCapacity;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setVisibleError(null);

    if (!deployForm.name.trim()) {
      setVisibleError('Server name is required');
      return;
    }
    if (!deployForm.plan_id) {
      setVisibleError('Please select a plan');
      return;
    }
    if (!deployForm.environment_id) {
      setVisibleError('Please select an environment');
      return;
    }

    const mounts = volumeMounts.map((m, idx) => ({
      volume_id: m.volume_id,
      mount_path: idx === 0 && !m.mount_path ? `/home/${defaultUsername}` : (m.mount_path || '/data'),
      mode: m.mode,
      max_size_bytes: !m.volume_id ? m.max_size_gb * 1024 * 1024 * 1024 : undefined,
    }));

    onDeploy({
      name: deployForm.name.trim(),
      plan_id: deployForm.plan_id,
      environment_id: deployForm.environment_id,
      volume_mounts: mounts.length > 0 ? mounts : undefined,
    });
  };

  const addVolumeMount = () => {
    setVolumeMounts((prev) => [...prev, { volume_id: '', mount_path: '/data', mode: 'read_write', max_size_gb: 10 }]);
  };

  const removeVolumeMount = (index: number) => {
    setVolumeMounts((prev) => prev.filter((_, i) => i !== index));
  };

  const updateVolumeMount = (index: number, field: keyof VolumeMountForm, value: string | number) => {
    setVolumeMounts((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };

  const handleCancel = () => {
    onOpenChange(false);
    setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write', max_size_gb: 10 }]);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Deploy New Server</DialogTitle>
          <DialogDescription>Create and spawn a new simulation server.</DialogDescription>
        </DialogHeader>
        <form id="deploy-form" onSubmit={handleSubmit} className="space-y-4 mt-4" noValidate>
          {visibleError && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20">
              <AlertTriangle className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
              <p className="text-sm text-destructive">{visibleError}</p>
            </div>
          )}
          <div className="space-y-2">
            <label className="text-sm font-medium">Server Name *</label>
            <Input
              type="text"
              value={deployForm.name}
              onChange={(e) => {
                setDeployForm({ ...deployForm, name: e.target.value });
                if (visibleError) setVisibleError(null);
              }}
              placeholder="my-simulation-server"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Plan *</label>
            <Select
              value={deployForm.plan_id}
              onChange={(value) => {
                setDeployForm({ ...deployForm, plan_id: value });
                if (visibleError) setVisibleError(null);
              }}
              placeholder="Select a plan..."
            >
              {plans.map((plan) => (
                <SelectItem key={plan.id} value={plan.id}>
                  {plan.name} ({plan.cpu_limit} CPU / {plan.memory_limit} / {formatPlanResource(plan.disk_limit)} disk)
                </SelectItem>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Environment *</label>
            <Select
              value={deployForm.environment_id}
              onChange={(value) => {
                setDeployForm({ ...deployForm, environment_id: value });
                if (visibleError) setVisibleError(null);
              }}
              placeholder="Select an environment..."
            >
              {environments.map((env) => (
                <SelectItem key={env.id} value={env.id}>
                  {env.name} ({env.slug})
                </SelectItem>
              ))}
            </Select>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium flex items-center gap-1.5">
                <HardDrive className="w-4 h-4" />
                Volume Mounts
              </label>
              <button
                type="button"
                onClick={addVolumeMount}
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Volume
              </button>
            </div>

            {/* Capacity indicator */}
            {selectedPlan && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    Plan capacity: {formatPlanResource(selectedPlan.disk_limit)}
                  </span>
                  <span className={isOverCapacity ? 'text-destructive font-medium' : 'text-muted-foreground'}>
                    {formatBytes(totalAllocatedBytes)} / {formatPlanResource(selectedPlan.disk_limit)}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      isOverCapacity ? 'bg-destructive' : capacityPercent > 80 ? 'bg-amber-500' : 'bg-emerald-500'
                    }`}
                    style={{ width: `${capacityPercent}%` }}
                  />
                </div>
                {isOverCapacity && (
                  <p className="text-xs text-destructive">
                    Total volume capacity exceeds plan disk limit. Reduce sizes or choose a larger plan.
                  </p>
                )}
              </div>
            )}

            {volumeMounts.map((mount, index) => {
              const selectedVol = volumes.find((v) => v.id === mount.volume_id);
              const isNewVolume = !mount.volume_id;
              return (
                <div key={index} className="space-y-2 p-3 rounded-lg bg-surface/50 border border-border/50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">
                      {index === 0 ? 'Primary Mount' : `Additional Mount ${index}`}
                    </span>
                    {volumeMounts.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeVolumeMount(index)}
                        className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  <Select
                    value={mount.volume_id}
                    onChange={(value) => updateVolumeMount(index, 'volume_id', value)}
                    placeholder="Create new volume (default)"
                  >
                    <SelectItem value="">Create new volume</SelectItem>
                    {volumes.map((vol) => (
                      <SelectItem key={vol.id} value={vol.id}>
                        {vol.display_name}
                        {' '}
                        {vol.max_size_bytes
                          ? `(${formatBytes(vol.max_size_bytes)} limit${vol.size_bytes > 0 ? `, ${formatBytes(vol.size_bytes)} used` : ''})`
                          : vol.size_bytes > 0
                            ? `(${formatBytes(vol.size_bytes)} used)`
                            : '(unused)'}
                      </SelectItem>
                    ))}
                  </Select>

                  {/* Size input for new volumes */}
                  {isNewVolume && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground whitespace-nowrap">Size:</span>
                      <Input
                        type="number"
                        min={1}
                        max={500}
                        value={mount.max_size_gb}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          updateVolumeMount(index, 'max_size_gb', String(isNaN(val) ? 1 : Math.max(1, Math.min(500, val))));
                        }}
                        className="w-20 text-sm"
                      />
                      <span className="text-xs text-muted-foreground">GB</span>
                    </div>
                  )}

                  {/* Show existing volume size info */}
                  {selectedVol && (
                    <div className="text-xs text-muted-foreground">
                      {selectedVol.max_size_bytes
                        ? `Capacity: ${formatBytes(selectedVol.max_size_bytes)}${selectedVol.size_bytes > 0 ? ` • Used: ${formatBytes(selectedVol.size_bytes)}` : ''}`
                        : selectedVol.size_bytes > 0
                          ? `Used: ${formatBytes(selectedVol.size_bytes)}`
                          : 'Empty volume'}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Input
                      type="text"
                      value={mount.mount_path}
                      onChange={(e) => updateVolumeMount(index, 'mount_path', e.target.value)}
                      placeholder={index === 0 ? `/home/${defaultUsername}` : '/data'}
                      className="flex-1 text-sm"
                    />
                    <div className="flex gap-1">
                      <Button
                        type="button"
                        variant={mount.mode === 'read_write' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateVolumeMount(index, 'mode', 'read_write')}
                        className="text-xs px-2"
                      >
                        RW
                      </Button>
                      <Button
                        type="button"
                        variant={mount.mode === 'read_only' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateVolumeMount(index, 'mode', 'read_only')}
                        className="text-xs px-2"
                      >
                        RO
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" type="button" onClick={handleCancel}>
            Cancel
          </Button>
          <Button type="submit" form="deploy-form" loading={isPending} disabled={!isValid}>
            {isPending ? 'Deploying...' : 'Deploy'}
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
