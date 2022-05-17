import logging
import sys
import configs as cfg
import ntpath
import os
import hashlib
import time
import argparse
import signal
import json
import shutil
import settings

from pathlib import Path
from qbittorrentapi import Client
from pyarr import RadarrAPI
from apscheduler.schedulers.background import BackgroundScheduler

parser = argparse.ArgumentParser()
parser.add_argument("--add-id", help="Add a TMDBid to watch.", type=int)
parser.add_argument("--skip-hash", help="Skip the file hash check.", action="store_true")
parser.add_argument("--no-delete", help="Don't delete the original file.", action="store_true")
parser.add_argument("--no-save", help="Don't save.", action="store_true")
parser.add_argument("--force-state-change", help="Skip the file hash check.", type=int)
parser.add_argument("-c", "--config", help="Path to the config file.", type=str)
args = parser.parse_args()

if args.config is not None:
    settings.config_file = args.config
else:
    dir_path = f"{str(Path.home())}/.config/seedr/"
    dir_path = os.path.join(dir_path, 'config.json')
    settings.config_file = dir_path

if not os.path.isfile(settings.config_file):
    print(f"Config file does not exist: {settings.config_file}")
    exit()

logger = logging.getLogger("seedarr")
logger.setLevel(cfg.read_config("loglevel").upper())
console = logging.StreamHandler(sys.stdout)
console.setLevel(cfg.read_config("loglevel").upper())
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(filename)s - %(message)s', datefmt='%y-%m-%d,%H:%M:%S')
console.setFormatter(formatter)
logger.addHandler(console)

sched = BackgroundScheduler(timezone="America/New_York")

def init():
    if args.add_id is not None:
        settings.watch.append(args.add_id)
    if not args.skip_hash and cfg.read_config("calculate_hashes"):
        settings.calculate_hashes = True
    

def check_endpoints():
    logger.info("Checking endpoints...")
    try:
        logger.info(f"Checking connection to torrent client({cfg.read_config('torrent_client')})...")
        settings.client = Client(host=cfg.read_config("torrent_host"), username=cfg.read_config("torrent_username"), password=cfg.read_config("torrent_password"))
        logger.info(settings.client.app_version())
        logger.info("Success!")
    except Exception as e:
        logger.error(f"Error connecting to the torrent client: {e}")
        exit(1)
    try:
        logger.info(f"Checking connection to Radarr...")
        settings.radarr = RadarrAPI(cfg.read_config("radarr_host"), cfg.read_config("radar_api_key"))
        settings.radarr.get_health()
        logger.info("Success!")
    except Exception as e:
        logger.error(f"Error connecting to the torrent client: {e}")
        exit(1)

def get_missing():
    movies = settings.radarr.get_movie()    
    for movie in movies:
        if movie['monitored']:
            if not movie['hasFile'] and movie['tmdbId'] not in settings.watch:
                logger.info(f"Adding to monitored movies: '{movie['title']}' with id {movie['tmdbId']}")
                settings.watch.append(movie['tmdbId'])

def update_state():
    found = False
    unwatch = []
    if len(settings.watch) == 0:
        logger.debug("Watch queue empty.")
        return
    logger.debug("Looking for state changes...")
    for id in settings.watch:
        movie = settings.radarr.get_movie(id)
        if len(movie) == 1:
            movie = movie[0]
            if movie['hasFile'] or movie['tmdbId'] == args.force_state_change:
                found = True
                logger.info(f"Movie '{movie['title']}' has changed state, queueing for torrent client check.")
                if id not in settings.changed:
                    settings.changed.append(id)
                if id not in unwatch:
                    unwatch.append(id)
    for i in unwatch:
        settings.watch.remove(i)
    if not found:
        logger.debug("No state changes found.")

def blake(file):
    with open(file, "rb") as f:
        file_hash = hashlib.blake2b()
        while chunk := f.read():
            file_hash.update(chunk)
    return file_hash.hexdigest()

