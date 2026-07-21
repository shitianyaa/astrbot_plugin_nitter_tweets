# Nitter Plugin WebUI V2 Group Management Design

> **Historical design note:** This document predates the 0.16.0 removal of deferred publish and non-translation AI features. Treat it as design archaeology, not current product behavior.


## Goal

Extend the existing AstrBot Plugin Pages dashboard with an interactive group-management surface that turns the current read-mostly `分组订阅` tab into a practical control panel for day-to-day administration.

Version 2 group management keeps the overall product direction of the existing WebUI:

- It is still an AstrBot-native operations console.
- It is still not a full replacement for `_conf_schema.json`.
- It focuses on high-frequency edits that operators want to perform in context.

This design is a follow-up to `docs/superpowers/specs/2026-07-05-nitter-webui-design.md`, which introduced the version 1 dashboard.

## User Value

The current `分组订阅` tab exposes rich state but very few direct edits:

- Operators can inspect groups, watch users, push targets, queue counts, and scheduling flags.
- Operators can run `立即检查`, `发布暂存`, `导入`, and `删除` watch users.
- Most group settings remain read-only and require a context switch into the AstrBot config page.

The next improvement should remove the most frustrating "can see but cannot operate" gaps without taking on the risk of a full config editor.

## Product Direction

### Selected Scope

Version 2 group management is **operations panel + high-frequency light editing**.

That means:

- Editing existing groups directly in the WebUI.
- Creating new custom groups from safe defaults.
- Deleting custom groups with strong confirmation.
- Keeping complex global settings in the AstrBot config page.

### Explicitly Not A Full Config Editor

The WebUI will **not** become the primary editor for:

- AI provider and prompt configuration.
- Media download and attachment limits.
- Nitter instance pools.
- Concurrency and performance tuning.
- Full deferred-publish global configuration.
- All hidden or legacy-compatible `tweet_groups` fields.

This boundary is important because the current runtime behavior mixes true per-group fields with inherited or global fields, and pretending otherwise in the UI would create configuration drift and operator confusion.

## Selected Interaction Model

The approved interaction model is:

- **Left-side group list**
- **Right-side group detail editor**

This replaces the current "one large read-only group card" pattern for the `分组订阅` tab.

### Why This Model

The existing group surface already holds many data points:

- group identity
- enabled state
- watch users
- push targets
- invalid entries
- queue state
- interval-check participation
- daily check times
- deferred-publish participation
- plain-text filtering

Trying to convert the current card into inline-editable controls would make the page denser and less predictable. A list-detail structure gives the WebUI room to grow into future push-target and queue actions without collapsing into a crowded inspector.

## Information Architecture

### Left Column: Group List

The left column becomes the navigation surface for groups.

Each list item shows:

- group display name
- `group_id`
- enabled or disabled state
- watch-user count
- push-target count
- invalid-target count
- attention state when the group has warnings such as invalid watch users, invalid push targets, or failed pending rows

The list header includes:

- `新建分组`
- optional compact summary such as total groups or selected-group state

Behavior:

- clicking a group loads it into the right-side editor
- the currently selected group remains highlighted
- unsaved changes on the selected group add a visible marker such as `未保存` or a small status dot
- attempting to switch away from a dirty editor requires confirmation

### Right Column: Group Detail Editor

The right column is the primary editing surface.

It is organized into these sections:

1. `基本信息`
2. `检查策略`
3. `暂存发布`
4. `内容过滤`
5. `关注账号`
6. `推送目标`
7. `运行摘要`

The editor header includes:

- group name
- current enabled state badge
- `保存更改`
- `删除分组`

The old generic kicker text `AstrBot Plugin Page` should be removed. The page header should keep the product title `Nitter 推文面板`, and the active tab plus section title should provide local context.

## Editable Fields

### Basic Information

Editable:

- `name`
- `enabled`

Display-only:

- `group_id`

Rationale:

