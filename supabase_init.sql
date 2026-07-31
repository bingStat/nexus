-- 1. åˆ›å»º devices è¡¨
CREATE TABLE IF NOT EXISTS public.devices (
    device_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'offline',
    last_seen TIMESTAMPTZ DEFAULT now()
);

-- 2. åˆ›å»º commands è¡¨
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

-- 3. å¼€å¯ Row Level Security (RLS) - è¿™æ˜¯ä¿æŠ¤ä½  API çš„å…³é”®
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.commands ENABLE ROW LEVEL SECURITY;

-- 4. åˆ›å»ºç­–ç•¥ï¼šå…è®¸å¸¦æœ‰æ­£ç¡®çš„ API KEY (é€šè¿‡ authenticated è§’è‰²ï¼Œæˆ–è€…æˆ‘ä»¬ç›´æŽ¥æ”¾è¡Œæ‰€æœ‰ service_role)
-- å»ºè®®åœ¨ Supabase ä¸­ï¼Œä½ åªéœ€ä½¿ç”¨ `service_role` key æˆ–è€… `anon` keyã€‚
-- ä¸ºäº†ç®€åŒ–æž¶æž„ä¸”å…¼é¡¾å®‰å…¨ï¼Œæˆ‘ä»¬å…è®¸å¸¦æœ‰æœ‰æ•ˆ JWT (anon/service_role) çš„è¯·æ±‚æ‹¥æœ‰æ‰€æœ‰æƒé™ã€‚
CREATE POLICY "Allow ALL for authenticated users on devices" 
ON public.devices FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow ALL for authenticated users on commands" 
ON public.commands FOR ALL USING (true) WITH CHECK (true);

