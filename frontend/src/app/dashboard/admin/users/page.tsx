'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { adminApi, usersApi, creditsApi } from '@/lib/api';
import { 
  Users, 
  Search,
  Shield,
  CreditCard,
  AlertTriangle,
  Plus,
  Pencil,
  Ban,
  Trash2,
  Coins,
  X,
  Check
} from 'lucide-react';

interface User {
  id: string;
  username: string;
  email: string;
  full_name: string | null;
  role: string;
  credit_balance: number;
  is_active: boolean;
  last_login: string | null;
}

export default function AdminUsersPage() {
  const { isAdmin } = useAuthStore();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [pagination, setPagination] = useState<any>({});
  const [message, setMessage] = useState('');
  
  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showCreditsModal, setShowCreditsModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  
  // Form states
  const [createForm, setCreateForm] = useState({
    username: '',
    email: '',
    password: '',
    role: 'user',
    full_name: '',
    credits: 500
  });
  
  const [editForm, setEditForm] = useState({
    full_name: '',
    email: '',
    role: 'user',
    is_active: true
  });
  
  const [creditsForm, setCreditsForm] = useState({
    amount: 0,
    reason: ''
  });

  useEffect(() => {
    if (!isAdmin()) return;
    fetchUsers();
  }, [isAdmin]);

  const fetchUsers = async (page = 1) => {
    try {
      setLoading(true);
      const data = await adminApi.getUsers({ page, search });
      setUsers(data.users || []);
      setPagination(data.pagination || {});
    } catch (error) {
      console.error('Error fetching users:', error);
    } finally {
      setLoading(false);
    }
  };

  const validateCreateForm = (): string | null => {
    if (!createForm.username || createForm.username.length < 3) {
      return 'Username must be at least 3 characters';
    }
    if (!createForm.email || !createForm.email.includes('@')) {
      return 'Please enter a valid email address';
    }
    if (!createForm.password || createForm.password.length < 6) {
      return 'Password must be at least 6 characters';
    }
    if (createForm.credits < 0) {
      return 'Credits cannot be negative';
    }
    return null;
  };

  const handleCreateUser = async () => {
    const validationError = validateCreateForm();
    if (validationError) {
      setMessage(validationError);
      return;
    }

    try {
      console.log('Creating user with data:', createForm);
      const response = await usersApi.create(createForm);
      console.log('Create user response:', response);
      setMessage('User created successfully');
      setShowCreateModal(false);
      setCreateForm({ username: '', email: '', password: '', role: 'user', full_name: '', credits: 500 });
      fetchUsers();
    } catch (error: any) {
      console.error('Create user error:', error);
      console.error('Error response:', error.response);
      console.error('Error data:', error.response?.data);
      const detail = error.response?.data?.detail;
      if (Array.isArray(detail)) {
        setMessage(detail.map((e: any) => `${e.loc.join('.')}: ${e.msg}`).join(', '));
      } else {
        setMessage(detail || 'Failed to create user');
      }
    }
  };

  const handleEditUser = async () => {
    if (!selectedUser) return;
    try {
      await usersApi.update(selectedUser.id, editForm);
      setMessage('User updated successfully');
      setShowEditModal(false);
      setSelectedUser(null);
      fetchUsers();
    } catch (error: any) {
      console.error('Edit user error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to update user');
    }
  };

  const validateCreditsForm = (): string | null => {
    if (!creditsForm.amount || creditsForm.amount <= 0) {
      return 'Please enter a positive amount';
    }
    if (!creditsForm.reason || creditsForm.reason.trim().length < 1) {
      return 'Please enter a reason for granting credits';
    }
    return null;
  };

  const handleGrantCredits = async () => {
    if (!selectedUser) return;
    
    const validationError = validateCreditsForm();
    if (validationError) {
      setMessage(validationError);
      return;
    }

    try {
      await creditsApi.grant(selectedUser.id, creditsForm.amount, creditsForm.reason);
      setMessage(`Granted ${creditsForm.amount} credits to ${selectedUser.username}`);
      setShowCreditsModal(false);
      setSelectedUser(null);
      setCreditsForm({ amount: 0, reason: '' });
      fetchUsers();
    } catch (error: any) {
      console.error('Grant credits error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to grant credits');
    }
  };

  const handleToggleStatus = async (user: User) => {
    let reason = '';
    
    if (user.is_active) {
      // Disabling - prompt for optional reason
      reason = window.prompt(`Disable user "${user.username}"?\n\nOptional: Enter a reason for disabling this user:`) || '';
      if (reason === null) return; // User cancelled
    } else {
      // Enabling - simple confirmation
      if (!confirm(`Enable user "${user.username}"?`)) return;
    }
    
    try {
      await usersApi.disable(user.id, user.is_active, reason || 'Admin action');
      setMessage(`User ${user.is_active ? 'disabled' : 'enabled'} successfully`);
      fetchUsers();
    } catch (error: any) {
      console.error('Toggle status error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to update user status');
    }
  };

  const handleDeleteUser = async (user: User) => {
    if (!confirm(`Are you sure you want to delete user ${user.username}?`)) return;
    try {
      await usersApi.delete(user.id);
      setMessage('User deleted successfully');
      fetchUsers();
    } catch (error: any) {
      console.error('Delete user error:', error.response?.data);
      setMessage(getErrorMessage(error) || 'Failed to delete user');
    }
  };

  const getErrorMessage = (error: any): string => {
    const detail = error.response?.data?.detail;
    if (Array.isArray(detail)) {
      return detail.map((e: any) => `${e.loc?.join('.') || 'error'}: ${e.msg}`).join(', ');
    }
    return detail || error.message || 'An error occurred';
  };

  const openEditModal = (user: User) => {
    setSelectedUser(user);
    setEditForm({
      full_name: user.full_name || '',
      email: user.email,
      role: user.role,
      is_active: user.is_active
    });
    setShowEditModal(true);
  };

  const openCreditsModal = (user: User) => {
    setSelectedUser(user);
    setCreditsForm({ amount: 0, reason: '' });
    setShowCreditsModal(true);
  };

  if (!isAdmin()) {
    return (
      <div className="text-center py-12">
        <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900">Access Denied</h2>
        <p className="text-gray-600 mt-2">You don't have permission to access this page.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-8 flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">User Management</h1>
          <p className="mt-2 text-gray-600">Manage platform users</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          <Plus className="w-5 h-5 mr-2" />
          Add User
        </button>
      </div>

      {message && (
        <div className={`mb-4 p-4 rounded-md ${message.includes('success') || message.includes('Granted') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          <div className="flex items-center">
            {message.includes('success') || message.includes('Granted') ? <Check className="w-5 h-5 mr-2" /> : <X className="w-5 h-5 mr-2" />}
            {message}
            <button onClick={() => setMessage('')} className="ml-auto text-sm underline">Dismiss</button>
          </div>
        </div>
      )}

      {/* Search */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="flex items-center">
          <Search className="w-5 h-5 text-gray-400 mr-3" />
          <input
            type="text"
            placeholder="Search users..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={() => fetchUsers()}
            className="ml-3 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            Search
          </button>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Role</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Credits</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-4 text-center">
                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto"></div>
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-4 text-center text-gray-500">
                    No users found
                  </td>
                </tr>
              ) : (
                users.map((user: User) => (
                  <tr key={user.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-bold">
                          {user.username[0]?.toUpperCase()}
                        </div>
                        <div className="ml-3">
                          <div className="text-sm font-medium text-gray-900">{user.username}</div>
                          <div className="text-sm text-gray-500">{user.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        user.role === 'super_admin' 
                          ? 'bg-red-100 text-red-800' 
                          : user.role === 'admin'
                          ? 'bg-orange-100 text-orange-800'
                          : 'bg-blue-100 text-blue-800'
                      }`}>
                        <Shield className="w-3 h-3 mr-1" />
                        {user.role}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center text-sm text-gray-900">
                        <CreditCard className="w-4 h-4 mr-1 text-green-600" />
                        {user.credit_balance}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        user.is_active 
                          ? 'bg-green-100 text-green-800' 
                          : 'bg-red-100 text-red-800'
                      }`}>
                        {user.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex space-x-2">
                        <button
                          onClick={() => openEditModal(user)}
                          className="p-1 text-blue-600 hover:bg-blue-50 rounded"
                          title="Edit user"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => openCreditsModal(user)}
                          className="p-1 text-yellow-600 hover:bg-yellow-50 rounded"
                          title="Grant credits"
                        >
                          <Coins className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleToggleStatus(user)}
                          className="p-1 text-orange-600 hover:bg-orange-50 rounded"
                          title={user.is_active ? 'Disable user' : 'Enable user'}
                        >
                          <Ban className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDeleteUser(user)}
                          className="p-1 text-red-600 hover:bg-red-50 rounded"
                          title="Delete user"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pagination.total_pages > 1 && (
          <div className="bg-gray-50 px-6 py-3 flex items-center justify-between">
            <div className="text-sm text-gray-700">
              Showing page {pagination.page} of {pagination.total_pages}
            </div>
            <div className="flex space-x-2">
              <button
                onClick={() => fetchUsers(pagination.page - 1)}
                disabled={pagination.page <= 1}
                className="px-3 py-1 border rounded-md disabled:opacity-50"
              >
                Previous
              </button>
              <button
                onClick={() => fetchUsers(pagination.page + 1)}
                disabled={pagination.page >= pagination.total_pages}
                className="px-3 py-1 border rounded-md disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">Create New User</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  type="text"
                  value={createForm.username}
                  onChange={(e) => setCreateForm({...createForm, username: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  value={createForm.email}
                  onChange={(e) => setCreateForm({...createForm, email: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  type="password"
                  value={createForm.password}
                  onChange={(e) => setCreateForm({...createForm, password: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                <input
                  type="text"
                  value={createForm.full_name}
                  onChange={(e) => setCreateForm({...createForm, full_name: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select
                  value={createForm.role}
                  onChange={(e) => setCreateForm({...createForm, role: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="user">User</option>
                  <option value="support">Support</option>
                  <option value="moderator">Moderator</option>
                  <option value="admin">Admin</option>
                  <option value="super_admin">Super Admin</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Initial Credits</label>
                <input
                  type="number"
                  value={createForm.credits}
                  onChange={(e) => setCreateForm({...createForm, credits: parseInt(e.target.value)})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
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
                onClick={handleCreateUser}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Create User
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {showEditModal && selectedUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">Edit User: {selectedUser.username}</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                <input
                  type="text"
                  value={editForm.full_name}
                  onChange={(e) => setEditForm({...editForm, full_name: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  value={editForm.email}
                  onChange={(e) => setEditForm({...editForm, email: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select
                  value={editForm.role}
                  onChange={(e) => setEditForm({...editForm, role: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="user">User</option>
                  <option value="support">Support</option>
                  <option value="moderator">Moderator</option>
                  <option value="admin">Admin</option>
                  <option value="super_admin">Super Admin</option>
                </select>
              </div>

            </div>
            <div className="mt-6 flex justify-end space-x-3">
              <button
                onClick={() => setShowEditModal(false)}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleEditUser}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Grant Credits Modal */}
      {showCreditsModal && selectedUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">Grant Credits to {selectedUser.username}</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Amount</label>
                <input
                  type="number"
                  value={creditsForm.amount}
                  onChange={(e) => setCreditsForm({...creditsForm, amount: parseInt(e.target.value)})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
                <input
                  type="text"
                  value={creditsForm.reason}
                  onChange={(e) => setCreditsForm({...creditsForm, reason: e.target.value})}
                  placeholder="e.g., Promotion, Bonus, Refund"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div className="mt-6 flex justify-end space-x-3">
              <button
                onClick={() => setShowCreditsModal(false)}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleGrantCredits}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Grant Credits
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
