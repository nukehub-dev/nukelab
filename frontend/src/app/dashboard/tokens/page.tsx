'use client';

import { useEffect, useState } from 'react';
import { tokensApi } from '@/lib/api';
import { Key, Plus, Trash2, Copy, RefreshCw, Eye } from 'lucide-react';

interface ApiToken {
  id: string;
  name: string;
  scopes: string[];
  usage_count: number;
  last_used_at: string | null;
  created_at: string;
  is_active: boolean;
}

export default function TokensPage() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [createForm, setCreateForm] = useState({
    name: '',
    scopes: ['servers:read', 'servers:start'],
    expires_days: 30
  });

  useEffect(() => {
    fetchTokens();
  }, []);

  const fetchTokens = async () => {
    try {
      setLoading(true);
      const data = await tokensApi.list();
      setTokens(data || []);
    } catch (error) {
      console.error('Error fetching tokens:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateToken = async () => {
    if (!createForm.name || createForm.name.trim().length < 1) {
      setMessage('Please enter a token name');
      return;
    }
    if (!createForm.expires_days || createForm.expires_days < 1) {
      setMessage('Expiration must be at least 1 day');
      return;
    }
    if (createForm.scopes.length === 0) {
      setMessage('Please select at least one scope');
      return;
    }

    try {
      const response = await tokensApi.create(createForm);
      setNewToken(response.token);
      setMessage('Token created successfully. Copy it now - you won\'t see it again!');
      setCreateForm({ name: '', scopes: ['servers:read', 'servers:start'], expires_days: 30 });
      fetchTokens();
    } catch (error: any) {
      console.error('Create token error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to create token');
    }
  };

  const getErrorMessage = (error: any): string => {
    const detail = error.response?.data?.detail;
    if (Array.isArray(detail)) {
      return detail.map((e: any) => `${e.loc?.join('.') || 'error'}: ${e.msg}`).join(', ');
    }
    return detail || error.message || 'An error occurred';
  };

  const handleRevokeToken = async (tokenId: string) => {
    if (!confirm('Are you sure you want to revoke this token?\n\nThis will prevent it from being used, but the record will be kept for audit purposes.')) return;
    try {
      await tokensApi.revoke(tokenId);
      setMessage('Token revoked successfully');
      fetchTokens();
    } catch (error: any) {
      console.error('Revoke token error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to revoke token');
    }
  };

  const handleDeletePermanent = async (tokenId: string) => {
    if (!confirm('⚠️ WARNING: This action cannot be undone!\n\nAre you sure you want to permanently delete this token from the database?\n\nThis will completely remove the token record, including its audit history.')) return;
    try {
      await tokensApi.deletePermanent(tokenId);
      setMessage('Token permanently deleted');
      fetchTokens();
    } catch (error: any) {
      console.error('Delete token error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to delete token');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setMessage('Token copied to clipboard');
  };

  return (
    <div>
      <div className="mb-8 flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">API Tokens</h1>
          <p className="mt-2 text-gray-600">Manage your API tokens for external integrations</p>
        </div>
        <button
          onClick={() => {
            setShowCreateModal(true);
            setNewToken(null);
            setMessage('');
          }}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          <Plus className="w-5 h-5 mr-2" />
          New Token
        </button>
      </div>

      {message && (
        <div className={`mb-4 p-4 rounded-md ${message.includes('success') || message.includes('copied') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          {message}
          <button onClick={() => setMessage('')} className="ml-2 text-sm underline">Dismiss</button>
        </div>
      )}

      {/* New Token Display */}
      {newToken && (
        <div className="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold text-yellow-800">New Token Created</h3>
            <button
              onClick={() => copyToClipboard(newToken)}
              className="flex items-center px-3 py-1 bg-white border border-yellow-300 rounded-md text-sm hover:bg-yellow-50"
            >
              <Copy className="w-4 h-4 mr-1" />
              Copy
            </button>
          </div>
          <div className="bg-white p-3 rounded border font-mono text-sm break-all">
            {newToken}
          </div>
          <p className="mt-2 text-sm text-yellow-700">
            This token will only be shown once. Make sure to copy it now!
          </p>
        </div>
      )}

      {/* Tokens Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Scopes</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Usage</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-4 text-center">
                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto"></div>
                  </td>
                </tr>
              ) : tokens.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-4 text-center text-gray-500">
                    <Key className="w-12 h-12 text-gray-300 mx-auto mb-2" />
                    <p>No tokens yet</p>
                    <p className="text-sm">Create your first API token to get started</p>
                  </td>
                </tr>
              ) : (
                tokens.map((token: ApiToken) => (
                  <tr key={token.id} className={`hover:bg-gray-50 ${!token.is_active ? 'bg-gray-50 opacity-60' : ''}`}>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-medium ${token.is_active ? 'text-gray-900' : 'text-gray-500 line-through'}`}>
                          {token.name}
                        </span>
                        {!token.is_active && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 rounded-full">
                            Revoked
                          </span>
                        )}
                        {token.is_active && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 rounded-full">
                            Active
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-1">
                        {token.scopes.map((scope: string) => (
                          <span
                            key={scope}
                            className={`px-2 py-1 text-xs font-medium rounded-full ${
                              token.is_active 
                                ? 'bg-blue-100 text-blue-800' 
                                : 'bg-gray-100 text-gray-500'
                            }`}
                          >
                            {scope}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      <div className="flex items-center">
                        <Eye className="w-4 h-4 mr-1" />
                        {token.usage_count} uses
                      </div>
                      {token.last_used_at && (
                        <div className="text-xs text-gray-400 mt-1">
                          Last used: {new Date(token.last_used_at).toLocaleDateString()}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(token.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex space-x-2">
                        {token.is_active ? (
                          <button
                            onClick={() => handleRevokeToken(token.id)}
                            className="p-1 text-yellow-600 hover:bg-yellow-50 rounded"
                            title="Revoke token"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        ) : (
                          <button
                            onClick={() => handleDeletePermanent(token.id)}
                            className="p-1 text-red-600 hover:bg-red-50 rounded"
                            title="Permanently delete token"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create Token Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">Create New API Token</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Token Name</label>
                <input
                  type="text"
                  value={createForm.name}
                  onChange={(e) => setCreateForm({...createForm, name: e.target.value})}
                  placeholder="e.g., VS Code Extension"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Expiration (days)</label>
                <input
                  type="number"
                  value={createForm.expires_days}
                  onChange={(e) => setCreateForm({...createForm, expires_days: parseInt(e.target.value)})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Scopes</label>
                <div className="space-y-2">
                  {['servers:read', 'servers:start', 'servers:stop'].map((scope) => (
                    <label key={scope} className="flex items-center">
                      <input
                        type="checkbox"
                        checked={createForm.scopes.includes(scope)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setCreateForm({...createForm, scopes: [...createForm.scopes, scope]});
                          } else {
                            setCreateForm({...createForm, scopes: createForm.scopes.filter(s => s !== scope)});
                          }
                        }}
                        className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                      />
                      <span className="ml-2 text-sm text-gray-700">{scope}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end space-x-3">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateToken}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Create Token
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
