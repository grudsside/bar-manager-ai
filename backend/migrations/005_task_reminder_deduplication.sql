alter table notification_events
    add column if not exists dedupe_key text;

create unique index if not exists notification_events_dedupe_key_idx
    on notification_events(dedupe_key);

create index if not exists notification_events_delivery_status_idx
    on notification_events(sent_at, scheduled_for)
    where sent_at is null;
