# Notifications

Issuarr can tell you when it grabs an issue, when an issue is filed, and when tagging fails. Set this up in **Settings > Notifications & advanced > Notifications**. Turn on a service, fill in its fields, and press its **Test** button.

The services are Discord, Email, Gotify, Mattermost, ntfy, Pushbullet, Pushover, Slack, Telegram, Prowl, Boxcar and a plain webhook. Each one has a **Notify when an issue is grabbed** switch. Tagging errors are always sent once a service is on.

Covers: Discord, Gotify and ntfy show the issue cover on grabbed, filed, added and Needs attention messages, and Pushover and Telegram do when their image switch is on. Mattermost shows the ComicVine cover as a link. A grabbed issue gets its ComicVine cover, a pack the series cover. The other services are text only.

Two switches at the top of the section pick the other messages, for every service at once (Email also needs its own switch for filed issues):

- **Notify when an issue is downloaded and filed** (on by default): an issue was downloaded, or a folder was post-processed, and the file was filed in the library.
- **Notify when files are added by hand** (off by default): a file was matched to an issue on **Needs attention**, a series was imported with its files, or a recheck found files you put in a series folder yourself. A recheck sends one message per series, such as `Added to Issuarr: Saga (2018) #54, #55`. Services that show covers get the matched file's cover, or for a recheck or import the series cover.

More switches tell you about Issuarr itself. These are checked every five minutes, and each thing is told once (Email sends them without its filed-issues switch):

- **Notify when files land in Needs attention** (on): one message naming the new files.
- **Notify when Import results needs you to choose a match** (on): names the new series waiting for a choice.
- **Notify when a download client can't be reached** (on): one of the clients under **Service status** in the sidebar is down. Sent again only if it comes back and goes down again.
- **Notify when disk space runs low** (on): the library, download or config folder has less free space than **Warn below** (10 GB). Folders on the same disk are checked once. Sent again only after there is space again.
- **Notify when a task starts** and **Notify when a task finishes** (off): the scheduled tasks you tick under **Tasks to notify about**. Auto-Search, Weekly Pullist and DB Updater are ticked at first; RSS Feeds and Folder Monitor run every few minutes, so they would send a lot.

## ntfy

[ntfy](https://ntfy.sh) sends push notifications to the ntfy phone and desktop apps.

- **Server address:** `https://ntfy.sh`, or your own ntfy server.
- **Topic:** the topic you subscribe to in the ntfy app. On the public ntfy.sh server anyone who knows a topic can read it, so pick a name that is hard to guess.
- **Access token:** only needed when your server protects the topic (a `tk_...` token from ntfy).

When an issue is filed, the cover is attached and tapping the notification opens the issue on ComicVine.

## Webhook

The webhook sends a JSON `POST` to any URL, for Home Assistant, n8n, Node-RED or your own script. A `2xx` answer counts as delivered.

```json
{
  "app": "issuarr",
  "event": "downloaded",
  "title": "Download and Postprocessing completed",
  "message": "Issuarr has downloaded and post-processed: Saga (2018) #54",
  "series": "Saga",
  "issue": "#54",
  "year": "2018",
  "issue_id": "123456",
  "comicvine_url": "https://comicvine.gamespot.com/issue/4000-123456/",
  "release": null,
  "provider": null,
  "client": null,
  "time": "2026-10-25T05:30:00Z"
}
```

| Field | Meaning |
|---|---|
| `event` | `snatched` (an issue or pack was sent to a downloader), `downloaded` (an issue was filed), `added` (files were added by hand), `task_started`, `task_finished`, `attention` (new files on Needs attention), `match_needed` (Import results needs a choice), `action_required` (a download client can't be reached), `disk_low`, `tag_error` (tagging failed) or `test` |
| `title`, `message` | The same text the other services show |
| `series`, `issue`, `year` | The issue, when known. For a pack, `issue` is the range, such as `#1 - 60`. For `added`, it lists the issues, such as `#54, #55` |
| `issue_id`, `comicvine_url` | The ComicVine issue, for `downloaded`, and for `added` when one file was matched by hand |
| `release`, `provider`, `client` | For `snatched`: the release name, where it was found and what is downloading it |
| `time` | When the message was sent, in UTC |

Fields that don't apply are `null`. New fields may be added later, but these will keep their names.
