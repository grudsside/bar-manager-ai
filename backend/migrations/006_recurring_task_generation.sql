alter table recurring_rules
    add column if not exists frequency text not null default 'daily',
    add column if not exists weekdays text[] not null default '{}'::text[],
    add column if not exists next_due_at timestamptz,
    add column if not exists source_chat_id bigint,
    add column if not exists original_text text;

alter table recurring_rules
    drop constraint if exists recurring_rules_frequency_check;

alter table recurring_rules
    add constraint recurring_rules_frequency_check
    check (frequency in ('daily', 'weekly'));

alter table recurring_rules
    drop constraint if exists recurring_rules_weekdays_check;

alter table recurring_rules
    add constraint recurring_rules_weekdays_check
    check (weekdays <@ array['MO','TU','WE','TH','FR','SA','SU']::text[]);

create index if not exists recurring_rules_next_due_idx
    on recurring_rules(next_due_at)
    where enabled = true and next_due_at is not null;

create unique index if not exists tasks_recurring_source_reference_idx
    on tasks(source_reference)
    where source_type = 'recurring' and source_reference is not null;

alter table telegram_pending_actions
    drop constraint if exists telegram_pending_actions_action_type_check;

alter table telegram_pending_actions
    add constraint telegram_pending_actions_action_type_check
    check (
        action_type in (
            'create_task',
            'update_task_status',
            'create_recurring_rule',
            'disable_recurring_rule'
        )
    );
