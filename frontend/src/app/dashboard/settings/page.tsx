'use client';

import { useEffect, useState } from 'react';
import { preferencesApi } from '@/lib/api';
import { Settings, Save, Check, X, Moon, Sun, Globe, Monitor } from 'lucide-react';

export default function SettingsPage() {
  const [preferences, setPreferences] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetchPreferences();
  }, []);

  const fetchPreferences = async () => {
    try {
      const data = await preferencesApi.get();
      setPreferences(data);
    } catch (error) {
      console.error('Error fetching preferences:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    
    try {
      await preferencesApi.update({
        theme: preferences.theme,
        language: preferences.language,
        timezone: preferences.timezone,
        default_environment: preferences.default_environment,
        default_plan: preferences.default_plan,
      });
      
      setMessage('Settings saved successfully');
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="mt-2 text-gray-600">Customize your experience</p>
      </div>

      {message && (
        <div className={`mb-4 p-4 rounded-md ${message.includes('success') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          <div className="flex items-center">
            {message.includes('success') ? <Check className="w-5 h-5 mr-2" /> : <X className="w-5 h-5 mr-2" />}
            {message}
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg shadow">
        <div className="p-6 border-b">
          <div className="flex items-center">
            <Settings className="w-6 h-6 text-blue-600 mr-3" />
            <h2 className="text-lg font-semibold">Preferences</h2>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Theme */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              <Moon className="w-4 h-4 inline mr-1" />
              Theme
            </label>
            <select
              value={preferences.theme || 'dark'}
              onChange={(e) => setPreferences({ ...preferences, theme: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="dark"><Moon className="w-4 h-4 inline mr-1" /> Dark</option>
              <option value="light"><Sun className="w-4 h-4 inline mr-1" /> Light</option>
              <option value="system"><Monitor className="w-4 h-4 inline mr-1" /> System</option>
            </select>
          </div>

          {/* Language */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              <Globe className="w-4 h-4 inline mr-1" />
              Language
            </label>
            <select
              value={preferences.language || 'en'}
              onChange={(e) => setPreferences({ ...preferences, language: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="en">English</option>
              <option value="es">Español</option>
              <option value="fr">Français</option>
              <option value="de">Deutsch</option>
            </select>
          </div>

          {/* Timezone */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Timezone
            </label>
            <select
              value={preferences.timezone || 'UTC'}
              onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="UTC">UTC</option>
              <option value="America/New_York">Eastern Time (ET)</option>
              <option value="America/Chicago">Central Time (CT)</option>
              <option value="America/Denver">Mountain Time (MT)</option>
              <option value="America/Los_Angeles">Pacific Time (PT)</option>
              <option value="Europe/London">London (GMT)</option>
              <option value="Europe/Paris">Paris (CET)</option>
              <option value="Asia/Tokyo">Tokyo (JST)</option>
            </select>
          </div>

          {/* Default Environment */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Default Environment
            </label>
            <select
              value={preferences.default_environment || 'dev'}
              onChange={(e) => setPreferences({ ...preferences, default_environment: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="dev">Development</option>
              <option value="base">Base</option>
            </select>
          </div>

          {/* Default Plan */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Default Plan
            </label>
            <select
              value={preferences.default_plan || 'small'}
              onChange={(e) => setPreferences({ ...preferences, default_plan: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="nano">Nano (0.5 CPU, 1GB RAM)</option>
              <option value="micro">Micro (1 CPU, 2GB RAM)</option>
              <option value="small">Small (2 CPU, 4GB RAM)</option>
              <option value="medium">Medium (4 CPU, 8GB RAM)</option>
              <option value="large">Large (8 CPU, 16GB RAM)</option>
            </select>
          </div>
        </div>

        <div className="p-6 border-t bg-gray-50">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            <Save className="w-4 h-4 mr-2" />
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
