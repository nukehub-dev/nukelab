'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { plansApi } from '@/lib/api';
import { 
  Server, 
  Search,
  Plus,
  Pencil,
  Trash2,
  Play,
  Square,
  Cpu,
  HardDrive,
  MemoryStick,
  X
} from 'lucide-react';

interface Plan {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  category: string;
  cpu_limit: number;
  memory_limit: string;
  disk_limit: string;
  gpu_limit: number;
  max_servers_per_user: number;
  cost_per_hour: number;
  priority: number;
  is_active: boolean;
  allowed_roles: string[];
  created_at: string;
}

export default function AdminPlansPage() {
  const { isAdmin } = useAuthStore();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [message, setMessage] = useState('');
  
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  
  const [createForm, setCreateForm] = useState({
    name: '',
    slug: '',
    description: '',
    category: 'cpu',
    cpu_limit: 1,
    memory_limit: '2g',
    disk_limit: '10g',
    gpu_limit: 0,
    max_servers_per_user: 3,
    cost_per_hour: 10,
    cooldown_seconds: 0,
    requires_approval: false,
    allowed_roles: [] as string[],
    priority: 0
  });

  useEffect(() => {
    if (!isAdmin()) return;
    fetchPlans();
  }, [isAdmin]);

  const fetchPlans = async () => {
    try {
      setLoading(true);
      const response = await plansApi.list();
      setPlans(response.data?.items || []);
    } catch (error) {
      console.error('Error fetching plans:', error);
      setMessage('Failed to load plans');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    try {
      await plansApi.create(createForm);
      setShowCreateModal(false);
      setMessage('Plan created successfully');
      fetchPlans();
      setCreateForm({
        name: '',
        slug: '',
        description: '',
        category: 'cpu',
        cpu_limit: 1,
        memory_limit: '2g',
        disk_limit: '10g',
        gpu_limit: 0,
        max_servers_per_user: 3,
        cost_per_hour: 10,
        cooldown_seconds: 0,
        requires_approval: false,
        allowed_roles: [],
        priority: 0
      });
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to create plan');
    }
  };

  const handleUpdate = async () => {
    if (!selectedPlan) return;
    try {
      await plansApi.update(selectedPlan.id, createForm);
      setShowEditModal(false);
      setMessage('Plan updated successfully');
      fetchPlans();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to update plan');
    }
  };

  const handleToggleStatus = async (plan: Plan) => {
    try {
      if (plan.is_active) {
        await plansApi.deactivate(plan.id);
      } else {
        await plansApi.activate(plan.id);
      }
      setMessage(`Plan ${plan.is_active ? 'deactivated' : 'activated'}`);
      fetchPlans();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to update plan');
    }
  };

  const handleDeletePermanent = async (plan: Plan) => {
    if (!confirm(`⚠️ WARNING: This action cannot be undone!\n\nAre you sure you want to permanently delete "${plan.name}"?\n\nThis will completely remove the plan from the database.`)) return;
    try {
      await plansApi.deletePermanent(plan.id);
      setMessage('Plan permanently deleted');
      fetchPlans();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to delete plan');
    }
  };

  const openEditModal = (plan: Plan) => {
    setSelectedPlan(plan);
    setCreateForm({
      name: plan.name,
      slug: plan.slug,
      description: plan.description || '',
      category: plan.category,
      cpu_limit: plan.cpu_limit,
      memory_limit: plan.memory_limit,
      disk_limit: plan.disk_limit,
      gpu_limit: plan.gpu_limit,
      max_servers_per_user: plan.max_servers_per_user,
      cost_per_hour: plan.cost_per_hour,
      cooldown_seconds: 0,
      requires_approval: false,
      allowed_roles: plan.allowed_roles || [],
      priority: plan.priority
    });
    setShowEditModal(true);
  };

  const filteredPlans = plans.filter(plan =>
    plan.name.toLowerCase().includes(search.toLowerCase()) ||
    plan.category.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Server Plans</h1>
        <p className="text-gray-600 mt-1">Manage compute plans and resource allocations</p>
      </div>

      {message && (
        <div className={`mb-4 p-3 rounded-lg flex items-center justify-between ${message.includes('Failed') ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
          <span>{message}</span>
          <button onClick={() => setMessage('')}><X size={16} /></button>
        </div>
      )}

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
          <input
            type="text"
            placeholder="Search plans..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={18} />
          New Plan
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading plans...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredPlans.map((plan) => (
            <div key={plan.id} className={`bg-white rounded-xl shadow-sm border overflow-hidden hover:shadow-md transition-shadow ${plan.is_active ? 'border-gray-200' : 'border-gray-300 opacity-75'}`}>
              <div className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${plan.category === 'gpu' ? 'bg-purple-100 text-purple-600' : 'bg-blue-100 text-blue-600'}`}>
                      <Cpu size={20} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className={`font-semibold ${plan.is_active ? 'text-gray-900' : 'text-gray-500 line-through'}`}>{plan.name}</h3>
                        {!plan.is_active && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-800">
                            Inactive
                          </span>
                        )}
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${plan.category === 'gpu' ? 'bg-purple-100 text-purple-800' : 'bg-blue-100 text-blue-800'}`}>
                        {plan.category.toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleToggleStatus(plan)}
                      className={`p-1.5 rounded-lg transition-colors ${plan.is_active ? 'text-green-600 hover:bg-green-50' : 'text-gray-400 hover:bg-gray-50'}`}
                      title={plan.is_active ? 'Deactivate' : 'Activate'}
                    >
                      {plan.is_active ? <Play size={16} /> : <Square size={16} />}
                    </button>
                    <button
                      onClick={() => openEditModal(plan)}
                      className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      onClick={() => handleDeletePermanent(plan)}
                      className="p-1.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="Permanently delete"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>

                <p className="text-sm text-gray-600 mb-4">{plan.description || 'No description'}</p>

                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="flex items-center gap-2 text-sm">
                    <Cpu size={16} className="text-gray-400" />
                    <span className="text-gray-700">{plan.cpu_limit} cores</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <MemoryStick size={16} className="text-gray-400" />
                    <span className="text-gray-700">{plan.memory_limit}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <HardDrive size={16} className="text-gray-400" />
                    <span className="text-gray-700">{plan.disk_limit}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <Server size={16} className="text-gray-400" />
                    <span className="text-gray-700">Max {plan.max_servers_per_user} servers</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-3 border-t border-gray-100">
                  <div className="text-sm">
                    <span className="text-gray-500">Cost: </span>
                    <span className="font-medium text-gray-900">{plan.cost_per_hour} credits/hr</span>
                  </div>
                  {plan.priority > 0 && (
                    <div className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">
                      Priority {plan.priority}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Modal */}
      {(showCreateModal || showEditModal) && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-gray-200 flex justify-between items-center">
              <h2 className="text-xl font-semibold">
                {showEditModal ? 'Edit Plan' : 'Create Plan'}
              </h2>
              <button onClick={() => { setShowCreateModal(false); setShowEditModal(false); }}>
                <X size={20} />
              </button>
            </div>
            
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    type="text"
                    value={createForm.name}
                    onChange={(e) => setCreateForm({...createForm, name: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., Small"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Slug</label>
                  <input
                    type="text"
                    value={createForm.slug}
                    onChange={(e) => setCreateForm({...createForm, slug: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., small"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                  type="text"
                  value={createForm.description}
                  onChange={(e) => setCreateForm({...createForm, description: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  placeholder="Brief description..."
                />
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
                  <select
                    value={createForm.category}
                    onChange={(e) => setCreateForm({...createForm, category: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="cpu">CPU</option>
                    <option value="gpu">GPU</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
                  <input
                    type="number"
                    value={createForm.priority}
                    onChange={(e) => setCreateForm({...createForm, priority: parseInt(e.target.value) || 0})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Cost/hr (credits)</label>
                  <input
                    type="number"
                    value={createForm.cost_per_hour}
                    onChange={(e) => setCreateForm({...createForm, cost_per_hour: parseInt(e.target.value) || 0})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-4 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">CPU (cores)</label>
                  <input
                    type="number"
                    step="0.5"
                    value={createForm.cpu_limit}
                    onChange={(e) => setCreateForm({...createForm, cpu_limit: parseFloat(e.target.value) || 0})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Memory</label>
                  <input
                    type="text"
                    value={createForm.memory_limit}
                    onChange={(e) => setCreateForm({...createForm, memory_limit: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="2g"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Disk</label>
                  <input
                    type="text"
                    value={createForm.disk_limit}
                    onChange={(e) => setCreateForm({...createForm, disk_limit: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="10g"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">GPU</label>
                  <input
                    type="number"
                    value={createForm.gpu_limit}
                    onChange={(e) => setCreateForm({...createForm, gpu_limit: parseInt(e.target.value) || 0})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Max Servers/User</label>
                  <input
                    type="number"
                    value={createForm.max_servers_per_user}
                    onChange={(e) => setCreateForm({...createForm, max_servers_per_user: parseInt(e.target.value) || 0})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createForm.requires_approval}
                      onChange={(e) => setCreateForm({...createForm, requires_approval: e.target.checked})}
                      className="w-4 h-4 text-blue-600 rounded"
                    />
                    <span className="text-sm text-gray-700">Requires Approval</span>
                  </label>
                </div>
              </div>
            </div>

            <div className="p-6 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => { setShowCreateModal(false); setShowEditModal(false); }}
                className="px-4 py-2 text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={showEditModal ? handleUpdate : handleCreate}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                {showEditModal ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
