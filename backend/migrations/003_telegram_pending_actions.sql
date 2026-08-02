create table if not exists telegram_pending_actions (
    id uuid primary key default gen_random_uuid(),
    chat_id bigint not null references telegram_chats(chat_id) on delete cascade,
    action_type text not null check (action_type in ('create_task')),
    payload jsonb not null,
    source_message_id bigint,
    status text not null default 'pending'
        check (status in ('pending','confirmed','cancelled','expired')),
    expires_at timestamptz not null default (now() + interval '24 hours'),
    resolved_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists telegram_pending_actions_chat_idx
    on telegram_pending_actions(chat_id, created_at desc);

create unique index if not exists telegram_pending_actions_one_pending_task_idx
    on telegram_pending_actions(chat_id, action_type)
    where status = 'pending';
