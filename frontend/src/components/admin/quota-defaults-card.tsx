// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useEffect } from 'react'
import { Gauge, Server, Cpu, HardDrive, MemoryStick, CircuitBoard } from 'lucide-react'
import { motion } from 'framer-motion'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Button } from '../ui/button'
import {
  useSystemQuotaDefaults,
  useUpdateSystemQuotaDefaults,
  type QuotaLimits,
} from '../../hooks/use-quotas'

interface QuotaDefaultsCardProps {
  canManage: boolean
}

export function QuotaDefaultsCard({ canManage }: QuotaDefaultsCardProps) {
  const { data: defaults, isLoading } = useSystemQuotaDefaults()
  const updateDefaults = useUpdateSystemQuotaDefaults()

  const [formData, setFormData] = useState<QuotaLimits>({
    max_cpu_total: 8,
    max_memory_total: '16g',
    max_disk_total: '100g',
    max_gpu_total: 0,
    max_servers_total: 5,
  })

  useEffect(() => {
    if (defaults) {
      setFormData(defaults)
    }
  }, [defaults])

  const handleSave = () => {
    updateDefaults.mutate(formData)
  }

  const isChanged =
    defaults &&
    (defaults.max_cpu_total !== formData.max_cpu_total ||
      defaults.max_memory_total !== formData.max_memory_total ||
      defaults.max_disk_total !== formData.max_disk_total ||
      defaults.max_gpu_total !== formData.max_gpu_total ||
      defaults.max_servers_total !== formData.max_servers_total)

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15 }}
    >
      <Card className="bubble">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Gauge className="w-4 h-4 text-primary" />
            System Default Resource Quotas
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Default limits applied to new users when they are created
          </p>
        </CardHeader>
        <CardContent>
          {isLoading && !defaults ? (
            <div className="h-24 bg-muted/50 rounded-xl animate-pulse" />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              <div className="space-y-2">
                <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Server className="w-3.5 h-3.5" />
                  Max Servers
                </Label>
                <Input
                  type="number"
                  min={0}
                  value={formData.max_servers_total}
                  onChange={(e) =>
                    setFormData({ ...formData, max_servers_total: parseInt(e.target.value) || 0 })
                  }
                  disabled={!canManage || updateDefaults.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Cpu className="w-3.5 h-3.5" />
                  Max CPU (cores)
                </Label>
                <Input
                  type="number"
                  min={0}
                  step={0.5}
                  value={formData.max_cpu_total}
                  onChange={(e) =>
                    setFormData({ ...formData, max_cpu_total: parseFloat(e.target.value) || 0 })
                  }
                  disabled={!canManage || updateDefaults.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <MemoryStick className="w-3.5 h-3.5" />
                  Max Memory
                </Label>
                <Input
                  type="text"
                  value={formData.max_memory_total}
                  onChange={(e) => setFormData({ ...formData, max_memory_total: e.target.value })}
                  placeholder="e.g. 16g"
                  disabled={!canManage || updateDefaults.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <HardDrive className="w-3.5 h-3.5" />
                  Max Disk
                </Label>
                <Input
                  type="text"
                  value={formData.max_disk_total}
                  onChange={(e) => setFormData({ ...formData, max_disk_total: e.target.value })}
                  placeholder="e.g. 100g"
                  disabled={!canManage || updateDefaults.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <CircuitBoard className="w-3.5 h-3.5" />
                  Max GPU
                </Label>
                <Input
                  type="number"
                  min={0}
                  value={formData.max_gpu_total}
                  onChange={(e) =>
                    setFormData({ ...formData, max_gpu_total: parseInt(e.target.value) || 0 })
                  }
                  disabled={!canManage || updateDefaults.isPending}
                />
              </div>
            </div>
          )}
          {canManage && (
            <div className="flex justify-end mt-4">
              <Button
                onClick={handleSave}
                disabled={updateDefaults.isPending || !isChanged}
                loading={updateDefaults.isPending}
              >
                Save Defaults
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  )
}
