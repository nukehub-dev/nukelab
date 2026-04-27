-- Seed admin user (only in development)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin') THEN
        INSERT INTO users (username, email, password_hash, role, is_verified, credit_balance)
        VALUES (
            'admin',
            'admin@nukelab.local',
            '$2b$12$TIn0jQXTtQATiISE8wuw4.3aHA3ikPWYy3VXuWRNM6rZGAp6YP3.e',
            'super_admin',
            true,
            999999
        );
    END IF;
END $$;