- `group_id` is the stable storage identifier for seen isolation, queue storage, and compatibility behavior.
- letting WebUI users rename `group_id` would make it too easy to break continuity between configuration and runtime state
- `group_id` should therefore be shown clearly, with an optional copy action, but not edited in version 2

### Aliases

Aliases were discussed during design exploration, but the selected scope should **not** make them a first-class editable control in this phase.

Rationale:

- `aliases` are currently treated as a compatibility-oriented field
- the schema already marks them invisible in the main UI
- alias editing adds name-resolution risk for `/推文检查 分组名` and related commands

Version 2 should either:

- show aliases read-only in an advanced details block, or
- hide them entirely from the first release of the new editor

The default recommendation is to hide them from the main editing flow for now.

### Check Strategy

Editable:

- `interval_check_enabled`
- `daily_check_times`

Read-only with explicit inherited wording:

- `check_interval_minutes`

Important constraint:

`check_interval_minutes` is currently a **global** setting, not a per-group setting. The detail panel must describe this honestly, for example:

- `间隔检查：已参与`
- `检查间隔：继承全局 30 分钟`

The editor must not present a per-group numeric input for interval minutes unless the runtime configuration model changes in a future release.

### Deferred Publish

Editable:

- `deferred_publish_enabled`

Read-only with explicit inherited wording:

- `deferred_publish_times`

Important constraint:

The current implementation uses global deferred-publish times. The group only decides whether it participates.

The editor should therefore display:

- a group-level enable switch
- the global publish times as read-only context such as `继承全局：08:00`

It must not imply that each group owns a separate publish-time list.

### Plain-Text Filtering

Editable:

- `filter_plain_text_enabled`

This is a true per-group behavior and fits the scope well.

### Watch Users

This remains action-based rather than form-buffered.

The detail panel should include:

- a batch input field for comma-separated usernames
- `导入`
- `删除`
- the current group watch-user chips
- invalid watch-user chips
- duplicate-entry chips or summary

The backend behavior should continue to reuse the existing import and delete semantics so that normalization, validation, and SQLite sync stay consistent with commands and version 1.

### Push Targets

Version 2 group management should keep push targets **read-only** in this phase.

The detail panel should show:

- target count
- target list
- invalid target list
- a short note that push-target editing is planned for the next phase

This matches the approved roadmap order:

1. group management
2. push targets
3. pending queue actions
4. overview shortcuts

### Runtime Summary

The right-side panel should end with a compact status block showing current runtime facts for the selected group, such as:

- pending count
- failed pending count
- invalid push-target count
- invalid watch-user count

These are read-only but useful while editing.

## Save Model

### Buffered Save For Group Settings

The following fields use a shared `保存更改` action:

- `name`
- `enabled`
- `interval_check_enabled`
- `daily_check_times`
- `deferred_publish_enabled`
- `filter_plain_text_enabled`

The save button activates only when buffered changes differ from the last loaded server state.

### Immediate Actions For Watch Users

Watch-user import and delete remain immediate actions.

Rationale:

- the plugin already has stable behavior for normalization, deduplication, and sync
- users expect immediate feedback for add/remove account actions
- forcing watch-user changes into the shared save buffer would complicate the UI without improving consistency

### Unsaved Change Protection

When buffered edits exist, the UI must protect against accidental loss:

- switching selected groups prompts the user
- refreshing the page prompts the user if possible
- deleting the currently edited group resets the dirty state only after successful deletion

## Group Creation

### First-Phase Rule

Version 2 supports creating groups from **safe defaults**.

The user chose this creation model because it reduces decision load and keeps the new flow stable.

### Default New Group Values

A new group is created with:

- generated stable `group_id`
- generated display name such as `新分组 1`
- `enabled = false`
- empty `watch_users`
- empty `push_targets`
- `interval_check_enabled = true`
- empty `daily_check_times`
- `deferred_publish_enabled = false`
- `filter_plain_text_enabled = false`

