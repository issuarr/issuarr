# Using JDownloader 2 for direct downloads

When Issuarr downloads from GetComics, it can download from GetComics' own server and some hosts itself. [JDownloader 2](https://jdownloader.org/) (JD2) can take over the mirror links (Mega, Mediafire, Pixeldrain and other hosts), which helps when those hosts need a premium account or the built-in downloader keeps failing on them.

This is optional. Direct downloads work without it.

## How Issuarr uses JD2

- Issuarr still tries the GetComics server itself first. The mirror links go to JD2 when that fails, or straight away when a post only has hosts JD2 handles.
- Mirrors get JD2 priorities in the host order you set under **Settings > Search providers > Direct downloads**, highest first.
- If JD2 can't be reached or refuses the links, Issuarr hands the download back to its built-in downloader.
- If JD2 gives up on a download (links offline, blocked, or the job never shows up in JD2's download list within about three minutes), Issuarr tries its own downloaders for the same post: file hosts first for big files, GetComics' own server last. The issue is marked Failed only when none of them work, so it doesn't sit at Snatched.
- When JD2 finishes, Issuarr post-processes the download from JD2's download folder like any other download.
- Everything Issuarr sends JD2 gets the comment `issuarr`, so you can tell its downloads apart in JD2.

## Filing downloads you add to JD2 yourself

Issuarr also files downloads you add to JD2 by hand, as long as they carry the comment `issuarr`:

1. Add the links in JD2 as usual.
2. Select the package (or its links) and type `issuarr` in the **Comment** field of JD2's properties panel below the list. Upper or lower case doesn't matter. A Packagizer rule can also set the comment for you.
3. Let JD2 download it to its download folder, the one set under **Download folder**.

About once a minute Issuarr checks JD2's download list. When every link of a marked package has finished (dead mirrors are skipped) and JD2 is done unpacking, Issuarr files the package's comics against your watchlist like a run over the folder Issuarr watches, then takes the package off JD2's download list. The files themselves stay until filing moves them. Comics that don't match a series go to **Downloads > Needs attention**.

- A package in a folder of its own is filed from that folder. When it shares a folder with other things (JD2's download folder itself, say), its files are first moved into a new folder named `Issuarr - <package name>` there, so nothing else in that folder is touched.
- Issuarr's own downloads carry the same comment but are never filed twice: Issuarr knows them by the job id JD2 gave them and the name it gave the package.
- **Post-process downloads** has to be on, and Issuarr has to be able to see JD2's download folder (see step 2 above).

## 1. Set up JD2

JD2 has to accept links from Issuarr over its local API, which is turned off by default.

1. In JD2, open **Settings > Advanced Settings** and search for `Remote API`.
2. Turn on the deprecated API (listed as **Enable Deprecated Api**).
3. If Issuarr runs on another computer or in another container, also turn off the setting that limits the deprecated API to localhost. Otherwise JD2 only answers requests from its own machine.
4. Note the API port (3128 by default) and make sure Issuarr can reach it. In Docker, publish the port or put both containers on the same Docker network.

The deprecated API has no password. Anyone who can reach that port can add downloads, so don't expose it to the internet.

## 2. Share the download folder

Issuarr tells JD2 where to save each download, then opens that same folder to file it, so both programs need to reach one shared folder.

The easiest setup gives the folder the same path in both. In Docker, map the same host folder to the same container path in both containers:

```yaml
services:
  issuarr:
    image: ghcr.io/issuarr/issuarr:latest
    volumes:
      - /path/to/config:/config
      - /path/to/comics:/comics
      - /path/to/downloads:/downloads
  jdownloader2:
    image: jlesage/jdownloader-2
    volumes:
      - /path/to/jd2-config:/config
      - /path/to/downloads:/downloads
```

Here both see the folder as `/downloads`, so `/downloads/jd2` works in both. The JD2 image is only an example.

If the paths differ, that works too. For example, some JD2 templates on Unraid map the folder to `/output` while Issuarr maps it to `/downloads`. Then you enter both paths in step 3.

The user JD2 runs as must be able to write there, and the user Issuarr runs as (`PUID`/`PGID` in Docker) must be able to read and move the files. Keep this folder out of the folder Issuarr watches for new comics, so it doesn't pick up downloads before they finish.

## 3. Set up Issuarr

1. Go to **Settings > Search providers > Direct downloads** and turn on **Download directly from sites**.
2. Go to **Settings > Download clients > JDownloader 2** and turn on **Send mirror links to JDownloader 2**.
3. **JDownloader 2 address:** the API address, for example `http://jdownloader2:3128` or `http://192.168.1.20:3128`. Include the port.
4. **Download folder:** the shared folder as JD2 sees it, for example `/downloads/jd2` (or `/output/complete`).
5. **Same folder, as Issuarr sees it:** only when Issuarr sees that folder under another path, for example `/downloads/complete`. Leave it empty when the path is the same.
6. Make sure **Settings > Files & post-processing > Post-process downloads** is on, or finished JD2 downloads won't be filed.
7. Save.

## Checking it works

Search for a wanted issue whose GetComics post has mirror links. **Tasks > Logs** shows `[JD2]` lines when links are sent, and `[JD2-QUEUE]` lines as the job is watched and filed. In JD2 the package is named after the series and year.

| Log line | What it means |
|---|---|
| `Submission failed ... falling back to DDL queue` | Issuarr couldn't reach JD2. Check the address, the port, and the two Remote API settings. |
| `never reached the JD2 download list` | JD2 got the links but didn't start them, usually because the host is offline or needs an account. |
| `JD2 destination is not configured` | The **Download folder** setting is empty. |
| `Issuarr can't find its files under` | A download you marked `issuarr` finished, but Issuarr can't see its files. Set **Same folder, as Issuarr sees it**. |
| `Issuarr can't reach JD2's download folder` | Issuarr sees the folder under another path, or doesn't have it mapped. Set **Same folder, as Issuarr sees it**. |
