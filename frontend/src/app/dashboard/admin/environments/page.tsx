'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { environmentsApi } from '@/lib/api';
import { 
  Box, 
  Search,
  Plus,
  Pencil,
  Trash2,
  Copy,
  Check,
  X,
  Play,
  Square
} from 'lucide-react';

interface Environment {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  image: string;
  category: string;
  icon: string;
  color: string;
  is_active: boolean;
  packages: string[];
  created_at: string;
}

export default function AdminEnvironmentsPage() {
  const { isAdmin } = useAuthStore();
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [message, setMessage] = useState('');
  
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedEnv, setSelectedEnv] = useState<Environment | null>(null);
  
  const [createForm, setCreateForm] = useState({
    name: '',
    slug: '',
    description: '',
    image: 'nukelab/base:latest',
    category: 'base',
    icon: '🖥️',
    color: '#3B82F6',
    packages: [] as string[],
    environment_variables: {} as Record<string, string>,
    ports: [3000],
    is_public: true
  });

  useEffect(() => {
    if (!isAdmin()) return;
    fetchEnvironments();
  }, [isAdmin]);

  const fetchEnvironments = async () => {
    try {
      setLoading(true);
      const response = await environmentsApi.list();
      setEnvironments(response.data?.items || []);
    } catch (error) {
      console.error('Error fetching environments:', error);
      setMessage('Failed to load environments');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    try {
      await environmentsApi.create(createForm);
      setShowCreateModal(false);
      setMessage('Environment created successfully');
      fetchEnvironments();
      setCreateForm({
        name: '',
        slug: '',
        description: '',
        image: 'nukelab/base:latest',
        category: 'base',
        icon: '🖥️',
        color: '#3B82F6',
        packages: [],
        environment_variables: {},
        ports: [3000],
        is_public: true
      });
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to create environment');
    }
  };

  const handleUpdate = async () => {
    if (!selectedEnv) return;
    try {
      await environmentsApi.update(selectedEnv.id, createForm);
      setShowEditModal(false);
      setMessage('Environment updated successfully');
      fetchEnvironments();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to update environment');
    }
  };

  const handleToggleStatus = async (env: Environment) => {
    try {
      if (env.is_active) {
        await environmentsApi.deactivate(env.id);
      } else {
        await environmentsApi.activate(env.id);
      }
      setMessage(`Environment ${env.is_active ? 'deactivated' : 'activated'}`);
      fetchEnvironments();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to update environment');
    }
  };

  const handleDeletePermanent = async (env: Environment) => {
    if (!confirm(`⚠️ WARNING: This action cannot be undone!\n\nAre you sure you want to permanently delete "${env.name}"?\n\nThis will completely remove the environment from the database.`)) return;
    try {
      await environmentsApi.deletePermanent(env.id);
      setMessage('Environment permanently deleted');
      fetchEnvironments();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to delete environment');
    }
  };

  const handleClone = async (env: Environment) => {
    try {
      await environmentsApi.clone(env.id, {
        name: `${env.name} (Copy)`,
        slug: `${env.slug}-copy`
      });
      setMessage('Environment cloned successfully');
      fetchEnvironments();
    } catch (error: any) {
      setMessage(error.response?.data?.error || 'Failed to clone environment');
    }
  };

  const openEditModal = (env: Environment) => {
    setSelectedEnv(env);
    setCreateForm({
      name: env.name,
      slug: env.slug,
      description: env.description || '',
      image: env.image,
      category: env.category,
      icon: env.icon,
      color: env.color,
      packages: env.packages || [],
      environment_variables: {},
      ports: [3000],
      is_public: true
    });
    setShowEditModal(true);
  };

  const filteredEnvs = environments.filter(env =>
    env.name.toLowerCase().includes(search.toLowerCase()) ||
    env.category.toLowerCase().includes(search.toLowerCase())
  );

  const getCategoryColor = (category: string) => {
    const colors: Record<string, string> = {
      neutronics: 'bg-orange-100 text-orange-800',
      multiphysics: 'bg-purple-100 text-purple-800',
      visualization: 'bg-pink-100 text-pink-800',
      base: 'bg-blue-100 text-blue-800',
      dev: 'bg-green-100 text-green-800'
    };
    return colors[category] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Environment Templates</h1>
        <p className="text-gray-600 mt-1">Manage compute environments and their configurations</p>
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
            placeholder="Search environments..."
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
          New Environment
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading environments...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredEnvs.map((env) => (
            <div key={env.id} className={`bg-white rounded-xl shadow-sm border overflow-hidden hover:shadow-md transition-shadow ${env.is_active ? 'border-gray-200' : 'border-gray-300 opacity-75'}`}>
              <div className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{env.icon}</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className={`font-semibold ${env.is_active ? 'text-gray-900' : 'text-gray-500 line-through'}`}>{env.name}</h3>
                        {!env.is_active && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-800">
                            Inactive
                          </span>
                        )}
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${getCategoryColor(env.category)}`}>
                        {env.category}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleToggleStatus(env)}
                      className={`p-1.5 rounded-lg transition-colors ${env.is_active ? 'text-green-600 hover:bg-green-50' : 'text-gray-400 hover:bg-gray-50'}`}
                      title={env.is_active ? 'Deactivate' : 'Activate'}
                    >
                      {env.is_active ? <Play size={16} /> : <Square size={16} />}
                    </button>
                    <button
                      onClick={() => openEditModal(env)}
                      className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      onClick={() => handleClone(env)}
                      className="p-1.5 text-gray-500 hover:text-purple-600 hover:bg-purple-50 rounded-lg transition-colors"
                    >
                      <Copy size={16} />
                    </button>
                    <button
                      onClick={() => handleDeletePermanent(env)}
                      className="p-1.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="Permanently delete"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>

                <p className="text-sm text-gray-600 mb-3 line-clamp-2">{env.description || 'No description'}</p>

                <div className="text-xs text-gray-500 mb-3">
                  <div className="font-mono bg-gray-50 px-2 py-1 rounded">{env.image}</div>
                </div>

                {env.packages && env.packages.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-3">
                    {env.packages.slice(0, 5).map((pkg, i) => (
                      <span key={i} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                        {pkg}
                      </span>
                    ))}
                    {env.packages.length > 5 && (
                      <span className="text-xs text-gray-400">+{env.packages.length - 5}</span>
                    )}
                  </div>
                )}

                <div className="text-xs text-gray-400">
                  Created {new Date(env.created_at).toLocaleDateString()}
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
                {showEditModal ? 'Edit Environment' : 'Create Environment'}
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
                    placeholder="e.g., Neutronics Workbench"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Slug</label>
                  <input
                    type="text"
                    value={createForm.slug}
                    onChange={(e) => setCreateForm({...createForm, slug: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., neutronics"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={createForm.description}
                  onChange={(e) => setCreateForm({...createForm, description: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  rows={2}
                  placeholder="Describe what this environment is used for..."
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Docker Image</label>
                  <input
                    type="text"
                    value={createForm.image}
                    onChange={(e) => setCreateForm({...createForm, image: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="nukelab/base:latest"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
                  <input
                    type="text"
                    list="category-suggestions"
                    value={createForm.category}
                    onChange={(e) => setCreateForm({...createForm, category: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., neutronics"
                  />
                  <datalist id="category-suggestions">
                    <option value="base" />
                    <option value="neutronics" />
                    <option value="multiphysics" />
                    <option value="visualization" />
                    <option value="dev" />
                  </datalist>
                  <p className="text-xs text-gray-500 mt-1">Type a custom category or select from suggestions</p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Icon</label>
                  <input
                    type="text"
                    value={createForm.icon}
                    onChange={(e) => setCreateForm({...createForm, icon: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="🖥️"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Color</label>
                  <input
                    type="color"
                    value={createForm.color}
                    onChange={(e) => setCreateForm({...createForm, color: e.target.value})}
                    className="w-full h-10 border border-gray-300 rounded-lg"
                  />
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createForm.is_public}
                      onChange={(e) => setCreateForm({...createForm, is_public: e.target.checked})}
                      className="w-4 h-4 text-blue-600 rounded"
                    />
                    <span className="text-sm text-gray-700">Public</span>
                  </label>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Packages (one per line)</label>
                <textarea
                  value={createForm.packages.join('\n')}
                  onChange={(e) => setCreateForm({...createForm, packages: e.target.value.split('\n').filter(p => p.trim())})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 font-mono text-sm"
                  rows={4}
                  placeholder="openmc&#10;dagmc&#10;moab"
                />
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
