CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    password_hash VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user' NOT NULL,
    
    -- Credits & Quotas
    credit_balance INTEGER DEFAULT 500,
    daily_allowance INTEGER DEFAULT 500,
    last_credit_reset TIMESTAMP WITH TIME ZONE,
    
    -- Profile (flexible JSONB for extensibility)
    profile JSONB DEFAULT '{}',
    
    -- Preferences (app-specific settings)
    preferences JSONB DEFAULT '{}',
    
    -- Security tracking
    security JSONB DEFAULT '{}',
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    email_verified_at TIMESTAMP WITH TIME ZONE,
    
    -- Audit
    last_login TIMESTAMP WITH TIME ZONE,
    last_ip_address INET,
    login_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create GIN indexes for JSONB columns (fast querying)
CREATE INDEX IF NOT EXISTS idx_users_profile ON users USING GIN (profile);
CREATE INDEX IF NOT EXISTS idx_users_preferences ON users USING GIN (preferences);
CREATE INDEX IF NOT EXISTS idx_users_security ON users USING GIN (security);

-- Roles table
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) UNIQUE NOT NULL,
    permissions JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert default roles
INSERT INTO roles (name, permissions) VALUES
    ('super_admin', '["*"]'),
    ('admin', '["users:read", "users:create", "users:update", "users:delete", "servers:read_all", "servers:manage", "resources:read_all", "environments:manage", "audit:read"]'),
    ('moderator', '["users:read", "users:create", "users:update", "servers:read_all", "resources:read_all"]'),
    ('support', '["users:read", "servers:read_all", "servers:access_all", "resources:read_all"]'),
    ('user', '["servers:read_own", "servers:start", "servers:stop", "resources:read_own"]'),
    ('guest', '["servers:read_own"]')
ON CONFLICT (name) DO NOTHING;

-- Servers table
CREATE TABLE IF NOT EXISTS servers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    environment_id UUID,
    plan_id UUID,
    container_id VARCHAR(255),
    image VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    allocated_cpu FLOAT,
    allocated_memory VARCHAR(50),
    allocated_disk VARCHAR(50),
    allocated_gpu INTEGER DEFAULT 0,
    internal_port INTEGER DEFAULT 3000,
    external_url VARCHAR(500),
    started_at TIMESTAMP WITH TIME ZONE,
    stopped_at TIMESTAMP WITH TIME ZONE,
    last_activity TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_servers_user_id ON servers(user_id);
CREATE INDEX IF NOT EXISTS idx_servers_status ON servers(status);
CREATE INDEX IF NOT EXISTS idx_servers_created_at ON servers(created_at);
