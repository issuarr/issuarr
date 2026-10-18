# Using AirDC++

Issuarr can search Direct Connect hubs through an [AirDC++ Web Client](https://airdcpp-web.github.io/) and grab comics from them. AirDC++ downloads the file, and Issuarr then files it like any other download.

## 1. Set up Issuarr

1. Go to **Settings > Search providers > AirDC++** and turn on **Search AirDC++ hubs**.
2. **Address:** the AirDC++ Web Client address, for example `http://airdcpp:5600`. **User name** and **Password** are an AirDC++ web user.
3. Choose **Where downloads go** (see below) and fill in the folders it asks for.
4. Optionally list **Hubs to search**. Leave it empty to search every hub AirDC++ is connected to.
5. Press **Test AirDC++**, then save.

## 2. Choose where downloads go

Issuarr has to open the finished file, so it needs to know where AirDC++ saved it. There are two ways.

### Issuarr sends the download folder (default)

Issuarr tells AirDC++ to save each grab in **Download folder**, then opens that same folder. The folder has to have **the same path in both programs**. In Docker, map the same host folder to the same container path in both containers:

```yaml
services:
  issuarr:
    image: ghcr.io/issuarr/issuarr:latest
    volumes:
      - /path/to/downloads:/downloads
  airdcpp:
    image: gangefors/airdcpp-webclient
    volumes:
      - /path/to/downloads:/downloads
```

Here both see `/downloads`, so `/downloads/airdcpp` works as **Download folder**. The AirDC++ image is only an example. If **Download folder** is empty, Issuarr uses an `airdcpp` folder inside the direct-download folder.

### AirDC++ uses its own download folder

Pick this when the two programs see the folder under different paths: AirDC++ on Windows with Issuarr in Docker, the containers mounting the folder at different paths, or AirDC++ on another computer with the folder shared over the network. Issuarr no longer sends a folder, so AirDC++ saves to the download folder set in its own settings. Issuarr still sends the file name.

- **Download folder:** AirDC++'s download folder **as Issuarr sees it**, for example `/downloads/airdcpp`. Issuarr won't create it, so if it's missing the grab stops with a message in the log instead of waiting for a file that can't appear.
- **AirDC++ download folder, as AirDC++ sees it:** optional, for example `D:\Downloads` or `/downloads`. When AirDC++ reports a finished file under this folder, Issuarr swaps that part of the path for **Download folder**, so files AirDC++ puts in subfolders are found too. Windows paths are matched without regard to case. When it's empty, Issuarr looks for the file directly in **Download folder**.

For example, with AirDC++ on Windows saving to `D:\Downloads` and that folder mounted in Issuarr's container at `/downloads/airdcpp`, a file AirDC++ reports as `D:\Downloads\Comics\Batman 001.cbz` is opened at `/downloads/airdcpp/Comics/Batman 001.cbz`.

In both modes, the user Issuarr runs as (`PUID`/`PGID` in Docker) must be able to read and rename the files.
