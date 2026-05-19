import { useState, useEffect } from 'react';
import { HardDrive, Plus, X, AlertTriangle } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { Select, SelectItem } from '../ui/select';
import type { Environment, Plan } from '../../types/api';
import type { Volume } from '../../hooks/use-volumes';

interface VolumeMountForm {
  volume_id: string;
  mount_path: string;
  mode: 'read_write' | 'read_only';
}

export interface DeployServerData {
  name: string;
  plan_id: string;
  environment_id: string;
  volume_mounts?: Array<{
    volume_id: string;
    mount_path: string;
    mode: 'read_write' | 'read_only';
  }>;
}

interface DeployServerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plans: Plan[];
  environments: Environment[];
  volumes: Volume[];
  defaultUsername?: string;
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
    { volume_id: '', mount_path: '', mode: 'read_write' },
  ]);
  const [visibleError, setVisibleError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDeployForm({ name: '', plan_id: '', environment_id: '' });
      setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write' }]);
      setVisibleError(null);
    }
  }, [open]);

  useEffect(() => {
    if (error) {
      setVisibleError(error.message);
    }
  }, [error]);

  const isValid = deployForm.name.trim() && deployForm.plan_id && deployForm.environment_id;

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

    const mounts = volumeMounts
      .filter((m) => m.volume_id)
      .map((m, idx) => ({
        volume_id: m.volume_id,
        mount_path: idx === 0 && !m.mount_path ? `/home/${defaultUsername}` : (m.mount_path || '/data'),
        mode: m.mode,
      }));

    onDeploy({
      name: deployForm.name.trim(),
      plan_id: deployForm.plan_id,
      environment_id: deployForm.environment_id,
      volume_mounts: mounts.length > 0 ? mounts : undefined,
    });
  };

  const addVolumeMount = () => {
    setVolumeMounts((prev) => [...prev, { volume_id: '', mount_path: '/data', mode: 'read_write' }]);
  };

  const removeVolumeMount = (index: number) => {
    setVolumeMounts((prev) => prev.filter((_, i) => i !== index));
  };

  const updateVolumeMount = (index: number, field: keyof VolumeMountForm, value: string) => {
    setVolumeMounts((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };

  const handleCancel = () => {
    onOpenChange(false);
    setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write' }]);
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
              required
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
                  {plan.name} ({plan.cpu_limit} CPU / {plan.memory_limit})
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

            {volumeMounts.map((mount, index) => (
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
                      {vol.display_name} ({vol.server_count > 0 ? `${vol.server_count} servers` : 'unused'})
                    </SelectItem>
                  ))}
                </Select>

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
            ))}
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
