alter table telegram_messages
    add column if not exists inbox_status text not null default 'new',
    add column if not exists analysis jsonb not null default '{}'::jsonb,
    add column if not exists reviewed_at timestamptz;

alter table telegram_messages
    drop constraint if exists telegram_messages_inbox_status_check;

alter table telegram_messages
    add constraint telegram_messages_inbox_status_check
    check (inbox_status in ('new', 'review', 'confirmed', 'dismissed', 'ignored'));

update telegram_messages
set inbox_status = 'ignored'
where direction = 'outgoing';

create index if not exists telegram_messages_inbox_status_idx
    on telegram_messages(inbox_status, message_date desc, created_at desc)
    where direction = 'incoming' and inbox_status <> 'ignored';

create unique index if not exists telegram_task_links_source_unique_idx
    on telegram_task_links(telegram_message_id)
    where relation_type = 'source';
