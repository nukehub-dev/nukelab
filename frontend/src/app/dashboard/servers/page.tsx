'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { serversApi, environmentsApi, plansApi } from '@/lib/api';
import { Server, Plus, Trash2, Pause, Activity, X, Loader2, Cpu, MemoryStick, HardDrive, CreditCard, ExternalLink } from 'lucide-react';

export default function ServersPage() {
  const [servers, setServers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [environments, setEnvironments] = useState<any[]>([]);
  const [plans, setPlans] = useState<any[]>([]);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState('');
  const [formData, setFormData] = useState({
    name: '',
    plan_id: '',
    environment_id: '',
  });

  useEffect(() => {
    fetchServers();
    fetchEnvironments();
    fetchPlans();
  }, []);

  const fetchServers = async () => {
    try {
      const data = await serversApi.list();
      setServers(data.servers || []);
    } catch (error) {
      console.error('Error fetching servers:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchEnvironments = async () => {
    try {
      const data = await environmentsApi.list();
      setEnvironments(data.data?.items || []);
    } catch (error) {
      console.error('Error fetching environments:', error);
    }
  };

  const fetchPlans = async () => {
    try {
      const data = await plansApi.list();
      setPlans(data.data?.items || []);
    } catch (error) {
      console.error('Error fetching plans:', error);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateLoading(true);
    setCreateError('');
    try {
      await serversApi.create(formData);
      setShowCreateModal(false);
      setFormData({ name: '', plan_id: '', environment_id: '' });
      fetchServers();
    } catch (err: any) {
      setCreateError(err.response?.data?.detail || 'Failed to create server');
    } finally {
      setCreateLoading(false);
    }
  };

  const handleStop = async (id: string) => {
    try {
      await serversApi.stop(id);
      fetchServers();
    } catch (error) {
      console.error('Error stopping server:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this server?')) return;
    try {
      await serversApi.delete(id);
      fetchServers();
    } catch (error) {
      console.error('Error deleting server:', error);
    }
  };

  return (
    <div>
      <div className="mb-8 flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">My Servers</h1>
          <p className="mt-2 text-gray-600">Manage your running instances</p>
        </div>
        <button 
          onClick={() => setShowCreateModal(true)}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          <Plus className="w-5 h-5 mr-2" />
          New Server
        </button>
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold">Create New Server</h2>
              <button onClick={() => setShowCreateModal(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {createError && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
                {createError}
              </div>
            )}

            <form onSubmit={handleCreate}>
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Server Name</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="my-server"
                />
              </div>

              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Plan</label>
                <select
                  required
                  value={formData.plan_id}
                  onChange={(e) => setFormData({ ...formData, plan_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Select a plan...</option>
                  {plans.map((plan: any) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name} — {plan.cpu_limit} CPU / {plan.memory_limit} / ${plan.cost_per_hour}/hr
                    </option>
                  ))}
                </select>
                {formData.plan_id && (
                  <div className="mt-2 p-3 bg-gray-50 rounded-md text-sm">
                    {(() => {
                      const plan = plans.find((p: any) => p.id === formData.plan_id);
                      return plan ? (
                        <div className="grid grid-cols-2 gap-2">
                          <div className="flex items-center text-gray-600">
                            <Cpu className="w-4 h-4 mr-1" />
                            {plan.cpu_limit} cores
                          </div>
                          <div className="flex items-center text-gray-600">
                            <MemoryStick className="w-4 h-4 mr-1" />
                            {plan.memory_limit}
                          </div>
                          <div className="flex items-center text-gray-600">
                            <HardDrive className="w-4 h-4 mr-1" />
                            {plan.disk_limit}
                          </div>
                          <div className="flex items-center text-gray-600">
                            <CreditCard className="w-4 h-4 mr-1" />
                            ${plan.cost_per_hour}/hr
                          </div>
                        </div>
                      ) : null;
                    })()}
                  </div>
                )}
              </div>

              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-1">Environment</label>
                <select
                  required
                  value={formData.environment_id}
                  onChange={(e) => setFormData({ ...formData, environment_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Select an environment...</option>
                  {environments.map((env: any) => (
                    <option key={env.id} value={env.id}>{env.name}</option>
                  ))}
                </select>
              </div>

              <div className="flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createLoading || !formData.plan_id || !formData.environment_id}
                  className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
                >
                  {createLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                  Create Server
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      ) : servers.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Server className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900">No servers yet</h3>
          <p className="text-gray-500 mt-2">Create your first server to get started</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">URL</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {servers.map((server: any) => (
                <tr key={server.id}>
                  <td className="px-6 py-4 whitespace-nowrap font-medium">{server.name}</td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      server.status === 'running' 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-gray-100 text-gray-800'
                    }`}>
                      {server.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {server.status === 'running' && server.external_url ? (
                      <a
                        href={`${window.location.origin}${server.external_url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:text-blue-800 hover:underline"
                      >
                        {server.external_url}
                      </a>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex space-x-2">
                      {server.status === 'running' && (
                        <>
                          <a
                            href={`${window.location.origin}${server.external_url}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1 text-green-600 hover:bg-green-50 rounded"
                            title="Open Server"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                          <Link
                            href={`/dashboard/servers/${server.id}/metrics`}
                            className="p-1 text-blue-600 hover:bg-blue-50 rounded"
                            title="View Metrics"
                          >
                            <Activity className="w-4 h-4" />
                          </Link>
                          <button
                            onClick={() => handleStop(server.id)}
                            className="p-1 text-yellow-600 hover:bg-yellow-50 rounded"
                          >
                            <Pause className="w-4 h-4" />
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => handleDelete(server.id)}
                        className="p-1 text-red-600 hover:bg-red-50 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