def move_torrent(t, movie, rename):
    # Removing before hash check to prevent threads from analyzing the same file
    if movie['tmdbId'] in settings.changed:
        settings.changed.remove(movie['tmdbId'])
    new_path = movie['movieFile']['path'].replace(cfg.read_config("radarr_library_directory"), cfg.read_config("torrent_library_directory"))
    if settings.calculate_hashes:
        logger.info("Comparing hashes to ensure files are identical")
        lib_file = blake(t['content_path'])
        download_file = blake(new_path)
        logger.debug(f"{lib_file} -- {t['content_path']}")
        logger.debug(f"{download_file} -- {new_path}")
        if not lib_file == download_file:
            logger.error("Invalid hashes, re-qeueuing.")
            return
        else:
            logger.info(f"{lib_file} and {download_file} hashes are identical.")
    else:
        logger.info("'--skip-hash' set, skipping hash check.")
    if rename:
        logger.debug("This torrent is in a folder and requires a rename before moving.")
        rename_path = os.path.dirname(new_path)
        logger.debug(f"Renaming {ntpath.basename(os.path.dirname(t['content_path']))} to {ntpath.basename(rename_path)}")
        try:
            settings.client.torrents_rename_folder(t['hash'], ntpath.basename(os.path.dirname(t['content_path'])), ntpath.basename(rename_path))
            # Let the client rename the folder
            time.sleep(5)
            logger.info(f"Torrent moved, deleting old directory({os.path.dirname(t['content_path'])})")
            # Failsafe
            if os.path.dirname(t['content_path']) != cfg.read_config("torrent_library_directory") and os.path.dirname(t['content_path']) != cfg.read_config("radarr_library_directory") and os.path.dirname(t['content_path']) != cfg.read_config("torrent_download_directory"):
                try:
                    shutil.rmtree(os.path.dirname(t['content_path']))
                except Exception as ex:
                    logger.error(f"Error deleting old directory: {ex}")
                    logger.debug(f"Error deleting old directory({os.path.dirname(t['content_path'])}): {ex}")
            else:
                logger.error(f"Hitting failsafe to prevent library deletion -> {os.path.dirname(t['content_path'])}")
            t['content_path'] = os.path.join(cfg.read_config("torrent_download_directory"), ntpath.basename(rename_path))
        except Exception as ee:
            logger.error(f"Error renaming torrent: {ee}")
            logger.debug(f"Error renaming torrent | {t['content_path']}, {rename_path}, {new_path}: {ee}")
    try:
        og_path = t['content_path']
        if rename:
            logger.info(f"Moving torrent({t['hash']}) from {t['content_path']} to {os.path.dirname(new_path)}")
            logger.debug("Renamed -> set_location")
            t.set_location(location=cfg.read_config("torrent_library_directory"))
        else:
            logger.info(f"Moving torrent({t['hash']}) from {t['content_path']} to {new_path}")
            t.set_location(location=os.path.dirname(new_path))
        logger.info(f"{movie['title']} moved. Removing from watch queue.")
        if movie['tmdbId'] in settings.changed:
            settings.changed.remove(movie['tmdbId'])
        logger.info(f"Queueing {t['name']} for deletion")
        if rename:
                # Renamed files only have a folder, adding a fake file to prevent dirname going up too much.
                og_path = os.path.join(og_path, "fakefile.mkv")
        if {"torrent": t, "original_path": og_path} not in settings.to_delete:
            logger.debug({"torrent": t, "original_path": og_path})
            settings.to_delete.append({"torrent": t, "original_path": og_path})
    except Exception as e:
        logger.error(f"Could not move torrent: {t['name']}. {e}")
        # re-adding on failure
        if movie['tmdbId'] not in settings.changed:
            settings.changed.append(movie['tmdbId'])

def match_and_move_torrents():
    found = False
    torrents = settings.client.torrents_info(category=cfg.read_config("torrent_category"))
    if len(settings.changed) == 0:
        logger.debug("Change queue empty.")
        return
    if len(torrents) > 0:
        logger.debug("Looking for torrent file match...")
    for id in settings.changed:
        movie = settings.radarr.get_movie(id)
        if len(movie) == 1:
            movie = movie[0]
            logger.debug(f"Looking for movie: {movie['title']} ({movie['movieFile']['relativePath']})")
            for t in torrents:
                for f in settings.client.torrents_files(torrent_hash=t['hash']):
                    if movie['movieFile']['relativePath'] == ntpath.basename(f['name']):
                        found = True
                        rename_needed = False
                        logger.info(f"Found a match for {movie['title']} with torrent: {t['name']}.")
                        t['content_path'] = os.path.join(t['content_path'],ntpath.basename(f['name']))
                        if ntpath.basename(f['name']) != f['name']:
                            rename_needed = True
                        move_torrent(t, movie, rename_needed)
                        break
    if not found and len(torrents) > 0:
        logger.warning(f"{len(settings.changed)} changes in Radarr but no match found in your torrent client.")

