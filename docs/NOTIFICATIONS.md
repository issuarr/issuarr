# Notifications

Issuarr can tell you when it grabs an issue, when an issue is filed, and when tagging fails. Set this up in **Settings > Notifications & advanced > Notifications**. Turn on a service, fill in its fields, and press its **Test** button.

The services are Discord, Email, Gotify, Mattermost, ntfy, Pushbullet, Pushover, Slack, Telegram, Prowl, Boxcar and a plain webhook. Each one has a **Notify when an issue is grabbed** switch. Filed issues and tagging errors are always sent once a service is on (Email has its own switch for filed issues).

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
| `event` | `snatched` (an issue or pack was sent to a downloader), `downloaded` (an issue was filed), `tag_error` (tagging failed) or `test` |
| `title`, `message` | The same text the other services show |
| `series`, `issue`, `year` | The issue, when known. For a pack, `issue` is the range, such as `#1 - 60` |
| `issue_id`, `comicvine_url` | The ComicVine issue, for `downloaded` only |
| `release`, `provider`, `client` | For `snatched`: the release name, where it was found and what is downloading it |
| `time` | When the message was sent, in UTC |

Fields that don't apply are `null`. New fields may be added later, but these will keep their names.
