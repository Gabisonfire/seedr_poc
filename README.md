# Seedr
Seedr is a companion for Radarr and Qbittorrent.

It will monitor your Radarr downloads. Once downloaded and copied to your library, it will point your torrent client to the file in your library and delete the file from your download directory.

### Use cases
- Your download and library folders are on seperate drives, therefore won't support hardlinks
- You don't have a seed limit and want to seed downloads from your Radarr library

### Usage
- Disable `Use Hardlinks instead of Copy` in Radarr. (Settings -> Media Management (Show Advanced))
- Rename `config.json.example` to `config.json`, adapt the included `docker-compose.yml` and use `docker-compose up -d`
  - Mount a directory containing the config file if you want some persistence (recommended). Seedr will store the state of missing movies in that directory.

### config.json
| Config | Description | Options |
|:-------|:-----------:|:-------:|
| loglevel | Level of logging details | info, debug, warning, error |
| torrent_client | Your torrent client (qbittorrent is the only client supported at the moment) | qbittorrent |
| torrent_host | Your torrent client's url | ex: qbittorrent.example.com |
| torrent_username | Your torrent client's  username | ex: admin |
| torrent_password | Your torrent client's password | ex: hunter2 |
| torrent_category[^1] | The category assigned to torrents by Radarr. | ex: radarr |
| radarr_host | The Radarr url | ex: http://radarr.example.com |
| radar_api_key[^2] | Your Radarr api key | 1234456789asd123456789asd |
| torrent_dowload_directory | The directory where your torrent client stores the downloads | ex: /mnt/downloads |
| torrent_library_directory | The directory where you store your movies relative to your torrent client  | ex: /mnt/movies |
| radarr_library_directory[^3] | Your Radarr library folder | ex: /etc/radarr/movies |
| missing_status_scan_interval | The interval in secs when Seedr looks for "missing" movies | 30 |
| state_change_scan_interval | The interval in secs where Seedr looks for status changes | 30 |
| match_and_move_torrents_scan_interval | The interval in secs where Seedr tries to find matches for torrents | 300 |
| check_and_delete_scan_interval | The interval in secs where Seedr checks for completed moves and deletes the file in the downloads fodler | 300 |
| calculate_hashes | Calculate hashes when matching files | true, false |

[^1]: This is optional however highly recommended. This also limits the torrents processed.

[^2]: In Radarr: Settings -> General -> Security -> API Key

[^3]: This is the path where Radarr creates your movie folders. It can be the same as `torrent_library_directory` if they use the same filesystem but if you run Radarr in docker, it could be different. Seedr will use this to tell you torrent client where the movie is. Similar to Radarr's `Remote Path Mappings`.