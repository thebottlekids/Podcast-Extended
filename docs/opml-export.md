# Exporting Your Subscriptions (OPML)

Podcast-Extended can export every podcast you can see as a standard OPML 2.0
file. Import that file into AntennaPod or any other OPML-compatible podcast
app to subscribe to all of your shows at once — each show becomes a separate
subscription that uses Podcast-Extended's generated, ad-free RSS feed, not the
publisher's original feed.

## How to export

1. Open the **Podcast Feeds** page.
2. Click the **Export OPML** button (the download icon next to the
   aggregate-feed button).
3. Your browser downloads `podcast-extended-subscriptions.opml`.

What ends up in the file follows the same rules as the feed list:

- **Administrators** export every feed on the server.
- **Regular users** export the feeds they have joined, plus the default
  landing feed.
- **When authentication is disabled**, all feeds are exported.

## Importing into AntennaPod

1. In AntennaPod, open **Settings → Import/Export → OPML import**.
2. Select the downloaded `podcast-extended-subscriptions.opml` file.
3. Confirm the subscription list. Each show is added individually and will
   refresh, stream, and download through Podcast-Extended.

Other podcast apps with OPML import work the same way.

## Security note: the file contains private credentials

When authentication is enabled, each feed URL in the OPML file includes your
personal `feed_token` and `feed_secret` query parameters. These let your
podcast app read the feeds without logging in — which also means anyone who
obtains the file can read your feeds.

- Store the file securely.
- Delete it after importing it into your podcast app.
- Do not share it or commit it to version control.

Exporting is safe to repeat: the same credentials are reused on every export,
so downloading the file again does not invalidate feeds you have already
imported.

## Notes

- Playback state, queues, favorites, and downloaded audio are not part of an
  OPML export — it carries subscriptions only.
- The existing per-feed share links and the aggregate feed are unaffected by
  exporting.
