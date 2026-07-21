# Nitter Plugin WebUI Design

> **Historical design note:** This document predates the 0.16.0 removal of deferred publish and non-translation AI features. Treat it as design archaeology, not current product behavior.


## Goal

Add an AstrBot Plugin Pages dashboard for `astrbot_plugin_nitter_tweets` that makes operational state visible and exposes the safest existing maintenance actions through a native AstrBot WebUI.

The first version is a Nitter operations console, not a replacement for `_conf_schema.json`. AstrBot's built-in config page remains the source for broad configuration such as Nitter instances, media limits, AI providers, prompts, and performance tuning.

## User Value

The current plugin has many command-driven maintenance flows:

- `/推文状态`
- `/推文检查`
- `/推文队列`
- `/推文发布`
- `/推文缓存清理`
- `/推文记录清理`
- `/订阅导入`
- `/订阅删除`
- `/订阅导出`

These commands work, but they are hard to scan when there are multiple `tweet_groups`, push targets, deferred queues, and failed pending rows. The dashboard should turn that state into a dense, readable admin surface.

## Scope

### Version 1

Version 1 includes:

- Dashboard overview.
- Group and subscription overview.
- Pending queue overview and list.
- Safe group-level actions.
- Simple subscription import/delete for existing groups.
- Mirror diagnostics.

Version 1 will not attempt full editing of every `tweet_groups` field.

### Version 2 Candidates

Possible follow-up work:

- Full group editor for `tweet_groups`.
- Push target editor with UMO validation help.
- Export and import of subscription configuration.
- Single pending-row delete or retry.
- Recent check result history.
- SSE progress for long checks or publishes.

### Out Of Scope

The first version does not include:

- Full `_conf_schema.json` replacement.
- Editing AI translation, AI vision, AI comment, media download, or concurrency settings.
- Direct SQLite editing.
- Live log streaming.
- Frontend build tooling.

## Architecture

### Backend

Add a small Web API module, tentatively `plugin_api.py`, following the split used by the referenced `astrbot_plugin_stealer`.

`main.py` stays light:

- Instantiate the API provider.
- Register plugin page routes through `context.register_web_api(...)`.
- Keep lifecycle, commands, scheduler, and service wiring as they are.

The API module should call existing plugin services instead of duplicating behavior:

- `self.plugin.scheduler.config_reader.schedule_groups(...)`
- `self.plugin.scheduler.storage.get_pending_queue_summary(...)`
- `self.plugin.scheduler.storage.get_pending_tweets(...)`
- `self.plugin.scheduler.run_check(...)`
- `self.plugin.scheduler.publish_pending(...)`
- `self.plugin.media.clear_non_staged_cache(...)`
- `self.plugin.scheduler.storage.clear_seen_records(...)`

### Frontend

Add a Plugin Page at `pages/dashboard/`.

Suggested files:

- `pages/dashboard/index.html`
- `pages/dashboard/app.js`
- `pages/dashboard/style.css`
- `pages/dashboard/_page.json`

Use `window.AstrBotPluginPage` directly. The page should call backend APIs through `bridge.apiGet(...)` and `bridge.apiPost(...)`. Static assets must use relative paths.

No bundler, package manager, or extra frontend dependency is required for version 1.

## Pages And Views

### Overview

Show:

- Scheduler running state.
- `schedule_enabled`.
- Total groups.
- Enabled groups.
- Total watched users.
- Total push targets.
- Invalid push targets.
- Total pending tweets.
- Failed pending tweets.
- Staged media count.
- Basic feature flags: images, videos, translation, AI vision, AI comment, deferred publish.

The overview should be compact and suited for repeated admin use.

### Groups

Show one row or panel per schedule group:

- Name and `group_id`.
- Enabled/disabled state.
- Watch user count.
- Push target count.
- Invalid target count.
- Interval check state.
- Daily check times.
- Deferred publish state.
- Deferred publish times.
- Plain-text filter state.
- Fetch limit.

Group details should show:

