-- Seed admin user (only in development)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin') THEN
        INSERT INTO users (username, email, password_hash, role, is_verified, credit_balance)
        VALUES (
            'admin',
            'admin@nukelab.local',
            '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.VTtYA.qGZvKG6', -- admin123
            'super_admin',
            true,
            999999
        );
    END IF;
END $$;