Notes:

- `interval_check_enabled = true` means the group is eligible for interval checks when enabled, matching the current group template behavior
- because the group itself starts disabled, it remains operationally safe by default

### Group ID Generation

The backend owns `group_id` generation.

The generated ID should:

- be deterministic enough for operators to read
- avoid collisions with existing group IDs
- never reuse reserved default-group semantics

A simple collision-checked pattern such as `group_1`, `group_2`, `group_3` is acceptable for this phase.

The frontend should not ask the operator to type a storage ID.

## Group Deletion

### Supported But Strongly Guarded

Version 2 supports group deletion, but only with explicit danger handling.

The selected product rule is:

- support force delete
- require secondary confirmation
- remove the group's runtime data together with the configuration entry

### Protected Groups

The default group must not be deletable.

That includes any ID or alias that normalizes to the default group identity, such as:

- `default`
- legacy `global`
- default-group compatibility aliases

The WebUI should disable the delete affordance for protected groups and explain why.

### Deletion Confirmation

The delete flow must make impact obvious:

- first confirmation opens a danger dialog
- the dialog states that the group configuration, push records, pending queue rows, and staged media for that group will be removed
- the final destructive action is a second explicit confirmation

The exact confirmation UX can be button-based or typed confirmation, but it must be clearly stronger than a single casual click.

### Deletion Semantics

Deleting a custom group removes:

- the `tweet_groups` configuration entry
- SQLite runtime rows for that `group_id`
- staged media under `cache/staged/<group_id>/`

This is important because runtime cleanup cannot rely on configuration sync alone.

## Backend Design

### Existing Behavior To Reuse

The current backend already has safe patterns for:

- schedule-group parsing through `SchedulerConfigReader`
- subscription import and delete
- config save
- sync from config into SQLite runtime storage

Version 2 should continue to reuse those patterns instead of inventing a second configuration path.

### New Backend Surface

Keep `plugin_api.py` as the HTTP surface, but move group-editing logic into a focused helper module such as:

- `webui_groups.py`, or
- `group_editor.py`

The helper owns:

- loading and updating raw `tweet_groups`
- safe default group creation
- group-field validation
- generated group ID selection
- delete protection rules

This keeps `plugin_api.py` from turning into another large business-logic file.

### New API Routes

Add these routes under the existing plugin prefix:

- `POST /astrbot_plugin_nitter_tweets/web/groups/create`
- `POST /astrbot_plugin_nitter_tweets/web/groups/update`
- `POST /astrbot_plugin_nitter_tweets/web/groups/delete`

The existing `GET /astrbot_plugin_nitter_tweets/web/groups` remains the read model for both the group list and the detail panel.

### Update Route Contract

`web/groups/update` should accept:

- `group_id`
- editable group fields only

It must reject:

- attempts to change `group_id`
- unknown target groups
- ambiguous or conflicting names
- invalid time values

The update flow should:

1. load current `tweet_groups`
2. locate the target raw group by normalized `group_id`
3. replace only allowed fields
4. save config
5. rebuild parsed schedule groups
6. sync config groups to SQLite runtime storage
7. return the updated serialized group payload

### Create Route Contract

`web/groups/create` should:

1. load raw `tweet_groups`
2. allocate a new `group_id`
3. generate a default display name that does not collide with existing names
4. append the new raw group entry
5. save config
6. rebuild parsed schedule groups
7. sync config groups to SQLite runtime storage
8. return the created group payload

### Delete Route Contract

`web/groups/delete` should:

1. validate the target `group_id`
2. reject protected groups
3. require explicit destructive confirmation fields
4. remove the config entry
5. save config
6. delete runtime data for the target `group_id`
7. delete staged media for the target `group_id`
8. sync remaining config groups to SQLite runtime storage
9. return a concise deletion summary

## Validation Rules

### Name Validation

Version 2 should validate group names conservatively.

