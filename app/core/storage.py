# Where measurements live on the Pi and on the USB flash drive.
#
# One surveyed point is one recording: a raw file and a metadata file sharing
# the same name. Measuring the same point again keeps both, the newer one gets
# a counter appended.
#
# Recordings go straight onto the flash drive when one is plugged in, so the
# data leaves with the drive and nothing has to be copied afterwards. Without a
# drive they land in local storage and can be moved onto a drive later.
import os
import re
import shutil
import unicodedata

from app.core import config

RAW_SUFFIX = ".ubx"
META_SUFFIX = ".json"

LOCATION_USB = "usb"
LOCATION_LOCAL = "local"

# Anything else in a name would either break the path or escape the data folder
UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name: str) -> str:
    """Turns user input into something safe to use as a file name.

    Parameters:
        name (string): Point id as it came from the request

    Returns:
        str: The cleaned name, empty when nothing usable is left
    """
    if not name:
        return ""

    # Czech names keep their meaning this way, mereni instead of m__en_
    stripped = unicodedata.normalize("NFKD", name.strip())
    stripped = stripped.encode("ascii", "ignore").decode("ascii")

    cleaned = UNSAFE_CHARS.sub("_", stripped)

    # Leading dots would hide the file or point at the parent directory
    return cleaned.strip("._")


# --- Locations ---------------------------------------------------------------

def get_usb_root():
    """The first mounted flash drive.

    Returns:
        str: Mount point of the drive, or False when nothing is mounted
    """
    base_path = config.BASE_USB_PATH

    try:
        devices = sorted(os.listdir(base_path))
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return False

    folders = [os.path.join(base_path, d) for d in devices]
    folders = [f for f in folders if os.path.isdir(f)]

    # An unclean unplug can leave an empty folder behind. Writing into it would
    # quietly fill the SD card instead of the drive, so a real mount wins.
    for folder in folders:
        if os.path.ismount(folder):
            return folder

    # On Linux a folder that is not a mount point means no drive is plugged in.
    # Anywhere else there is nothing to check, which keeps development working.
    if folders and not _is_linux():
        return folders[0]

    return False


def _is_linux() -> bool:
    """True on the Raspberry Pi, where mount points can be checked."""
    return os.path.exists("/proc/mounts")


def get_usb_path(create=True):
    """Folder for measurements on the flash drive.

    Recordings go into a subfolder rather than the root of the drive, so the
    drive can hold other things too.

    Returns:
        str: The folder, or False when no drive is mounted or it is read only
    """
    root = get_usb_root()

    if not root:
        return False

    folder = os.path.join(root, config.USB_SUBDIR) if config.USB_SUBDIR else root

    if not create:
        return folder

    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        print(f"Flash drive is not writable: {e}")
        return False

    return folder


def get_local_path(create=True) -> str:
    """The fallback folder on the Pi itself."""
    folder = config.LOCAL_DATA_PATH

    if create and not os.path.exists(folder):
        os.makedirs(folder)

    return folder


def get_write_path():
    """Where the next recording should go.

    Returns:
        tuple: (folder, location), location is "usb" or "local"
    """
    if config.PREFER_USB:
        usb_path = get_usb_path()

        if usb_path:
            return usb_path, LOCATION_USB

    return get_local_path(), LOCATION_LOCAL


def get_folder(location: str):
    """Folder of one location, without creating anything."""
    if location == LOCATION_USB:
        return get_usb_path(create=False)

    return get_local_path(create=False)


def free_bytes(folder) -> int:
    """Free space of the filesystem a folder sits on, 0 when unknown."""
    if not folder or not os.path.exists(folder):
        return 0

    try:
        return shutil.disk_usage(folder).free
    except Exception:
        return 0


def get_state() -> dict:
    """Where recordings go and how much room is left."""
    usb_path = get_usb_path(create=False)
    local_path = get_local_path(create=False)
    target, location = get_write_path()

    return {
        "prefer_usb": config.PREFER_USB,
        "usb_mounted": bool(usb_path) and os.path.exists(usb_path),
        "usb_base": config.BASE_USB_PATH,
        "usb_path": usb_path or None,
        "usb_free_bytes": free_bytes(usb_path),
        "local_path": local_path,
        "local_free_bytes": free_bytes(local_path if os.path.exists(local_path) else None),
        "writing_to": location,
        "write_path": target,
    }


# --- Points ------------------------------------------------------------------

