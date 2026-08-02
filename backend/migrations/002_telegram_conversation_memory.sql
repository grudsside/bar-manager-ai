alter table telegram_messages
    add column if not exists telegram_update_id bigint,
    add column if not exists direction text not null default 'incoming',
    add column if not exists role text not null default 'user',
    add column if not exists processing_status text not null default 'received',
    add column if not exists error_message text;

alter table telegram_messages
    drop constraint if exists telegram_messages_direction_check;
alter table telegram_messages
    add constraint telegram_messages_direction_check
    check (direction in ('incoming', 'outgoing'));

alter table telegram_messages
    drop constraint if exists telegram_messages_role_check;
alter table telegram_messages
    add constraint telegram_messages_role_check
    check (role in ('user', 'assistant', 'system'));

alter table telegram_messages
    drop constraint if exists telegram_messages_processing_status_check;
alter table telegram_messages
    add constraint telegram_messages_processing_status_check
    check (processing_status in ('received', 'processing', 'completed', 'failed', 'ignored'));

create unique index if not exists telegram_messages_update_id_unique_idx
    on telegram_messages(telegram_update_id)
    where telegram_update_id is not null;

create index if not exists telegram_messages_history_idx
    on telegram_messages(chat_id, created_at desc)
    where processing_status = 'completed' and message_text is not null;
