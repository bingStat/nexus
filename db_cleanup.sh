#!/bin/bash
docker exec -i dc-db psql -U postgres -d postgres -c "DELETE FROM public.commands WHERE created_at < NOW() - INTERVAL '24 hours';"