def unique_name(base_name: str, folder: str) -> str:
    """First free name for a point, counting up until one is unused.

    A second measurement of B1 becomes B1_1, a third B1_2, and so on. Both
    locations are checked, so a point recorded locally and then again onto a
    flash drive still gets a fresh name.

    Parameters:
        base_name (string): Already cleaned point name
        folder (string): Where the recording is about to be written

    Returns:
        str: Name without a suffix
    """
    folders = [folder]

    for other in (get_usb_path(create=False), get_local_path(create=False)):
        if other and other not in folders:
            folders.append(other)

    def taken(name):
        return any(os.path.exists(os.path.join(f, name + RAW_SUFFIX)) for f in folders if f)

    if not taken(base_name):
        return base_name

    counter = 1
    while taken(f"{base_name}_{counter}"):
        counter += 1

    return f"{base_name}_{counter}"


def _points_in(folder, location):
    """Recordings found in one folder."""
    if not folder or not os.path.exists(folder):
        return []

    try:
        names = os.listdir(folder)
    except Exception as e:
        print(f"Directory list failed: {e}")
        return []

    points = []

    for name in sorted(names):
        if not name.endswith(RAW_SUFFIX):
            continue

        raw_path = os.path.join(folder, name)

        try:
            size = os.path.getsize(raw_path)
            modified_ns = os.path.getmtime(raw_path) * 1e9
        except Exception:
            size = 0
            modified_ns = 0

        points.append({
            "name": name[:-len(RAW_SUFFIX)],
            "location": location,
            "size_bytes": size,
            "modified_ns": int(modified_ns),
        })

    return points


def get_points():
    """Every recording, on the flash drive and on the Pi.

    Returns:
        list: Dicts with name, location, size and modification time
    """
    points = _points_in(get_usb_path(create=False), LOCATION_USB)
    points += _points_in(get_local_path(create=False), LOCATION_LOCAL)

    return points


def find_point(point_name):
    """Where one recording lives.

    The flash drive is looked at first, matching where new recordings go.

    Returns:
        tuple: (folder, location, files), or (None, None, None) when not found
    """
    name = safe_name(point_name)

    if not name:
        return None, None, None

    for folder, location in (
        (get_usb_path(create=False), LOCATION_USB),
        (get_local_path(create=False), LOCATION_LOCAL),
    ):
        if not folder:
            continue

        files = [f for f in (name + RAW_SUFFIX, name + META_SUFFIX)
                 if os.path.exists(os.path.join(folder, f))]

        if files:
            return folder, location, files

    return None, None, None


def get_point_files(point_name):
    """Files belonging to one point, raw and metadata.

    Returns:
        dict: Location and file names

        2: no such point
    """
    folder, location, files = find_point(point_name)

    if not files:
        return 2

    return {"location": location, "point_files": files}


def delete_point(point_name):
    """Removes one recording.

    Returns:
        True on success, 2 no such point, 3 delete failed
    """
    folder, location, files = find_point(point_name)

    if not files:
        return 2

    for name in files:
        try:
            os.remove(os.path.join(folder, name))
        except Exception as e:
            print(f"Delete failed: {e}")
            return 3

    return True


def download_point(point_name, cleanup=False):
    """Moves a locally stored recording onto the flash drive.

    Recordings made while a drive was plugged in are already on it and need
    nothing done.

    Returns:
        True on success, 2 no such point, 3 copy failed, 4 cleanup failed,
        5 already on the flash drive, 6 no flash drive mounted
    """
    folder, location, files = find_point(point_name)

    if not files:
        return 2

    if location == LOCATION_USB:
        return 5

    usb_path = get_usb_path()

    if not usb_path:
        return 6

    try:
        for name in files:
            shutil.copy2(os.path.join(folder, name), os.path.join(usb_path, name))
    except Exception as e:
        print(f"Copy failed: {e}")
        return 3

    if cleanup:
        for name in files:
            try:
                os.remove(os.path.join(folder, name))
            except Exception as e:
                print(f"Cleanup failed: {e}")
                return 4

    return True


def download_all(cleanup=False) -> dict:
    """Moves every locally stored recording onto the flash drive."""
    result = {"copied": [], "failed": [], "skipped": []}

    if not get_usb_path():
        result["failed"] = [p["name"] for p in _points_in(get_local_path(create=False), LOCATION_LOCAL)]
        return result

    for point in _points_in(get_local_path(create=False), LOCATION_LOCAL):
        outcome = download_point(point["name"], cleanup)

        if outcome is True:
            result["copied"].append(point["name"])
        elif outcome == 5:
            result["skipped"].append(point["name"])
        else:
            result["failed"].append(point["name"])

    return result
