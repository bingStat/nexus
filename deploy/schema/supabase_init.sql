-- 1. 创建 devices 表
CREATE TABLE IF NOT EXISTS public.devices (
    device_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'offline',
    last_seen TIMESTAMPTZ DEFAULT now()
);

-- 2. 创建 commands 表
CREATE TABLE IF NOT EXISTS public.commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_device TEXT,
    "deviceId" TEXT,
    device_id TEXT,
    command TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    output TEXT,
    timeout_ms INTEGER DEFAULT 30000,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. 设备身份公钥登记镜像。权威存储位于 Oracle Global API
-- /var/lib/nexus-global-api/device_identities.db；Supabase 只做目录/审计镜像。
CREATE TABLE IF NOT EXISTS public.device_identities (
    device_id TEXT PRIMARY KEY,
    key_id TEXT NOT NULL,
    public_key_ed25519 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending', 'approved', 'rejected', 'revoked')),
    hostname TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    agent_version TEXT,
    registered_at TIMESTAMPTZ DEFAULT now(),
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    last_seen TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 4. 开启 Row Level Security (RLS) - 这是保护你 API 的关键
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_identities ENABLE ROW LEVEL SECURITY;

-- 5. 创建策略：允许带有正确的 API KEY (通过 authenticated 角色，或者我们直接放行所有 service_role)
-- 建议在 Supabase 中，你只需使用 `service_role` key 或者 `anon` key。
-- 为了简化架构且兼顾安全，我们允许带有有效 JWT (anon/service_role) 的请求拥有所有权限。
CREATE POLICY "Allow ALL for authenticated users on devices"
ON public.devices FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow ALL for authenticated users on commands"
ON public.commands FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow ALL for authenticated users on device_identities"
ON public.device_identities FOR ALL USING (true) WITH CHECK (true);
