import logging
import sys
import configs as cfg
import ntpath
import os
import hashlib
import time
import argparse
import settings

from pathlib import Path
from qbittorrentapi import Client
from pyarr import RadarrAPI
from apscheduler.schedulers.background import BackgroundScheduler

parser = argparse.ArgumentParser()
parser.add_argument("--add-id", help="Add a TMDBid to watch.", type=int)
parser.add_argument("--skip-hash", help="Skip the file hash check.", action="store_true")
parser.add_argument("--force-state-change", help="Skip the file hash check.", type=int)
parser.add_argument("-c", "--config", help="Path to the config file.", type=int)
args = parser.parse_args()

if args.config is not None:
    settings.config_file = args.config
else:
    dir_path = f"{str(Path.home())}/.config/seedarr/"
    dir_path = os.path.join(dir_path, 'config.json')
    settings.config_file = dir_path

logger = logging.getLogger("seedarr")
logger.setLevel(logging.INFO)
console = logging.StreamHandler(sys.stdout)
console.setLevel(cfg.read_config("loglevel").upper())
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(filename)s - %(message)s', datefmt='%y-%m-%d,%H:%M:%S')
console.setFormatter(formatter)
logger.addHandler(console)

sched = BackgroundScheduler(timezone="America/New_York")

def init():
    if args.add_id is not None:
        settings.watch.append(args.add_id)
    

def check_endpoints():
    logger.info("Checking endpoints...")
    try:
        logger.info(f"Checking connection to torrent client({cfg.read_config('torrent_client')})...")
        settings.client = Client(host=cfg.read_config("torrent_host"), username=cfg.read_config("torrent_username"), password=cfg.read_config("torrent_password"))
        logger.info(settings.client.app_version())
        logger.info("Success!")
    except Exception as e:
        logger.error(f"Error connecting to the torrent client: {e}")
    try:
        logger.info(f"Checking connection to Radarr...")
        settings.radarr = RadarrAPI(cfg.read_config("radarr_host"), cfg.read_config("radar_api_key"))
        logger.info(settings.radarr.get_health())
        logger.info("Success!")
    except Exception as e:
        logger.error(f"Error connecting to the torrent client: {e}")

def get_missing():
    movies = settings.radarr.get_movie()    
    for movie in movies:
        if movie['monitored']:
            if not movie['hasFile'] and movie['tmdbId'] not in settings.watch:
                logger.info(f"Adding to monitored movies: '{movie['title']}' with id {movie['tmdbId']}")
                settings.watch.append(movie['tmdbId'])

def update_state():
    found = False
    logger.info("Looking for state changes...")
    for id in settings.watch:
        movie = settings.radarr.get_movie(id)
        if len(movie) == 1:
            movie = movie[0]
            if movie['hasFile'] or movie['tmdbId'] == args.force_state_change:
                found = True
                logger.info(f"Movie '{movie['title']}' has changed state, queueing for torrent client check.")
                settings.changed.append(id)
    if not found:
        logger.info("No state changes found.")


def blake(file):
    with open(file, "rb") as f:
        file_hash = hashlib.blake2b()
        while chunk := f.read(8192):
            file_hash.update(chunk)

    return file_hash.hexdigest()

def move_torrent(t, movie):
    new_path = movie['movieFile']['path'].replace(cfg.read_config("radarr_library_directory"), cfg.read_config("torrent_library_directory"))
    if not args.skip_hash:
        logger.info("Comparing hashes to ensure files are identical")
        lib_file = blake(t['content_path'])
        download_file = blake(new_path)
        logger.info(f"{lib_file} -- {t['content_path']}")
        logger.info(f"{download_file} -- {new_path}")
        if not lib_file == download_file:
            logger.error("Invalid hash.")
            return
    logger.info(f"Moving torrent({t['hash']}) from {t['content_path']} to {new_path}")
    try:
        og_path = t['content_path']
        t.set_location(location=os.path.dirname(new_path))
        logger.info("Torrent moved. Removing from watch queue.")
        settings.changed.remove(movie['tmdbId'])
        settings.watch.remove(movie['tmdbId'])
        logger.info("Queueing for deletion")
        settings.to_delete.append({"torrent": t, "original_path": og_path})
    except Exception as e:
        logger.error(f"Could not move torrent: {t['name']}. {e}")

def verify_torrents():
    found = False
    torrents = settings.client.torrents_info(category=cfg.read_config("torrent_category"))
    if len(torrents) > 0:
        logger.info("Looking for torrent file match...")
    for id in settings.changed:
        movie = settings.radarr.get_movie(id)
        if len(movie) == 1:
            movie = movie[0]
            logger.info(f"Looking for movie: {movie['title']} ({movie['movieFile']['relativePath']})")
            for t in torrents:
                if ntpath.basename(t['content_path']) == movie['movieFile']['relativePath']:
                    found = True
                    logger.info(f"Found a match with torrent: {t['name']}. Changing location")
                    move_torrent(t, movie)
    if not found and len(torrents) > 0:
        logger.info("No matching torrent found.")

def check_and_delete():
    deleted = []
    for torrent in settings.to_delete:
        status = settings.client.torrents_info(torrent_hashes=torrent["torrent"]['hash'])[0]
        if status['state'] not in ["error", "checkingUP", "moving", "unknown"]: # User provided acceptable state
            logger.info(f"Torrent's state is {status['state']}, deleting: {torrent['original_path']}")
            # ACTUALLY DELETE THE FILE
            deleted.append(torrent)
        else:
            logger.info(f"Torrent's state is {status['state']}, not ready for deletion.")
    for i in deleted:
        settings.to_delete.remove(i)

def tick():
    get_missing()
    update_state()
    verify_torrents()
    check_and_delete()

init()
check_endpoints()
logger.info("Starting scheduler...")
sched.start()
sched.add_job(tick, 'interval', seconds=cfg.read_config("scan_interval"), max_instances=1, id="main_loop")
logger.info("Ready.")
while True:
    time.sleep(1)

# need to delete torrent (schedule for deletion if status not checking)
# need save/load ids
# 1 job per task step (seperate interval)
# watch to changed remove right away