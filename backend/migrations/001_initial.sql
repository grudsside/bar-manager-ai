create extension if not exists pgcrypto;

create table if not exists venues (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    created_at timestamptz not null default now()
);

insert into venues (code, name)
values ('oxford', 'Оксфорд'), ('sovremennik', 'Современник')
on conflict (code) do nothing;

create table if not exists tasks (
    id uuid primary key default gen_random_uuid(),
    venue_id uuid references venues(id) on delete set null,
    title text not null,
    description text,
    original_text text,
    status text not null default 'new' check (status in ('new','planned','work','waiting','done','cancelled')),
    priority text not null default 'normal' check (priority in ('low','normal','high','critical')),
    due_at timestamptz,
    waiting_until timestamptz,
    source_type text not null default 'manual' check (source_type in ('manual','telegram','recurring','agent','file')),
    source_reference text,
    requires_confirmation boolean not null default false,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists tasks_status_due_idx on tasks(status, due_at);
create index if not exists tasks_venue_idx on tasks(venue_id);

create table if not exists task_events (
    id uuid primary key default gen_random_uuid(),
    task_id uuid not null references tasks(id) on delete cascade,
    event_type text not null,
    actor_type text not null check (actor_type in ('owner','agent','telegram','system')),
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists task_events_task_idx on task_events(task_id, created_at desc);

create table if not exists telegram_chats (
    chat_id bigint primary key,
    title text not null,
    venue_id uuid references venues(id) on delete set null,
    purpose text,
    allowed boolean not null default false,
    classification_rules jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists telegram_messages (
    id uuid primary key default gen_random_uuid(),
    chat_id bigint not null references telegram_chats(chat_id) on delete cascade,
    message_id bigint not null,
    sender_id bigint,
    sender_name text,
    message_text text,
    message_date timestamptz,
    reply_to_message_id bigint,
    forwarded_from jsonb,
    attachments jsonb not null default '[]'::jsonb,
    raw_update jsonb not null,
    classification text check (classification in ('task','task_update','writeoff','preparation','information','unknown')),
    confidence numeric(5,4),
    processed_at timestamptz,
    edited_at timestamptz,
    created_at timestamptz not null default now(),
    unique(chat_id, message_id)
);

create index if not exists telegram_messages_unprocessed_idx on telegram_messages(processed_at) where processed_at is null;
create index if not exists telegram_messages_chat_date_idx on telegram_messages(chat_id, message_date desc);

create table if not exists telegram_task_links (
    telegram_message_id uuid not null references telegram_messages(id) on delete cascade,
    task_id uuid not null references tasks(id) on delete cascade,
    relation_type text not null default 'source' check (relation_type in ('source','update','clarification','evidence')),
    created_at timestamptz not null default now(),
    primary key (telegram_message_id, task_id)
);

create table if not exists recurring_rules (
    id uuid primary key default gen_random_uuid(),
    venue_id uuid references venues(id) on delete set null,
    title text not null,
    description text,
    schedule_rrule text not null,
    default_due_time time,
    priority text not null default 'normal' check (priority in ('low','normal','high','critical')),
    enabled boolean not null default true,
    last_generated_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists agent_questions (
    id uuid primary key default gen_random_uuid(),
    task_id uuid references tasks(id) on delete cascade,
    question text not null,
    answer_options jsonb not null default '[]'::jsonb,
    answer text,
    status text not null default 'open' check (status in ('open','answered','dismissed')),
    asked_at timestamptz not null default now(),
    answered_at timestamptz
);

create index if not exists agent_questions_open_idx on agent_questions(status, asked_at desc);

create table if not exists agent_runs (
    id uuid primary key default gen_random_uuid(),
    task_id uuid references tasks(id) on delete set null,
    run_type text not null,
    model text,
    input_summary text,
    output_summary text,
    status text not null check (status in ('queued','running','waiting_confirmation','completed','failed')),
    usage jsonb not null default '{}'::jsonb,
    error_message text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists notification_events (
    id uuid primary key default gen_random_uuid(),
    task_id uuid references tasks(id) on delete cascade,
    notification_type text not null,
    title text not null,
    body text not null,
    severity text not null default 'normal' check (severity in ('info','normal','important','critical')),
    scheduled_for timestamptz,
    sent_at timestamptz,
    read_at timestamptz,
    delivery_results jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists notification_events_pending_idx on notification_events(scheduled_for) where sent_at is null;
create index if not exists notification_events_unread_idx on notification_events(created_at desc) where read_at is null;

create table if not exists push_subscriptions (
    id uuid primary key default gen_random_uuid(),
    endpoint text not null unique,
    p256dh text not null,
    auth text not null,
    user_agent text,
    enabled boolean not null default true,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists stored_files (
    id uuid primary key default gen_random_uuid(),
    task_id uuid references tasks(id) on delete set null,
    storage_key text not null unique,
    original_name text not null,
    content_type text,
    size_bytes bigint,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists app_settings (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);

create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists tasks_set_updated_at on tasks;
create trigger tasks_set_updated_at before update on tasks
for each row execute function set_updated_at();

drop trigger if exists telegram_chats_set_updated_at on telegram_chats;
create trigger telegram_chats_set_updated_at before update on telegram_chats
for each row execute function set_updated_at();

drop trigger if exists recurring_rules_set_updated_at on recurring_rules;
create trigger recurring_rules_set_updated_at before update on recurring_rules
for each row execute function set_updated_at();

drop trigger if exists push_subscriptions_set_updated_at on push_subscriptions;
create trigger push_subscriptions_set_updated_at before update on push_subscriptions
for each row execute function set_updated_at();
