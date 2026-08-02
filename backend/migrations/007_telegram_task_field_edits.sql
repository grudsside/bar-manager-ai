alter table telegram_pending_actions
    drop constraint if exists telegram_pending_actions_action_type_check;

alter table telegram_pending_actions
    add constraint telegram_pending_actions_action_type_check
    check (
        action_type in (
            'create_task',
            'update_task_status',
            'update_task_fields',
            'create_recurring_rule',
            'disable_recurring_rule'
        )
    );