- Watched users.
- Push targets.
- Invalid targets.
- Aliases.
- Duplicate and invalid watch-user entries.

Safe actions:

- Refresh.
- Run check for a selected group.
- Publish pending queue for a selected group.

Optional version 1 actions:

- Add subscriptions to an existing group.
- Delete subscriptions from an existing group.

### Pending Queue

Show group-level summaries:

- Pending count.
- Failed count.
- Media count.
- Oldest created time.
- Newest created time.
- Top pending users.

Show pending tweet rows:

- Pending row ID.
- Group.
- Username.
- Status ID.
- Original link.
- Published text timestamp if available.
- Created time.
- Scheduled time if available.
- Fail count.
- Last error.
- Delivered targets.
- Media count and media kinds.

Rows should be read-only in version 1. Publishing remains a group-level action.

### Mirror Diagnostics

Show configured Nitter instances and provide a small probe form:

- Username.
- Limit.
- Instance override.

The backend should reuse the same behavior as `/镜像测试`: full URL instances only, no config mutation, and no seen writes.

## API Design

All routes are registered under `/{PLUGIN_NAME}/...`.

Suggested routes:

- `GET /astrbot_plugin_nitter_tweets/web/overview`
- `GET /astrbot_plugin_nitter_tweets/web/groups`
- `GET /astrbot_plugin_nitter_tweets/web/pending?group_id=...&limit=...`
- `POST /astrbot_plugin_nitter_tweets/web/check`
- `POST /astrbot_plugin_nitter_tweets/web/publish`
- `POST /astrbot_plugin_nitter_tweets/web/cache/clear`
- `POST /astrbot_plugin_nitter_tweets/web/seen/clear`
- `POST /astrbot_plugin_nitter_tweets/web/subscriptions/import`
- `POST /astrbot_plugin_nitter_tweets/web/subscriptions/delete`
- `POST /astrbot_plugin_nitter_tweets/web/mirror/probe`

API responses should be JSON objects with:

- `success: boolean`
- `error: string` when failed
- operation-specific payload fields when successful

Long operations such as check and publish can return the existing formatted scheduler message plus structured summary fields where easy.

## Safety Rules

- Dangerous actions require explicit confirmation in the UI.
- Seen clearing must never delete subscriptions, pending rows, or media.
- Cache clearing must only clear ordinary cache and preserve staged media.
- Version 1 does not expose direct delete for pending rows.
- Web API write paths should reuse existing command/service logic where possible.
- Save config only when a subscription import/delete actually changes users.
- After subscription import/delete, sync schedule groups to SQLite just like command handlers do.

## Error Handling

Backend errors should:

- Log developer details with the AstrBot logger.
- Return concise user-facing JSON errors.
- Return service-unavailable errors when scheduler or storage is not initialized.

Frontend errors should:

- Show a visible inline error or toast.
- Keep the last successful data visible when refresh fails.
- Disable action buttons while the action is running.
- Require confirmation for destructive operations.

## Testing

Backend tests:

- Web API registration route list.
- Overview payload from fake scheduler/config/storage objects.
- Pending queue serialization from `PendingTweetRecord`.
- Subscription import/delete behavior mirrors command behavior.
- Seen clear and cache clear do not call unrelated deletion paths.
- Mirror probe validates full URL instance and does not mutate config.

Frontend checks:

- `node --check pages/dashboard/app.js`.
- Static HTML/CSS smoke check.
- Browser or in-app visual check if a local AstrBot page environment is available.

Regression tests should prefer existing test style in `tests/test_subscription_import.py` and `tests/test_pending_storage.py`.

## Documentation

Update:

- `README.md`: add Plugin Pages dashboard summary and safe-operation notes.
- `docs/advanced.md`: document WebUI views, what it can operate on, and what remains in AstrBot config.
- `CHANGELOG.md`: note the new dashboard before release.

The docs must explicitly say that the dashboard does not replace the AstrBot config page and does not edit AI/media/performance settings in version 1.