def check_and_delete():
    deleted = []
    for torrent in settings.to_delete:
        status = settings.client.torrents_info(torrent_hashes=torrent["torrent"]['hash'])[0]
        if status['state'] not in ["error", "checkingUP", "moving", "unknown"]: 
            logger.info(f"{status['name']}'s state is '{status['state']}', deleting: {os.path.dirname(torrent['original_path'])}")
            if not args.no_delete:
                try:
                    # Failsafe
                    if os.path.dirname(torrent['original_path']) != cfg.read_config("torrent_library_directory") and os.path.dirname(torrent['original_path']) != cfg.read_config("radarr_library_directory") and os.path.dirname(torrent['original_path']) != cfg.read_config("torrent_download_directory"):
                            if os.path.isdir:
                                shutil.rmtree(os.path.dirname(torrent['original_path']))
                            else:
                                os.remove(os.path.dirname(torrent['original_path']))
                    else:
                        logger.error(f"Hitting failsafe to prevent library deletion -> {os.path.dirname(torrent['original_path'])}")
                    if torrent not in deleted:
                        deleted.append(torrent)
                    logger.info(f"{os.path.dirname(torrent['original_path'])} deleted.")
                except Exception as e:
                    logger.error(f"Error deleting {os.path.dirname(torrent['original_path'])}, {e}")
            else:
                logger.info("'--no-delete' set, skipping deletion.")
                if torrent not in deleted:
                    deleted.append(torrent)
        else:
            logger.debug(f"{status['name']}'s state is '{status['state']}', not ready for deletion.")
    for i in deleted:
        settings.to_delete.remove(i)

def save():
    if args.no_save:
        return
    savepath = os.path.dirname(settings.config_file)
    try:
        logger.debug("Saving...")
        watch = open(os.path.join(savepath, "watch.json"), "w")
        changed = open(os.path.join(savepath, "changed.json"), "w")
        to_delete = open(os.path.join(savepath, "to_delete.json"), "w")
        watch.write(json.dumps(settings.watch))
        changed.write(json.dumps(settings.changed))
        to_delete.write(json.dumps(settings.to_delete))
        watch.close()
        changed.close()
        to_delete.close()
        logger.debug("Saved.")
    except Exception as e:
        logger.error(f"Error saving data. {e}")

def load():
    savepath = os.path.dirname(settings.config_file)
    try:
        logger.info("Loading data...")
        logger.debug(f"Path: {savepath}")
        if os.path.isfile(os.path.join(savepath, "watch.json")):
            watch = open(os.path.join(savepath, "watch.json"), "r")
            settings.watch = json.loads(watch.read())
            watch.close()
            logger.debug(settings.watch)
        if os.path.isfile(os.path.join(savepath, "changed.json")):
            changed = open(os.path.join(savepath, "changed.json"), "r")
            settings.changed = json.loads(changed.read())
            changed.close()
            logger.debug(settings.changed)
        if os.path.isfile(os.path.join(savepath, "to_delete.json")):
            to_delete = open(os.path.join(savepath, "to_delete.json"), "r")
            settings.to_delete = json.loads(to_delete.read())
            to_delete.close()
            logger.debug(settings.to_delete)
        logger.info("Data loaded.")
    except Exception as e:
        logger.error(f"Error loading data. {e}")

def clean_shutdown(force=True):
    save()
    sched.shutdown(wait=not force)
    logger.info("Goodbye.")
    exit()

def signal_handler(sig, frame):
    clean_shutdown()

signal.signal(signal.SIGINT, signal_handler)
init()
check_endpoints()
load()
logger.info("Starting scheduler...")
sched.add_job(get_missing, 'interval', seconds=cfg.read_config("missing_status_scan_interval"), max_instances=10, id="missing_status_scan")
sched.add_job(update_state, 'interval', seconds=cfg.read_config("state_change_scan_interval"), max_instances=10, id="state_change_scan")
sched.add_job(match_and_move_torrents, 'interval', seconds=cfg.read_config("match_and_move_torrents_scan_interval"), max_instances=10, id="match_and_move_torrents_scan")
sched.add_job(check_and_delete, 'interval', seconds=cfg.read_config("check_and_delete_scan_interval"), max_instances=1, id="check_and_delete_scan")
sched.add_job(save, 'interval', seconds=300, max_instances=1, id="save")
sched.start()
logger.info("Waiting.")
while True:
    time.sleep(1)