At minimum, saving must reject names that would collide with existing command resolution in obvious ways, including conflicts with:

- another group's `group_id`
- another group's display name
- another group's aliases

The purpose is to avoid making `/推文检查 分组名` or other group-resolution behavior ambiguous.

### Time Validation

`daily_check_times` must stay in the current `HH:MM` format and reuse the same parsing rules already applied by `SchedulerConfigReader`.

The frontend should provide guardrails, but the backend remains authoritative.

### Immutable Identity

The update route must treat `group_id` as immutable in this version.

## Runtime Data Cleanup Design

### SQLite Cleanup

Deleting a group requires a direct storage cleanup path, not just a resync.

Add an explicit storage method that removes rows for one `group_id` from:

- `groups`
- `group_users`
- `group_targets`
- `seen_tweets`
- `pending_media` linked to that group's pending rows
- `pending_tweets`

This should live in the SQLite and storage adapter layers so the API does not reach into raw SQL itself.

### Staged Media Cleanup

Add a media-layer helper that removes:

- `cache/staged/<group_id>/`

This cleanup must be scoped to the deleted group only and must not affect staged media for other groups.

### Ordering

Preferred delete ordering:

1. remove config entry
2. save config
3. delete runtime storage rows
4. delete staged media directory
5. sync remaining groups

This keeps the configuration as the source of truth while still ensuring runtime data is actually removed.

## Frontend Changes

### Tab Structure

The existing `分组订阅` tab remains the entry point, but its layout changes from:

- toolbar + stacked group cards

to:

- left group list + right detail editor

### Top-Level Copy

Adjust visible wording:

- remove `AstrBot Plugin Page`
- keep `Nitter 推文面板` as the main title
- let the selected tab and section heading communicate local context

### Preserved Actions

Keep the existing quick actions in the group context:

- `立即检查`
- `发布暂存`

These can stay in the detail header for the selected group.

## Testing

### Backend Tests

Extend `tests/test_plugin_api.py` with cases for:

- create group from safe defaults
- update editable fields successfully
- reject `group_id` mutation
- reject delete of default group
- reject delete without destructive confirmation
- delete custom group and report cleanup summary
- reject name collisions

### Storage Tests

Extend `tests/test_pending_storage.py` or `tests/test_storage_adapter.py` with cases for:

- deleting one group removes group-specific runtime rows
- deleting one group does not remove runtime rows for another group
- pending-media rows linked to deleted pending tweets are removed

### Media Cleanup Tests

Extend `tests/test_media_cleanup.py` with a case for:

- deleting staged media by group ID removes only `cache/staged/<group_id>/`

### Frontend Tests

Extend `tests/test_dashboard_frontend.py` with checks for:

- presence of left-side group list structure
- presence of detail-panel editing structure
- no `AstrBot Plugin Page` header text
- dirty-state marker handling hooks
- global inherited fields rendered as read-only context rather than editable controls

## Documentation Updates

Update:

- `README.md`
- `docs/advanced.md`
- `CHANGELOG.md`

Documentation must clearly state:

- the `分组订阅` tab now supports creating, editing, and deleting custom groups
- `group_id` is still immutable in the WebUI
- default group deletion is blocked
- interval minutes and deferred publish times remain global settings
- push-target editing is still deferred to a later phase

## Out Of Scope For This Phase

This design intentionally does not include:

- push-target editing
- queue-row single delete or retry
- overview quick actions redesign
- alias editing
- `group_id` editing
- per-group interval-minute editing
- per-group deferred publish times
- a full `_conf_schema.json` replacement

## Success Criteria

This phase is successful when:

- operators can create a new empty custom group from the WebUI
- operators can edit high-frequency group fields without leaving the dashboard
- operators can safely delete a custom group with explicit impact confirmation
- the UI no longer presents global fields as if they were per-group editable
- runtime storage and staged media are cleaned when a custom group is deleted
- the page header no longer uses the generic `AstrBot Plugin Page` copy
