export interface PaginatedResponse<T> {
  data: T[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    totalPages: number;
  };
}

export interface Server {
  id: string;
  name: string;
  status: 'running' | 'stopped' | 'pending' | 'error';
  external_url?: string;
  user_id?: string;
  username?: string;
  created_at?: string;
  container_id?: string;
  allocated_cpu?: number;
  allocated_memory?: string;
  health_status?: string;
  status_reason?: string;
  started_at?: string;
  stopped_at?: string;
}

export interface User {
  id: string;
  username: string;
  email: string;
  first_name?: string;
  last_name?: string;
  display_name: string;
  avatar_url: string;
  role: string;
  nuke_balance: number;
  is_active: boolean;
  is_verified: boolean;
  last_login?: string;
  created_at?: string;
}

export interface Environment {
  id: string;
  name: string;
  slug: string;
  image: string;
  description?: string;
  category?: string;
  is_active: boolean;
  is_public: boolean;
  created_at: string;
  updated_at?: string;
  created_by?: string;
  icon?: string;
  color?: string;
}

export interface Plan {
  id: string;
  name: string;
  slug: string;
  description?: string;
  category: string;
  cpu_limit: number;
  memory_limit: string;
  disk_limit: string;
  gpu_limit: number;
  max_servers_per_user: number;
  cost_per_hour: number;
  cooldown_seconds: number;
  requires_approval: boolean;
  allowed_roles: string[];
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at?: string;
}

export interface ApiError {
  detail: string;
}
