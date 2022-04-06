import json
import logging
import os
import settings


logger = logging.getLogger("seedarr")

def read_config(cfg):
    try:
        logger.debug(f"Reading from: {settings.config_file}")
        cfg_file = json.load(open(settings.config_file))
    except Exception as e:
        logger.error(f"{os.path.join(settings.config_file)} contains invalid JSON. ({e})")

    for k in cfg_file:
        if k == cfg:
            return cfg_file[k]

    
